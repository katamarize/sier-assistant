---
title: "監視ソースをYAMLで管理し、クラッシュしても再開できるキューを作る #3"
emoji: "🔗"
type: "tech"
topics: ["python", "sqlite", "yaml", "llamacpp", "llm"]
published: true
---

:::message
**ローカルLLMで作る自分専用ニュースbot** シリーズの3本目です。この記事だけでも読めます。  
前: [ローカルLLM推論中のブルースクリーンをWinDbgで追う](https://zenn.dev/katamarize/articles/step3-incident-gpu-bsod)  
次: [PythonからSlack Incoming Webhookで通知する](https://zenn.dev/katamarize/articles/step4-slack-webhook)
:::

## この記事について

[#1](https://zenn.dev/katamarize/articles/step1-ollama-structured-output)でローカルLLMのstructured output、[#2](https://zenn.dev/katamarize/articles/step2-rss-diff-detection)でRSS収集とSQLite差分検知を作りました。今回はこの2つを1本のパイプラインに結合し、監視対象のニュースソースをYAMLで宣言的に管理できるようにします。

そして今回は予定外のポイントがあります。検証中に**PCがBSODでクラッシュし**([#2.5](https://zenn.dev/katamarize/articles/step3-incident-gpu-bsod)参照)、結果的に「LLMが死んでもパイプラインは壊れない」というキュー設計の核心を、実際の障害で実証することになりました。

## 作ったもの

```
config/
├── sources.yaml            # 監視対象の定義(個人設定、gitignore)
└── sources.example.yaml    # 公開用テンプレート
src/
├── core/
│   ├── config.py            # YAMLローダ(Source dataclass)
│   └── storage.py            # pending取得・分析結果更新を追加
└── pipelines/
    └── daily_news.py         # パイプライン本体
```

## sources.yaml: ソース追加をコード変更ゼロにする

監視したいソースはこういうYAMLで宣言します。

```yaml:config/sources.yaml
defaults:
  interval_hours: 6
  min_importance_to_notify: 3

sources:
  - id: aws-whats-new
    name: AWS What's New
    type: rss
    url: https://aws.amazon.com/about-aws/whats-new/recent/feed/
    category: it_news
    tags_hint: [AWS, クラウド]

  - id: publickey
    name: Publickey
    type: rss
    url: https://www.publickey1.jp/atom.xml
    category: it_news
    tags_hint: [クラウド, インフラ, 開発ツール]
  # ...以下、はてブIT・Qiita人気・ITmedia NEWSの計5ソース
```

この形式にした狙いは3つあります。

1. **`defaults` とソース個別設定のマージ**。通知閾値などはまず全体既定を置き、ソースごとに上書きできる
2. **collectorは `type` だけ見てディスパッチ**。現在は `rss` のみだが、将来 `html`(RSSのないページの更新監視など)を追加するときも、collector関数を1つ書いてディスパッチ辞書に1行足すだけで済む
3. **個人設定はgitignore**。`sources.yaml` は公開リポジトリに含めず、`sources.example.yaml` をテンプレートとして公開する

ローダは `dataclass` に詰めるだけの素朴な作りです。

```python:src/core/config.py(抜粋)
def load_sources(path: str | Path = DEFAULT_SOURCES_PATH) -> list[Source]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    defaults = data.get("defaults", {})
    sources = []
    for raw in data.get("sources", []):
        merged = {**defaults, **raw}
        sources.append(Source(...))
    return sources
```

## パイプライン: 「収集」と「分析」を意図的に分離する

`daily_news.py` の処理フローは2フェーズに分かれています。

```
フェーズ1(収集): sources.yaml読込 → type別collector → 差分検知 → 新着をitems(pending)保存
フェーズ2(分析): pending全件を取得 → 1件ずつLLMへ → analyzed / skipped に更新
```

**フェーズ1はLLMが死んでいても必ず完走します**。そしてフェーズ2が見るのは「DBにpendingがあるか」だけ。収集と分析はDBのstatus列だけで繋がっていて、直接の関数呼び出し関係がありません。

```python:src/pipelines/daily_news.py(抜粋)
def run_analysis() -> None:
    pending_items = storage.fetch_pending_items()
    for pending in pending_items:
        try:
            result = analyze(pending.title, pending.content)
        except LLMUnavailableError:
            # pendingのまま残す = 次回実行時に自動リトライされる
            continue

        status = "analyzed" if result.should_notify else "skipped"
        storage.update_item_analysis(pending.id, result, status)
```

- LLM呼び出しが失敗した記事は**DBを一切更新しない**。pendingのまま残るので、次回実行時に自動で再試行される
- try/exceptは**1件単位**。1記事の失敗が残り全件を道連れにしない

## 想定外の実証実験: 本物のクラッシュで設計を検証する

初回のフル実行(100件超のpendingをLLMに連続投入)の最中に、PCがBSODで落ちました。GPUドライバー+メモリ破損系のクラッシュで、詳細は[#2.5](https://zenn.dev/katamarize/articles/step3-incident-gpu-bsod)にまとめています。

普通なら「実行中のデータはどうなった?」と青ざめる場面です。恐る恐る再起動後にDBを見ると:

```
('analyzed', 3)
('pending', 219)
('skipped', 3)
```

クラッシュ直前に処理し終えた6件はコミット済み、残り219件は**pendingのまま無傷**でした。SQLiteは1件ごとにコミットしているので、プロセスがどのタイミングで即死してもDBは壊れません。「再実行すれば続きから回収される」設計がそのまま機能しました。

その後、LLM実行基盤をOllamaからllama.cpp(llama-server)のOpenAI互換APIに移行し(VRAM圧迫を下げるため。これも#2.5参照)、溜まった全pendingを処理する再実行を行ったところ:

```
AWS What's New (aws-whats-new): 新着 11 件
Publickey (publickey): 新着 1 件
はてなブックマーク テクノロジー (hatena-it): 新着 30 件
Qiita 人気の投稿 (qiita-popular): 新着 20 件
ITmedia NEWS (itmedia-news): 新着 19 件
LLM分析対象(pending): 300 件
```

**300件を約15秒/件、失敗0件で完走**(クラッシュで残った219件+当日の新着81件)。処理後のstatus内訳は `analyzed 161 / skipped 145 / pending 0`、importance分布は4が35件・3が245件・2が26件。GPU温度は全行程で80℃未満(30秒間隔で監視)で、移行後の構成では普通に安定して動いています。

「LLM停止→pending維持→再実行で回収」はStep 3の完了条件として最初から検証項目に入れていましたが、まさか停止どころかOSごと落ちる本番相当のテストになるとは思いませんでした。普段業務で保守運用のアラートが飛んで初めて気づくようなエラーもありますが、実運用始める前にエラーになるとは...💦  
あらゆるテストケースを事前に想定して対策する重要さを身をもって体験した回でした。

## LLMサーバー移行がパイプラインに与えた影響: import 1行

今回OllamaからLLM実行基盤を丸ごと入れ替えたわけですが、パイプライン側の変更は `from src.llm.llm_client import analyze` のimport 1行だけ。`analyze(title, content) -> AnalysisResult` というインターフェース(モジュール間の契約)を最初に固定していたおかげでした。個人開発でも「契約を先に決めて、実装は差し替え可能にしておく」は普通に効きます。

## 次回予告

Step 4では、analyzedになった記事のうち重要度が閾値以上のものをSlackに通知します。`sources.yaml` の `min_importance_to_notify` がここで初めて消費され、「通知されなかったanalyzed」は `skipped` に落ちる、status状態機械の最後のピースが埋まります。
