# PLAN-M2.md — マイルストーン2 実装計画書

最終更新: 2026-08-25
前提ドキュメント: DESIGN.md(設計思想・技術選定)、PLAN.md(M1実装計画。契約C1〜C6の定義はそちらが正)
本書の目的: M1と同じく、**どのチャット・どのモデルでも本書だけでStepを継続できる**状態を保つ。

M2のテーマ: **「届く」から「使える」へ**。評価の質を上げ(Step 6)、監視対象を広げ(Step 7)、流れていく情報を資産化する(Step 8〜9)。
スコープ外(M3送り): Docker化 / Ubuntuサーバー移設 / n8n / Wake-on-LAN / k8s検証環境。機能が固まってから基盤を移す。

---

## 0. 進捗トラッカー(作業のたびに更新)

| Step | 内容 | 状態 | 完了日 | Zenn記事下書き |
|---|---|---|---|---|
| 6 | 重要度評価のルーブリック化 | ✅ 完了 | 2026-07-21 | articles/step6-rubric-importance.md |
| 7 | HTML差分監視(推し情報) | ⬜ 未着手 | | |
| 8 | Notion蓄積 + 過去分バックフィル | ⬜ 未着手 | | |
| 9 | 毎朝レポート | ⬜ 未着手 | | |

---

## 1. Step間の依存関係

```
M1完了
  ├─→ Step 6(ルーブリック)──┐
  ├─→ Step 7(HTML差分)──────┼─→ Step 9(毎朝レポート)
  └─→ Step 8(Notion蓄積)────┘
```

- **Step 6・7・8は互いに独立**。並行着手・順序入替え可。推奨順は6→7→8(効果の大きい順・小さい順)
- Step 9はStep 8のNotion蓄積が動いていることが前提。またStep 6の評価改善後の方がレポートの質が上がる
- Step 7の成果(html collector)はStep 8以降に影響しない(C6契約で吸収)

---

## 2. 契約の変更・追加(M1のC1〜C6はPLAN.md参照)

### 変更なし(重要)
- **C1(LLM出力スキーマ)**: Step 6はプロンプト本文のみ変更し、スキーマは変えない
- **C6(Item型)**: html collectorもこの型を返す(item_key=正規化本文のSHA-256)。パイプライン改修不要

### C4(sources.yaml)への追加
- `type: html` を有効化。`selector` フィールド(CSSセレクタ)を使用開始。スキーマ自体はM1定義のまま
- `type: aip` を追加(2026-08-25)。`artist_folder` フィールド(Sony Music AIPのアーティスト識別子)を使用。`selector` は使わない。詳細は§3 Step 7-b

### C7: Notion連携の環境変数(Step 8で追加)
| キー | 用途 |
|---|---|
| `NOTION_TOKEN` | Notion Integration Token |
| `NOTION_DB_ID` | 蓄積先データベースID |

### C2への影響(Step 8、着手時に決定)
Notion転記済みの追跡方法が未決(§5参照)。**statusの値は増やさない方針を優先**し、列追加(`notion_page_id`等)で解決できないか先に検討する。

---

## 3. Step別 実装仕様

### Step 6: 重要度評価のルーブリック化
- 背景: 現状の評価分布は3に79%集中(2:40 / 3:313 / 4:45 / 5:0、2026-07-17時点の398件)。基準を与えていないため中央に寄る
- 前提: なし(単体で完結)
- 作るもの: `src/llm/prompts/analyze_item.md` の改訂のみ。各重要度の定義+具体例を明記する
  - たたき台: 5=セキュリティ緊急・業務直撃 / 4=主要サービスのGA・大型障害・業界の大きな動き / 3=知って損はない技術動向 / 2=ニッチ・宣伝色強め / 1=対象外
- 完了条件: 検証用サンプル(過去記事20〜30件をDBから抽出)を新旧プロンプトで再評価し、分布の偏りが緩和されること(3の比率が明確に下がり、4/5と2以下に分離する)
- 検証方法: 一時DBまたは読み取り専用スクリプトで比較。**本番DBの既存評価は上書きしない**
- 注意: モデル変更なし・スキーマ変更なし。閾値(sources.yaml)の再調整が必要になる可能性あり
- 記事ネタ: LLM評価にルーブリックを与えると分布はどう変わるか(before/after の実データ付き)

### Step 7: 「推し情報」の更新監視(HTML差分 + AIP JSON)
- 前提: なし(単体で完結)。`uv add beautifulsoup4` を想定
- 取得は1日2回(既存スケジュール)で十分。User-Agent明示、タイムアウト、失敗時はソース単位でスキップ(既存のtry/exceptに乗る)
- **2026-08-25の再調査で2本立てに変更**。JS描画のため見送っていた2サイトが、裏のJSON APIを直接叩けば取得できると判明したため(§5)

#### 7-a: HTML差分監視(BM-ECHOES / 青木陽菜)
- 作るもの: `src/collectors/html.py`、sources.yamlへの `type: html` ソース追加(登録済み)
- 公開するもの: `fetch_html(url: str, source_id: str, selector: str) -> list[Item]`(C6準拠)
  - item_key = selectorで抽出・正規化した本文のSHA-256(C6コメントの通り)
  - title = ページの`<title>`等、content = 抽出本文。「前回から変わった」ことを1 Itemとして返す
- 実装要点:
  - 変更検知の単位は「抽出範囲のハッシュ」から始める。差分箇所の特定はやらない(LLMの要約に任せる)
  - 抽出本文の整形にMD化ライブラリ(html2text / trafilatura等)を挟むとLLMへ渡すトークンが減る。必須ではないので後回しでよい
- 完了条件: 実ページで(a)初回に1件検知、(b)変更なし時に0件、(c)ページ更新後に1件検知、が確認できる

#### 7-b: AIP JSON収集(ClariS / 楠木ともり)
- 背景: 両サイトともSony Musicの共通基盤(AIP)製で、生HTMLにはVueのテンプレート(`v-for` と `{{ article.title }}`)しか無く、記事データが1件も含まれない。requests+BeautifulSoupで取れないのはセレクタの問題ではなく**HTMLにデータが無い**ため
  - **MD化ツール(markitdown / trafilatura / html2text等)では解決しない**。これらは「取得済みHTML → 読みやすいテキスト」の変換器であり、取得のレイヤーには効かない。解決するのはヘッドレスブラウザ(Playwright)かレンダリング付きリーダーだが、下記のJSON APIがあるため不要
- エンドポイント(2026-08-25 実アクセスで確認済み):
  ```
  https://www.sonymusic.co.jp/json/v2/artist/{artist_folder}/information/start/{start}/count/{count}
  ```
  - artist_folder: ClariS = `claris` / 楠木ともり = `tomorikusunoki`(各サイトの `aip.setting.js` / `tomori.setting.js` の `_artistFolder` から特定)
  - JSONPで返る(`callback({...})`)。前後を剥がしてから `json.loads` する
  - 中身: `items[]` に `id / title / category / date / article(本文HTML)`、加えて `total_count`。categoryは INFO / LIVE / MEDIA / RELEASE
  - 実質RSS相当。本文まで入っているぶんRSSより情報量が多い。`/discography/` など他の種別も同じ形式
- 作るもの: `src/collectors/aip.py`、sources.yamlに `type: aip` のソース2件
- 公開するもの: `fetch_aip(url: str, source_id: str, artist_folder: str) -> list[Item]`(C6準拠)
  - **item_key = 記事の `id`**。ページ全体ハッシュと違い「この記事が増えた」を記事単位で検知できる(7-aより差分が正確)
- 完了条件: 初回に直近n件を取得、2回目は0件、新着があれば増えた分だけ検知できる
- 注意:
  - 非公式APIなので予告なく変わり得る。壊れてもソース単位のスキップでパイプライン全体は落ちない
  - `www.sonymusic.co.jp/robots.txt` に `User-agent: *` の禁止規則は無いが、AIクローラー(GPTBot / ClaudeBot / CCBot / PerplexityBot等)は名指しで全面禁止。冒頭コメントに「機械学習に使うなら問い合わせを」とある。個人利用・1日2回・数件の範囲を守り、User-Agentは明示する。本文をLLMに渡さずタイトル+日付+categoryだけ通知する構成も選べる

#### 共通
- パイプライン変更: `_COLLECTORS` に2行追加(+ `selector` / `artist_folder` 引数の受け渡し)
- **記事ネタ(有力・7-b)**: 「JSで描画されていて諦めたページの裏に、JSON APIがあった」。調査の筋道 — 生HTMLにテンプレートしか無いことの確認 → 読み込んでいるJSを辿る → Vueが叩くエンドポイントを特定 → 実際に叩いて検証 — がそのまま1本になる。「MD化ツールを噛ませれば取れるのでは?」という直感が外れる理由(取得と変換はレイヤーが違う)を軸にすると、スクレイピング入門として実用的。robots.txtとAIクローラー禁止の扱いも1節書ける
- 記事ネタ(7-a): RSSがないページの更新をLLM要約付きで通知する

### Step 8: Notion蓄積 + 過去分バックフィル
- 前提: Notion Integration作成済み(C7)。Notion側にデータベース作成済み
- 作るもの: `src/notifiers/notion.py`、バックフィルスクリプト(`scripts/backfill_notion.py`等)、daily_news.py末尾に蓄積フェーズ追加
- 処理: `stocked`(と必要ならnotified)の記事をNotion DBにページ作成(タイトル/URL/要約/重要度/タグ/日付)。転記失敗時は既存の再送パターンに従う(転記済み追跡は§5で決めてから)
- バックフィル: DBに残る全評価(M1期間の全件)を一括転記。**評価がDBに全部残っている設計の回収ポイント**
- 完了条件: 定時実行でストック記事がNotionに増えていく。過去分がNotionで検索できる
- 記事ネタ: SQLiteに全部残しておいたから後付けできた話(スキーマ設計の伏線回収)

### Step 9: 毎朝レポート
- 前提: Step 8完了(+Step 6完了が望ましい)
- 内容の候補(着手時に決定): 朝の通知に「昨日のまとめ」(件数・カテゴリ傾向・注目3件)を1ブロック追加 / またはNotionに日次ページを生成
- 作るもの・完了条件: 上記決定後に本書へ追記する
- 記事ネタ: 情報を「流す」から「振り返る」へ

---

## 4. 影響マトリクス(M2で増える分)

| 変更 | 影響範囲 | 影響しないもの |
|---|---|---|
| プロンプト改訂(Step 6) | 評価分布 → sources.yamlの閾値調整の可能性 | 全コード・スキーマ・DB |
| html collector追加(Step 7-a) | collectors/新ファイル、_COLLECTORSに1行、sources.yaml追記 | pipeline本体、storage、notifier、LLM |
| aip collector追加(Step 7-b) | collectors/新ファイル、_COLLECTORSに1行、sources.yaml追記(`type: aip` + `artist_folder`) | pipeline本体、storage、notifier、LLM |
| Notion notifier追加(Step 8) | notifiers/新ファイル、daily_news末尾、.env(C7) | 収集・LLM側全部 |
| Notion転記の追跡列追加(Step 8、するなら) | items DDL、storage.py。DB作り直しは許容済み | collectors、LLM |

---

## 5. 未決事項(着手時に決める)

| 項目 | 決めるタイミング | 備考 |
|---|---|---|
| ルーブリックの具体文言 | Step 6 | §3のたたき台から。試行錯誤を記事に残す |
| 記事単位のカテゴリ判定(技術/業界)をC1に足すか | Step 6 | 入れるならプロンプト改訂と同時が効率的。C1変更なので影響マトリクス確認 |
| HTML監視対象の具体ページ | ~~Step 7~~ **決定済(2026-07-19)、2026-08-25に拡張** | **青木陽菜さんのBM-ECHOESページ**(`https://bm-echoes.com/creators/aoki-hina/`、selector `.creators-details__works--list`)。候補3件のうち唯一のサーバーサイドレンダリング(WordPress)。robots.txtは`/wp-admin/`のみ禁止で問題なし。sources.yaml反映済み |
| ~~ClariS公式・楠木ともり公式の見送り~~ | **撤回(2026-08-25)** | JS(AIP/Vue)描画のため見送っていたが、**AIPのJSON APIを直接叩けば取得できる**ことを実アクセスで確認。3サイトとも監視対象に含める(取得方法は§3 Step 7-b)。ClariS公式の現URLは `https://www.clarismusic.jp/`(旧 `claris-official.com` はDNS解決不可) |
| Notion転記済みの追跡方法 | Step 8 | status追加 vs `notion_page_id`列追加。列追加を優先検討(C2の状態機械を太らせない) |
| 毎朝レポートの形(Slack内 vs Notionページ) | Step 9 | Step 8の使用感を見てから |

---

## 6. チャット運用ルール

PLAN.md §5と同じ。M2では冒頭テンプレを「DESIGN.mdとPLAN-M2.mdを読んで。Step Nに着手する」と読み替える。Step完了時の記事下書き・トラッカー更新も同様に必須。
