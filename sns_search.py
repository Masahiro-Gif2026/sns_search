import os
import json
import html
import logging
import requests
import webbrowser
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import google.generativeai as genai  # 元のライブラリのまま
from dotenv import load_dotenv
import warnings

# 警告（黄色い文字）を表示させないようにする
warnings.filterwarnings("ignore")

# print の代わりにロガーを使用（エラーを握りつぶさず記録する）
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

load_dotenv()

SERPER_KEY = os.getenv("SERPER_API_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# 【改善3】HTTP接続を使い回すためのセッションを1つだけ生成
SESSION = requests.Session()

# 【改善3】Geminiモデルは投稿ごとに作り直さず、起動時に一度だけ生成して再利用
MODEL = None
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    MODEL = genai.GenerativeModel("gemini-2.5-flash")


def _default_analysis(summary="AI判定スキップ", score=3):
    return {"trust_score": score, "is_free": False, "summary": summary}


def get_ai_analysis_batch(posts):
    """【改善1】全投稿を1回のリクエストにまとめて判定する（API往復をN回→1回に削減）。

    返り値は posts と同じ長さ・同じ順序のリスト。
    """
    if not posts:
        return []
    if not GEMINI_KEY or MODEL is None:
        return [_default_analysis("APIキー未設定", 1) for _ in posts]

    # 各投稿に id を振り、テキストをまとめてプロンプト化
    items = [
        {"id": i, "text": f"{p.get('title', '')} {p.get('snippet', '')}"}
        for i, p in enumerate(posts)
    ]
    prompt = f"""以下のSNS投稿リストを分析し、結果を必ずJSON配列のみで返してください。
配列の各要素は、対応する id の投稿の分析結果です。

投稿リスト:
{json.dumps(items, ensure_ascii=False, indent=2)}

返却形式（この配列形式のみで返すこと。前後に説明文を付けない）:
[
  {{"id": 0, "trust_score": 1から5の数値, "is_free": 内容が無料ならtrueそれ以外false, "summary": "15文字以内の要約"}},
  ...
]
"""
    try:
        text = MODEL.generate_content(prompt).text.strip()
        json_start = text.find("[")
        json_end = text.rfind("]") + 1
        arr = json.loads(text[json_start:json_end])

        # id をキーに辞書化し、元の順序で取り出す（欠損時はデフォルト）
        by_id = {a.get("id"): a for a in arr if isinstance(a, dict)}
        return [by_id.get(i, _default_analysis()) for i in range(len(posts))]
    except Exception as e:
        log.warning(f"  ⚠ AIバッチ判定に失敗しました: {e}")
        return [_default_analysis() for _ in posts]


def search_sns(query, site, days):
    url = "https://google.serper.dev/search"
    date_limit = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    search_query = f'site:{site} "{query}" after:{date_limit}'

    payload = json.dumps({"q": search_query})
    headers = {"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"}

    try:
        # 【改善3】SESSION を使い回し、timeout を必ず指定して無限待ちを防ぐ
        res = SESSION.post(url, headers=headers, data=payload, timeout=10)
        res.raise_for_status()
        return res.json().get("organic", [])
    except Exception as e:
        log.warning(f"  ⚠ 検索に失敗しました ({site}): {e}")
        return []


def generate_report(all_results, query, days, no_classify):
    # プラットフォーム情報を保持したまま全投稿を平坦化
    flat = []
    for platform, posts in all_results.items():
        for post in posts:
            flat.append((platform, post))

    # 【改善1】AI判定はループ内で1件ずつではなく、ここで一括実行
    analyses = [None] * len(flat)
    if not no_classify and flat:
        log.info(f"  → AI分析中: {len(flat)} 件をまとめて判定...")
        analyses = get_ai_analysis_batch([p for _, p in flat])

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: sans-serif; background: #f0f2f5; max-width: 800px; margin: 40px auto; padding: 20px; }}
            .card {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            .X {{ border-left: 8px solid #000; }}
            .Instagram {{ border-left: 8px solid #E1306C; }}
            .ai-badge {{ background: #e8f0fe; padding: 10px; border-radius: 6px; margin-top: 10px; font-size: 14px; }}
            .btn {{ display: inline-block; padding: 8px 16px; border-radius: 6px; text-decoration: none; color: white; background: #1a73e8; font-weight: bold; margin-top: 10px; }}
        </style>
    </head>
    <body>
        <h1 style="text-align:center;">🛹 SNSお宝情報レポート</h1>
        <p style="text-align:center;">キーワード: {html.escape(query)} / 過去 {days} 日分</p>
    """

    for (platform, post), ai in zip(flat, analyses):
        ai_html = ""
        if ai:
            try:
                stars = "★" * int(ai.get("trust_score", 3))
            except (TypeError, ValueError):
                stars = "★" * 3
            ai_html = f"""
            <div class="ai-badge">
                <strong>AIの要約:</strong> {html.escape(str(ai.get('summary', '')))} {stars}
            </div>
            """

        # タイトル・本文・リンクはHTMLエスケープしてレイアウト崩れや埋め込みを防ぐ
        title = html.escape(str(post.get("title", "")))
        snippet = html.escape(str(post.get("snippet", "")))
        link = html.escape(str(post.get("link", "")), quote=True)

        html_content += f"""
        <div class="card {platform}">
            <strong>{platform}</strong>
            <h3>{title}</h3>
            <p style="font-size:14px; color:#444;">{snippet}</p>
            {ai_html}
            <a href="{link}" target="_blank" class="btn">詳細を見る</a>
        </div>
        """

    html_content += "</body></html>"
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    webbrowser.open("file://" + os.path.abspath("report.html"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--days", type=int, default=7)
    # --no-classify という命令を受け取れるように設定
    parser.add_argument("--no-classify", action="store_true")
    args = parser.parse_args()

    platforms = {"X": "twitter.com", "Instagram": "instagram.com"}

    log.info(f"🚀 検索開始: {args.query}")

    # 【改善2】各プラットフォームの検索は互いに独立なので並列実行する
    with ThreadPoolExecutor(max_workers=len(platforms)) as ex:
        futures = {
            name: ex.submit(search_sns, args.query, domain, args.days)
            for name, domain in platforms.items()
        }
        all_results = {}
        for name, fut in futures.items():
            log.info(f"🔍 {name} を検索中...")
            all_results[name] = fut.result()

    generate_report(all_results, args.query, args.days, args.no_classify)
    log.info("✅ 完了しました！")


if __name__ == "__main__":
    main()
