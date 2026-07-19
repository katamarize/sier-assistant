# DESIGN.md — 自分専用SIerアシスタント

最終更新: 2026-07-13
ステータス: マイルストーン1 完了(2026-07-18)。マイルストーン2 計画中(PLAN-M2.md)

---

## 1. プロジェクトコンセプト

単なる「ローカルLLMを動かす」ではなく、**毎日自分が使うAIアシスタントを育て続けるプロジェクト**。
学習・実用・情報発信(Zenn)・ポートフォリオを一つに統合する。

### 背景
- 新人SIer。AI・ローカルLLM・自動化技術を学びたい
- 学んだ内容をZenn等で発信し、副業・転職時のポートフォリオに繋げたい
- API従量課金は極力避け、ローカルLLM(Ollama)で運用する

### 最終目標
毎朝、自分に必要な情報だけを自動で収集・整理・通知してくれる仕組み。
(ITニュース / 学習すべき内容 / 推しアーティスト情報 / タスク / 予定)

---

## 2. 設計思想(決定事項)

| 項目 | 決定 | 理由 |
|---|---|---|
| LLMの役割 | 収集ではなく「理解・整理」に限定 | 収集・差分検知は決定論的にPythonで行う方が安定 |
| 差分→LLMの結合 | キュー方式(疎結合) | LLM停止時もパイプラインが壊れない。statusで再試行 |
| 実行環境 | **メインPC 1台完結**(常時起動) | まずアプリを形にする。インフラ分散はその後 |
| 推論方式 | 差分検知したらその場でローカルLLMサーバーへ(準リアルタイム) | 両PC常時起動方針のため。将来WoL方式へ移行可能な設計は維持 |
| サブPC(ノート2台) | **将来検討**。現時点では計画から除外 | 24hサーバー化・検証環境化は マイルストーン2以降 |

---

## 3. アーキテクチャ(マイルストーン1)

```
情報ソース(RSS / 公式サイト / GitHub)
        ↓
メインPC(RTX3070・常時起動)
  ├ スケジューラ: Windowsタスクスケジューラ(朝夕2回)
  ├ 収集・差分検知: Python + SQLite
  ├ LLM分析: llama-server (localhost:8080, OpenAI互換API)
  └ 通知: Slack Incoming Webhook
```

- n8n / Docker / Ubuntu / Notion はこの段階では**使わない**(後続マイルストーン)
- llama-serverへの接続失敗時は items.status = pending のまま残し、次回実行時に再試行
- llama-serverは起動bat(`qwen-start.bat`)を手動起動している間だけ稼働。停止していてもパイプラインは壊れない(上記pending維持)が、Step 5の常駐化ではサーバー起動を前提条件として扱う

---

## 4. 技術選定(決定事項)

| 領域 | 採用 | 備考 |
|---|---|---|
| 言語 | Python 3.12系 | |
| パッケージ管理 | uv | pyproject.tomlベース。GitHub公開時にきれい |
| LLM実行 | llama.cpp(llama-server)のOpenAI互換API | 当初Ollamaだったが、Step 3検証中のBSOD(GPU/メモリ起因の疑い)を受けて移行。`--n-cpu-moe` でMoEエキスパートをCPU側に置きVRAM圧迫を回避 |
| モデル | Qwen3系 35B MoE(アクティブ約3B、IQ4_XS量子化) | llama-server起動bat(`-m`)で指定。モデル変更はbat編集(コード変更なし) |
| LLM出力 | structured output(response_formatにJSONスキーマ指定) | llama.cppがJSON SchemaをGBNF文法に変換し生成を制約。importance / tags / should_notify を機械可読で受ける |
| RSS取得 | feedparser | RSS/Atomがあるソースは必ずRSS優先 |
| HTML本文抽出 | trafilatura | CSS変更等のノイズを本文抽出の段階で除去 |
| 差分検知 | 本文抽出→正規化→ハッシュ化→SQLite比較 | RSSはentry idと更新日時で判定 |
| 状態管理 | SQLite | seen_items(既読) + items(キュー兼結果) |
| 通知 | Slack Incoming Webhook | 無料プランで可 |
| スケジューラ | Windowsタスクスケジューラ | cron / n8n は分散化の際に検討 |

### 見送り・保留
- **n8n**: 採用するとしてもオーケストレーションのみ。コアロジックはPythonに置く(ポートフォリオ価値のため)。マイルストーン2以降
- **X(Twitter)スクレイピング**: 規約・技術両面で困難。アーティスト情報は公式サイト・通販サイトに絞る
- **ノートPCでのCPU推論**: メモリ8GBでは品質・速度とも実用に届かないため不採用

---

## 5. データ設計

### sources.yaml(監視対象の宣言的定義)

```yaml
defaults:
  interval_hours: 6
  min_importance_to_notify: 3

sources:
  - id: aws-whats-new
    name: AWS What's New
    type: rss                # rss / html
    url: https://aws.amazon.com/about-aws/whats-new/recent/feed/
    category: it_news        # it_news / artist / learning
    tags_hint: [AWS, クラウド]

  - id: artist-goods
    name: ○○公式グッズ
    type: html
    url: https://example.com/goods
    category: artist
    selector: "main"
    interval_hours: 3
    min_importance_to_notify: 2
```

- collector は type だけ見て動く / 通知判定は category と閾値だけ見る(責務分離)
- ソース追加はコード変更なし・YAML追記のみで完結させる
- 個人設定(推しアーティスト等)は gitignore し、sources.example.yaml を公開用に置く

### SQLite

```sql
-- 既読管理(差分検知用)
CREATE TABLE seen_items (
    source_id    TEXT,
    item_key     TEXT,      -- RSS: entry id / HTML: 正規化本文のハッシュ
    content_hash TEXT,
    first_seen   TEXT,
    PRIMARY KEY (source_id, item_key)
);

-- 検知した差分と処理状態(キューを兼ねる)
CREATE TABLE items (
    id            INTEGER PRIMARY KEY,
    source_id     TEXT,
    title         TEXT,
    url           TEXT,
    content       TEXT,
    status        TEXT DEFAULT 'pending',
    importance    INTEGER,
    summary       TEXT,
    beginner_note TEXT,     -- Step3で追加。LLM出力(C1)のbeginner_noteをそのまま保持
    tags          TEXT,     -- JSON文字列
    should_notify INTEGER,  -- Step3で追加。LLM出力(C1)のshould_notifyを0/1で保持
    reason        TEXT,     -- Step3で追加。LLM出力(C1)のreason(デバッグ・プロンプト改善用)
    created_at    TEXT
);
```

status の状態遷移: `pending`(収集済) → `analyzed`(LLMがshould_notify=trueと判定) → `notified`(メインCHへ通知済)。`analyzed` のうちソースの `min_importance_to_notify` 未満はストックCHへ送り `stocked`(2026-07-17追加。ストック用Webhook未設定時は従来どおり `skipped`)。LLMが `should_notify=false` と判定した記事は `skipped`。通知は重要度の高い順に1メッセージ最大10件で分割送信する。

### LLM出力スキーマ(structured output)

```json
{
  "summary": "3行以内の日本語要約",
  "beginner_note": "新人SIerへの影響を1文で",
  "importance": 4,
  "tags": ["Java", "Spring"],
  "should_notify": true,
  "reason": "判定理由(デバッグ・プロンプト改善用)"
}
```

---

## 6. ディレクトリ構成(GitHub公開前提)

```
sier-assistant/
├── config/
│   └── sources.yaml
├── src/
│   ├── collectors/         # rss.py, html.py, github_releases.py
│   ├── core/               # diff.py, storage.py, models.py
│   ├── llm/                # ollama_client.py, prompts/
│   ├── notifiers/          # slack.py (将来: notion.py)
│   └── pipelines/          # daily_news.py (将来: goods_watch.py, morning_report.py)
├── scripts/                 # Step単位の動作確認スクリプト(check_llm.py等)
├── articles/                 # Zenn記事下書き(Step完了ごとに1本、PLAN.md §5 運用ルール6参照)
├── tests/
├── DESIGN.md               # 本ドキュメント
├── PLAN.md                 # 実装計画書(進捗トラッカー・契約・Step別仕様)
├── .env.example
└── README.md
```

APIキー・Webhook URLは .env 管理。公開リポジトリに秘密情報・個人情報を含めない。

---

## 7. ロードマップ

### マイルストーン1: メインPC 1台で動くニュース要約bot(目安1〜2週間)

| Step | 内容 | 完了条件 | 記事ネタ |
|---|---|---|---|
| 0 | 環境構築(Git / Python / uv / VS Code / Ollama) | ollama run で日本語応答確認、初コミット | RTX3070でローカルLLM入門 |
| 1 | LLM疎通スクリプト | structured outputでJSONが返る | LLMにJSONを返させる |
| 2 | RSS収集 + SQLite既読管理 | 新着のみコンソール出力 | 差分検知設計 |
| 3 | パイプライン結合 + sources.yaml導入 | 3〜5ソースでitemsに保存 | 宣言的なソース管理 |
| 4 | Slack通知 | importance≥3 が整形されて届く | Slack Webhook実践 |
| 5 | タスクスケジューラで朝夕自動実行 | 手を触れず通知が届く | 常駐化 |

### マイルストーン2(確定 2026-07-19。実装計画は PLAN-M2.md)

- Step 6: 重要度評価のルーブリック化(評価分布の3集中を直す)
- Step 7: グッズ・ライブ情報監視(HTML差分)
- Step 8: Notion蓄積 + 過去分バックフィル
- Step 9: 毎朝レポート

### マイルストーン3以降(順不同・未確定)

- モデル比較検証(日本語要約品質)
- Docker化 → ノートPC①のUbuntuサーバー化 → 処理移設
- n8n導入(オーケストレーションのみ)
- Wake-on-LAN方式への移行(省電力運用。7/18のPC電源オフによる定時スキップの根本解もここ)
- ノートPC②を検証環境化(Kubernetes等)

---

## 8. 発信方針

- Zenn中心に技術記事を資産化。「新人SIerが試行錯誤しながら作る」切り口
- 各Stepが記事1本に対応するようロードマップを分割済み
- 最初からアフィリエイト目的にせず、価値ある記事を積み上げる。その後 ブログ / note へ展開検討

## 9. 開発におけるClaudeの使い分け(運用メモ)

- **claude.aiチャット**: 設計相談・レビュー・記事の壁打ち。話題単位で新規チャットを切る
- **プロジェクト機能**: 本DESIGN.mdをプロジェクトナレッジに登録し、全チャットで文脈共有
- **Claude Code**(導入予定): 実装・修正・デバッグ。リポジトリを直接読み書き
- 設計判断が変わったら本ドキュメントを更新し、リポジトリとプロジェクトナレッジの両方を差し替える
