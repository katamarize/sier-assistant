# PLAN.md — マイルストーン1 実装計画書

最終更新: 2026-07-13
前提ドキュメント: DESIGN.md(設計思想・技術選定はそちらが正)
本書の目的: **どのチャット・どのモデルでも、本書とDESIGN.mdだけで実装を継続できる**ようにする。設計判断の再議論を不要にし、各Stepを独立した作業単位として渡せる状態を維持する。

---

## 0. 進捗トラッカー(作業のたびに更新)

| Step | 内容 | 状態 | 完了日 | Zenn記事下書き |
|---|---|---|---|---|
| 0 | 環境構築 | ✅ 完了 | 2026-07-13 | 未作成 |
| 1 | LLM疎通スクリプト | ✅ 完了 | 2026-07-13 | [articles/step1-ollama-structured-output.md](articles/step1-ollama-structured-output.md) |
| 2 | RSS収集 + SQLite既読管理 | ✅ 完了 | 2026-07-14 | [articles/step2-rss-diff-detection.md](articles/step2-rss-diff-detection.md) |
| 3 | パイプライン結合 + sources.yaml | ⬜ 未着手 | | |
| 4 | Slack通知 | ⬜ 未着手 | | |
| 5 | タスクスケジューラ常駐化 | ⬜ 未着手 | | |

---

## 1. Step間の依存関係

```
Step 0(環境構築)
  ├─→ Step 1(LLM疎通)────┐
  └─→ Step 2(RSS+既読)───┼─→ Step 3(結合+YAML)─→ Step 4(Slack)─→ Step 5(常駐化)
                            │
        ※ Step 1 と 2 は互いに独立。並行着手・順序入替え可
```

- **Step 1とStep 2は依存なし**。片方が詰まってももう片方を進められる
- Step 3が最初の「統合点」。Step 1・2の公開インターフェース(下記の契約C1・C6)が確定していることが前提
- Step 4はDBのitemsテーブル(C2)とLLM出力(C1)にのみ依存。収集ロジックには依存しない
- Step 5はコード変更なし(バッチ起動+ログのみ)。Step 4まで手動実行で安定していることが前提

---

## 2. モジュール間の契約(Contract)

Step間で共有する「取り決め」。**ここを変えると複数Stepに波及する**ため、変更時は §4 影響マトリクスを確認し、本書とDESIGN.mdを両方更新する。

### C1: LLM出力スキーマ
DESIGN.md §5 のJSONスキーマそのまま。
- 生産者: `src/llm/ollama_client.py`(Step 1)
- 消費者: `src/pipelines/daily_news.py`(Step 3)、`src/notifiers/slack.py`(Step 4)
- Pythonでは `AnalysisResult` dataclass(`src/core/models.py`)として受ける

### C2: itemsテーブル + status状態機械
DESIGN.md §5 のDDLそのまま。状態遷移: `pending → analyzed → notified`、通知不要は `skipped`。
- 書き込み: Step 3(pending作成、analyzed/skipped更新)、Step 4(notified更新)
- **statusの値を増減する場合はStep 3と4の両方を修正**

### C3: seen_itemsテーブル(差分検知)
DESIGN.md §5 のDDLそのまま。RSSの `item_key` = entry id(なければlink)。
- 使用者: Step 2のみ(Step 3以降は関数経由で間接利用)

### C4: sources.yamlスキーマ
DESIGN.md §5 の形式そのまま。
- 消費者: config loader(Step 3)、collectors(typeフィールドでディスパッチ)、通知閾値判定(Step 4が `category` と `min_importance_to_notify` を参照)
- **フィールド追加はコード変更なしで無害。フィールドの意味変更は Step 3・4 に波及**

### C5: 環境変数(.env)
| キー | 用途 | 使用Step |
|---|---|---|
| `OLLAMA_HOST` | 既定 `http://localhost:11434` | 1〜 |
| `OLLAMA_MODEL` | 既定 `qwen3:8b`。モデル変更はここだけ | 1〜 |
| `SLACK_WEBHOOK_URL` | Incoming Webhook | 4〜 |
| `DB_PATH` | 既定 `data/assistant.db` | 2〜 |

### C6: Itemデータクラス(collector共通戻り値)
```python
@dataclass
class Item:
    source_id: str
    item_key: str       # RSS: entry id / HTML: 本文ハッシュ(将来)
    title: str
    url: str
    content: str        # 正規化済み本文
    published_at: str | None
```
- 生産者: 全collector(Step 2〜)。消費者: diff・storage・pipeline
- **将来のhtml collector(M2)もこの型を返せばパイプライン改修不要**(これが型を固定する理由)

---

## 3. Step別 実装仕様

各Stepは「入力(前提)/ 作るもの / 公開するもの / 完了条件 / 検証方法」を持つ独立作業単位。**新しいチャットでは該当Stepの節だけ読めば着手できる。**

### Step 1: LLM疎通スクリプト
- 前提: Step 0のみ(DB・RSS不要。単体で完結)
- 作るもの: `src/llm/ollama_client.py`、`src/llm/prompts/analyze_item.md`、`src/core/models.py`(AnalysisResult)
- 公開するもの: `analyze(title: str, content: str) -> AnalysisResult`(契約C1)
- 実装要点:
  - `ollama` 公式Pythonパッケージ、`chat()` の `format` にC1のJSONスキーマdictを指定
  - temperature低め(0.2程度)、タイムアウト120s、失敗時は独自例外 `LLMUnavailableError` を送出(リトライ1回)
  - プロンプトはコード外のファイルに分離(プロンプト改善を記事ネタにするため)
- 完了条件: 固定の日本語記事テキストを渡し、C1準拠のJSONがパースできる。Ollama停止時に例外が正しく出る
- 検証: 記事風テキスト2〜3種(重要/軽微)で `should_notify` の判定が変わることを目視確認
- 記事ネタ: LLMにJSONを返させる(structured output)

### Step 2: RSS収集 + SQLite既読管理
- 前提: Step 0のみ(Step 1と独立)
- 作るもの: `src/collectors/rss.py`、`src/core/storage.py`、`src/core/diff.py`、`src/core/models.py`(Item追加)
- 公開するもの:
  - `fetch_rss(url: str, source_id: str) -> list[Item]`(契約C6)
  - `storage.init_db()` / `is_seen(source_id, item_key)` / `mark_seen(item)` / `save_item(item)`(契約C2・C3)
- 実装要点: feedparser使用。entry idがない場合はlinkをitem_keyに。content_hashは正規化本文のSHA-256
- 完了条件: 同一フィードを2回実行し、2回目は新着0件と表示される
- 検証: AWS What's New のRSSで実行 → DBをsqlite3 CLIで目視
- 記事ネタ: 差分検知設計

### Step 3: パイプライン結合 + sources.yaml
- 前提: **Step 1と2の両方完了**。契約C1・C2・C4・C6が確定していること
- 作るもの: `src/pipelines/daily_news.py`、`src/core/config.py`(YAMLローダ)、`config/sources.yaml` と `sources.example.yaml`
- 処理フロー: sources.yaml読込 → source毎にtype別collector呼出 → 差分検知 → 新着をitems(pending)保存 → pending全件をLLMへ → analyzed/skipped更新
- 実装要点: **LLM失敗時はpendingのまま残す(キュー設計の核心)**。1件の失敗で全体を止めない(try/except per item)
- 完了条件: 3〜5ソースで実行し、itemsにanalyzed行が入る。Ollamaを止めて実行→pendingが残り、再実行で回収される
- 記事ネタ: 宣言的なソース管理
- 検証: 上記の「Ollama停止→再実行」を必ず実施(これが設計の売り)

### Step 4: Slack通知
- 前提: Step 3完了。SlackでIncoming Webhook作成済(契約C5)
- 作るもの: `src/notifiers/slack.py`、daily_news.py末尾に通知フェーズ追加
- 処理: `status=analyzed AND should_notify AND importance >= ソースのmin_importance_to_notify` を抽出 → 整形(タイトル/要約/beginner_note/URL)→ POST → `notified` 更新。閾値未満は `skipped`
- 実装要点: Webhook失敗時はanalyzedのまま残す(次回再送)。複数件は1メッセージにまとめる(通知疲れ防止)
- 完了条件: 実際のSlackに整形済み通知が届く
- 記事ネタ: Slack Webhook実践

### Step 5: タスクスケジューラ常駐化
- 前提: Step 4まで手動実行で数日安定していること
- 作るもの: `run.bat`(`uv run python -m src.pipelines.daily_news`)、`logs/` へのファイルログ(logging + RotatingFileHandler)
- 設定: Windowsタスクスケジューラで朝7:00・夕18:00。「スリープ解除して実行」は要確認
- 完了条件: 2日間手を触れずに通知が届く。失敗時にログで原因追跡できる
- 記事ネタ: 常駐化

---

## 4. 影響マトリクス(変更したら何が壊れるか)

| 変更 | 影響範囲 | 影響しないもの |
|---|---|---|
| C1スキーマにフィールド追加 | prompts、ollama_client、slack整形、(DB列に持つなら)items DDL | collectors、diff |
| モデル変更(qwen3:8b→他) | `.env` のみ。※出力品質は要再検証(プロンプト調整の可能性) | 全コード |
| ソース追加(既存type) | sources.yaml追記のみ | 全コード |
| 新type追加(html等) | collectors/に新ファイル+type分岐1行 | pipeline本体、storage、notifier |
| status値の追加・変更 | Step 3と4の両方、DB内既存行のマイグレーション | Step 1、2 |
| 通知先追加(Notion等、M2) | notifiers/に新ファイル。items(C2)を読むだけ | 収集・LLM側全部 |
| 実行環境の移設(M2: Ubuntu) | run.bat→cron、パス処理 | Pythonコード(パスはDB_PATH等で外出し済のこと) |

---

## 5. チャット運用ルール(Fable/モデル非依存で進めるために)

1. **新チャットの冒頭テンプレ**:
   「DESIGN.mdとPLAN.mdを読んで。今からStep Nに着手する。PLAN.md §3のStep Nの仕様に従って進めて」
2. 設計判断が変わったら、その場でDESIGN.md(思想・選定)とPLAN.md(§0進捗・§2契約・§4影響)を更新し、プロジェクトナレッジを差し替える
3. 1チャット=1Step(または1つの問題)。長引いたら本書を更新してからチャットを切る
4. 実装はClaude Code(導入後)、設計相談・レビュー・記事壁打ちはチャット、という分担はDESIGN.md §9のとおり
5. 迷ったら**契約(§2)を守る方を選ぶ**。契約を変えたくなったら§4を見て影響を確認してから
6. **Step完了時は必ず以下の2点を実施する(省略しない)**:
   1. 今回実際に実装したファイルの内容まとめ・解説をチャット上で提示する(何を作ったか・なぜその設計にしたか・検証結果)
   2. `articles/step{N}-{slug}.md` にZenn記事の下書きを作成する。フォーマットはZennのfrontmatter(`title` / `emoji` / `type` / `topics` / `published: false`)に従う。該当Stepの「記事ネタ」(§3・DESIGN.md §7)を軸に、実装の意図・詰まった点・検証結果を含める
   3. §0の進捗トラッカーに完了日と記事下書きへのリンクを追記する

## 6. 未決事項(着手時に決める)

| 項目 | 決めるタイミング | 備考 |
|---|---|---|
| プロンプト本文(analyze_item) | Step 1 | 記事ネタなので試行錯誤の記録を残す |
| 初期ソース3〜5件の選定 | Step 3 | it_news中心。artist系はM2のhtml対応後 |
| Slackメッセージの整形フォーマット | Step 4 | まずプレーンテキスト、Block Kitは任意 |
| 朝夕の実行時刻 | Step 5 | 生活リズムに合わせる |