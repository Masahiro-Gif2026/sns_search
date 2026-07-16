"""
SNS検索ツール — 社内ベータ版 (Phase 1)
========================================
Streamlit で動く Web 版。ブラウザからキーワードを入れると、
X と Instagram の直近投稿を集めて Google Gemini で判定・要約して表示します。

APIキーは Streamlit Cloud の Secrets に設定して使います。
ソースコード自体には秘密情報は含まれません。
"""
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import requests
import streamlit as st


# ────────────────────────────────────────────────────────
# ページ設定
# ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SNS検索ツール (社内β)",
    page_icon="🔍",
    layout="wide",
)


# ────────────────────────────────────────────────────────
# パスワードゲート
# ────────────────────────────────────────────────────────
def check_password() -> bool:
    """認証済みなら True、未認証なら入力フォームを描画して False を返す。"""
    if st.session_state.get("authenticated"):
        return True

    st.title("🔒 SNS検索ツール (社内β版)")
    st.write("社内で共有されているパスワードを入力してください。")

    with st.form("login_form", clear_on_submit=False):
        pwd = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン", type="primary")

    if submitted:
        expected = st.secrets.get("APP_PASSWORD", "")
        if pwd and pwd == expected:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    return False


if not check_password():
    st.stop()


# ────────────────────────────────────────────────────────
# 設定
# ────────────────────────────────────────────────────────
def _get_secret(name: str) -> str:
    val = st.secrets.get(name, "")
    if not val:
        admin = st.secrets.get("ADMIN_CONTACT", "管理者")
        st.error(
            f"⚠️ 設定エラー: `{name}` が Streamlit Cloud の Secrets に登録されていません。"
            f"\n\n{admin}にご連絡ください。"
        )
        st.stop()
    return val


PLATFORMS = {"X": "twitter.com", "Instagram": "instagram.com"}


# ────────────────────────────────────────────────────────
# Serper で SNS を検索
# ────────────────────────────────────────────────────────
def search_serper(query: str, site: str, days: int, api_key: str) -> list:
    url = "https://google.serper.dev/search"
    date_limit = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    search_q = f'site:{site} "{query}" after:{date_limit}'
    payload = json.dumps({"q": search_q})
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = requests.post(url, headers=headers, data=payload, timeout=10)
        res.raise_for_status()
        return res.json().get("organic", [])
    except Exception as e:
        st.warning(f"⚠️ 検索エラー ({site}): {e}")
        return []


# ────────────────────────────────────────────────────────
# Gemini で一括判定 (バッチ)
# ────────────────────────────────────────────────────────
def classify_batch(posts: list, api_key: str) -> list:
    if not posts:
        return []

    model = "gemini-2.5-flash"
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?key={api_key}"
    )

    items = [
        {"id": i, "text": f"{p.get('title', '')} {p.get('snippet', '')}"}
        for i, p in enumerate(posts)
    ]
    prompt = f"""以下のSNS投稿リストを分析し、JSON配列のみで返してください。
配列の各要素は、対応する id の投稿の分析結果です。

投稿リスト:
{json.dumps(items, ensure_ascii=False, indent=2)}

返却形式(この配列のみ・前後に文を付けない):
[
  {{"id": 0, "trust_score": 1〜5の整数, "is_free": true/false, "summary": "15文字以内の要約"}},
  ...
]
"""
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    default = lambda: {"trust_score": 3, "is_free": False, "summary": "判定なし"}

    try:
        res = requests.post(url, json=body, timeout=60)
        res.raise_for_status()
        text = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        s, e = text.find("["), text.rfind("]") + 1
        arr = json.loads(text[s:e])
        by_id = {a.get("id"): a for a in arr if isinstance(a, dict)}
        return [by_id.get(i, default()) for i in range(len(posts))]
    except Exception as e:
        st.warning(f"⚠️ AI判定に失敗しました: {e}")
        return [default() for _ in posts]


# ────────────────────────────────────────────────────────
# サイドバー
# ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 検索オプション")
    days = st.slider("直近◯日以内の投稿を対象", 1, 30, 7)
    skip_ai = st.checkbox("AI判定をスキップ (処理を速くする)", value=False)

    st.markdown("---")
    admin = st.secrets.get("ADMIN_CONTACT", "管理者")
    st.caption(
        f"🧪 このツールはベータ版です。使ってみて気になった点は "
        f"{admin}までフィードバックをお願いします。"
    )

    if st.button("ログアウト", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()


# ────────────────────────────────────────────────────────
# メイン画面
# ────────────────────────────────────────────────────────
st.title("🔍 SNS検索ツール")
st.caption("キーワードを入れると、X と Instagram の直近投稿を集めて、AIが要約します。")

query = st.text_input(
    "キーワード",
    value="",
    placeholder="例: スケートボード、東京 カメラ、無料講座 など",
)

search = st.button("検索する", type="primary", disabled=not query)

if search:
    serper_key = _get_secret("SERPER_API_KEY")
    gemini_key = _get_secret("GEMINI_API_KEY")

    # 各プラットフォームを並列で検索
    with st.spinner("Serper で X と Instagram を検索中..."):
        with ThreadPoolExecutor(max_workers=len(PLATFORMS)) as ex:
            futures = {
                name: ex.submit(search_serper, query, domain, days, serper_key)
                for name, domain in PLATFORMS.items()
            }
            all_results = {name: fut.result() for name, fut in futures.items()}

    # プラットフォーム情報を保持して平坦化
    flat = [(plat, post) for plat, posts in all_results.items() for post in posts]

    if not flat:
        st.info(
            "😕 該当する投稿が見つかりませんでした。"
            "キーワードを変えたり、期間(左のスライダー)を長めにして試してみてください。"
        )
        st.stop()

    # AI判定 (バッチで1回だけ呼ぶ)
    ai_results = [None] * len(flat)
    if not skip_ai:
        with st.spinner(f"Gemini で {len(flat)} 件をまとめて判定中..."):
            ai_results = classify_batch([p for _, p in flat], gemini_key)

    # サマリバー
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("検索結果", f"{len(flat)} 件")
    with c2:
        useful = sum(1 for a in ai_results if a and a.get("trust_score", 0) >= 4)
        st.metric("★4以上", f"{useful} 件")
    with c3:
        free = sum(1 for a in ai_results if a and a.get("is_free"))
        st.metric("無料情報", f"{free} 件")

    st.markdown("---")

    # 結果カード
    for (plat, post), ai in zip(flat, ai_results):
        color = "#000000" if plat == "X" else "#E1306C"
        with st.container(border=True):
            top1, top2 = st.columns([1, 8])
            with top1:
                st.markdown(
                    f"<div style='background:{color};color:white;"
                    f"padding:6px 12px;border-radius:6px;font-weight:bold;"
                    f"display:inline-block;font-size:14px;'>{plat}</div>",
                    unsafe_allow_html=True,
                )
            with top2:
                st.markdown(f"**{post.get('title', '(タイトル無し)')}**")

            st.write(post.get("snippet", ""))

            if ai:
                try:
                    stars = "★" * int(ai.get("trust_score", 3))
                except (TypeError, ValueError):
                    stars = "★★★"
                free_badge = "🆓 無料" if ai.get("is_free") else ""
                st.markdown(
                    f"<div style='background:#e8f0fe;padding:10px 14px;"
                    f"border-radius:6px;font-size:14px;margin:6px 0;'>"
                    f"<b>AIの要約:</b> {ai.get('summary', '')} {stars} {free_badge}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            if post.get("link"):
                st.link_button("👉 投稿を開く", post["link"])
