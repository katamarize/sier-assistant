# CLAUDE.md

## プロジェクト概要

毎朝、自分に必要な情報を自動で収集・整理・通知する自分専用アシスタント。
ローカルLLM(llama-server)で運用し、学習・Zenn発信・ポートフォリオを兼ねる個人プロジェクト。

- **設計の正は [DESIGN.md](DESIGN.md)**。設計思想・技術選定はここで決定済み。再議論しない
- **進捗と実装計画は [PLAN.md](PLAN.md)(M1、完了)と [PLAN-M2.md](PLAN-M2.md)(M2、進行中)**。Step単位で進める。モジュール間契約(C1〜C6)はPLAN.md、M2での追加(C7等)はPLAN-M2.mdに定義
- 契約(LLM出力スキーマ、itemsテーブル、sources.yaml等)を変更するときは **PLAN.md §4 影響マトリクスを確認し、DESIGN.md と PLAN.md の両方を更新する**

## 重要な前提(間違えやすい点)

- LLM実行は **llama.cpp(llama-server、localhost:8080、OpenAI互換API)**。当初のOllamaからBSODインシデントを機に移行済み。「Ollama」が残っているのは過去の記事・記録のみ
- LLMの役割は「理解・整理」に限定。**収集・差分検知は決定論的にPythonで行う**(LLMにやらせない)
- llama-serverは手動起動(qwen-start.bat)。停止していてもパイプラインは壊れない設計(items.status = pending で再試行)
- コアロジックはPythonに置く。n8n / Docker / Notion はマイルストーン2以降まで導入しない

## コマンド

```powershell
uv run main.py                # エントリポイント
uv run python -m src.pipelines.daily_news   # パイプライン実行(例)
uv add <package>              # 依存追加(pip installは使わない)
```

- Python 3.12 / uv / Windows。環境変数は `.env`(`.env.example` 参照)
- 監視対象は `config/sources.yaml`(スキーマは `sources.example.yaml` と PLAN.md C4)
- DBは `data/assistant.db`(SQLite)。個人用ローカルDBなので破壊的変更は作り直しで許容

## ディレクトリ

| パス | 内容 |
|---|---|
| `src/collectors/` | 収集(RSS等)。決定論的処理のみ |
| `src/core/` | models(dataclass) / config / storage(SQLite) / diff |
| `src/llm/` | llama-serverクライアント + `prompts/`(プロンプトは.mdで管理) |
| `src/pipelines/` | 収集→差分→LLM→保存の結合 |
| `src/notifiers/` | Slack通知(Step 4) |
| `articles/` | ZennのStep別記事下書き |
| `bug_doc/` | インシデント・不具合の記録 |

## 作業ルール

- **Step完了時は PLAN.md §0 の進捗トラッカーを更新**する(状態・完了日)
- インシデントや躓きは `bug_doc/` に記録し、記事ネタになりそうなら `articles/` の下書きに反映を提案する
- ユーザーは新人SIerで学習目的も兼ねる。**実装時は「何をしたか」だけでなく「なぜそうするか」を簡潔に説明**する(ただし冗長にしない)
- 回答・コミットメッセージ・ドキュメントは日本語

## サブエージェント運用(モデル使い分け)

- ファイル探索・要約・コマンド実行・typo修正などの軽作業は **quick-worker(Haiku)** に、仕様が明確な実装・テスト・リファクタリングは **coder(Sonnet)** に委譲してよい(常設許可)
- 独立したサブタスクは並列でスポーンする
- タスク分解・設計判断・成果物のレビューは委譲せずメイン(司令塔)が行う
- 大きめのタスクは `/orchestrate` で手順書付きのオーケストレーションを使う
- 迷ったら1段上のモデルに振る。数行で終わる作業は委譲しない
