# streamlit_app — Web版 (社内ベータ)

CLI版と同じロジックを、ブラウザから使える Web アプリにしたものです。
[Streamlit](https://streamlit.io/) で動きます。

## 用途

- **Phase 1 (現在)**: パスワードで守られたクローズドβ。チームメンバーが共有された URL + パスワードでアクセスして試用する
- **Phase 2 (未定)**: Phase 1 で好評だった場合、パスワードを外して一般公開する。同時に BYO Key モードを追加する

## デプロイ (Streamlit Community Cloud)

無料枠でホスティングできます。手順:

1. このリポジトリを GitHub に push
2. <https://share.streamlit.io> にログイン
3. 「New app」→ このリポジトリを選択
4. **Main file path** に `streamlit_app/app.py` を指定
5. 「Advanced settings」→ Secrets に以下を貼り付け:

```toml
SERPER_API_KEY = "実際のSerperキー"
GEMINI_API_KEY = "実際のGeminiキー"
APP_PASSWORD = "チーム内で共有する任意のパスワード"

# 任意: エラーやフィードバック連絡先の表示名
# 未設定の場合は「管理者」と表示されます
ADMIN_CONTACT = "運営者名 (Slack: @xxx など)"
```

6. Deploy をクリック

数分でビルドが終わり、`https://xxxxx.streamlit.app` のようなURLが払い出されます。

## Secrets の管理

`SERPER_API_KEY` と `GEMINI_API_KEY` は **Streamlit Cloud の Secrets 画面にのみ**
保存してください。このリポジトリのコードには絶対に書き込まないこと。

パスワードを変更したい場合も、Secrets 画面の `APP_PASSWORD` の値を書き換えるだけです。
コードの変更は不要です。

## コスト保険

デプロイした人(あなた)の財布を守るため、以下を必ず設定しておいてください:

- **Serper.dev** → 管理画面で月額上限を **$0** (=無料枠のみ) に設定
- **Google AI Studio** → プロジェクトの月次予算を **¥0** に設定

無料枠を使い切ると、アプリは自動的に「今月の無料枠を使い切りました」というエラー表示になるだけで、
請求は一切発生しません。

## ローカルで動作確認したい場合

```bash
cd streamlit_app
pip install -r requirements.txt

# Secrets をローカルにも用意
mkdir -p .streamlit
cat > .streamlit/secrets.toml <<'EOF'
SERPER_API_KEY = "..."
GEMINI_API_KEY = "..."
APP_PASSWORD = "test"
EOF

streamlit run app.py
```

**注意**: `.streamlit/secrets.toml` は `.gitignore` で除外済みです。
絶対に commit しないこと。
