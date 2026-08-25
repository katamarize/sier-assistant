---
title: "PythonからSlack Incoming Webhookで通知する(再送できるキュー設計) #4"
emoji: "🔔"
type: "tech"
topics: ["python", "slack", "webhook", "sqlite", "llm"]
published: true
---

:::message
**ローカルLLMで作る自分専用ニュースbot** シリーズの4本目です。この記事だけでも読めます。  
前: [監視ソースをYAMLで管理し、クラッシュしても再開できるキューを作る](https://zenn.dev/katamarize/articles/step3-pipeline-sources-yaml)  
次: [運用初日、Slackに208件通知が飛んできた話](https://zenn.dev/katamarize/articles/step4-notification-two-lane)
:::

## この記事について

前回までで、RSS収集→差分検知→LLM分析のパイプラインが完成し、分析結果はSQLiteに溜まるようになりました。今回はその出口、Slack通知を作ります。

先に結論を書くと、今回やったことの本質は「Slackに送る」ことではありません。**Webhookの失敗をLLMの失敗と同じ「statusで管理される再送待ち」として扱う**ことで、Step 3で作ったキュー設計を通知まで貫通させました。

## 作ったもの

```
src/
├── notifiers/
│   └── slack.py          # メッセージ整形 + Webhook POST
├── core/
│   └── storage.py        # 通知対象の取得・status一括更新を追加
└── pipelines/
    └── daily_news.py     # 末尾に通知フェーズ(run_notification)を追加
```

Slack側の準備はIncoming Webhookを1本作るだけ。ワークスペースにアプリを作り、通知先チャンネルを選ぶとWebhook URLが発行されるので、それを `.env` の `SLACK_WEBHOOK_URL` に入れます。手順は[Slack公式ドキュメント](https://api.slack.com/messaging/webhooks)のとおりで、ここで詰まる要素はありませんでした。

## 通知フェーズの仕事は「仕分け」と「送信」

通知フェーズがやることは2段階です。まず、LLMが「通知すべき」と判定した記事(`status=analyzed`)を、ソースごとの重要度閾値でもう一度ふるいにかけます。sources.yamlに書いた `min_importance_to_notify` がここで初めて消費されます。

```python:src/pipelines/daily_news.py(抜粋)
def run_notification(sources: list[config.Source]) -> None:
    thresholds = {s.id: s.min_importance_to_notify for s in sources}
    candidates = storage.fetch_notifiable_items()

    to_notify = [i for i in candidates if i.importance >= thresholds.get(i.source_id, 3)]
    below = [i for i in candidates if i.importance < thresholds.get(i.source_id, 3)]

    storage.update_items_status([i.id for i in below], "skipped")
    if not to_notify:
        return

    try:
        slack.send(slack.format_message(to_notify))
    except slack.SlackNotifyError as e:
        print(f"  [analyzed維持] Slack通知失敗(次回再送): {e}")
        return

    storage.update_items_status([i.id for i in to_notify], "notified")
```

閾値をLLMに判定させず通知側に置いたのは、「AWSの記事は重要度3から通知、趣味系のソースは2から」のようにソース単位で感度を変えたいからです。LLMは記事そのものの重要度だけを見て、どこまで通知するかはYAMLの設定が決める。この分担にしておくと、通知がうるさいと感じたらYAMLの数字を1つ変えるだけで済みます。

これでStep 2から引きずってきたstatus状態機械の全遷移が埋まりました。

```
pending ──→ analyzed ──→ notified   (通知済み)
   │            └──→ skipped        (閾値未満)
   └──→ skipped                     (LLMが通知不要と判定)
```

## 核心: 送信に失敗したらDBを更新しない

except節で**何もせずreturnしている**ところがキーポイントです。

Step 3では「LLMが死んだら記事はpendingのまま残し、次回実行で自動リトライ」という設計にしました。通知も同じです。Webhookへの送信が失敗したら、対象の記事はanalyzedのまま残る。次回のパイプライン実行時、通知フェーズはまたanalyzedを拾うので、自動的に再送されます。リトライ処理もリカバリ用のスクリプトも書いていません。「DBを更新しない」だけで再送が成立します。

順序にも意味があります。「送信に成功してからnotifiedに更新」なので、更新前にプロセスが落ちると同じ内容がもう一度届く可能性はあります。逆順(先に更新してから送信)にすると、今度は送信失敗時に通知が永遠に消えます。二重通知と通知漏れのどちらを許容するかというトレードオフで、朝のニュース通知なら答えは明らかに前者だよな、ということでこの順序にしました。

## 複数件は1メッセージにまとめる

新着が10件あるとき、Slackに10連続で通知が飛んでくると確実に通知をミュートしたくなります(チャットで散発で来るのたまにイラッとしますよね...)。なので整形時に全件を1メッセージに詰めました。

```
📰 新着ニュース 2件

*Amazon S3 の新機能が発表* (重要度: 4)
S3に〜が追加され、〜が可能になった。
💡 S3はAWSのオブジェクトストレージ。バックアップや静的サイトによく使われる
https://example.com/...
```

タイトル・要約・URLに加えて、LLM出力の `beginner_note`(新人向け補足)を💡付きで添えています。フォーマットはとりあえずプレーンテキストで、Block Kitでのリッチ化は必要を感じてからにします。

## 検証: 本物のSlackに送る前にモックで壊し方を確かめる

BSODの一件(#2.5参照)以来、「正常系より先に異常系を確認する」ことをとくに意識するようになりました。今回はローカルにHTTPサーバーを立ててWebhookの代役をさせ、一時DBに5パターンの記事(閾値以上・閾値未満・pending・should_notify=0)を仕込んで検証しています。

確認したのは3点です。

1. 閾値以上だけが1メッセージに入り、閾値未満はskippedに落ちる
2. pendingとshould_notify=0の記事は触られない
3. サーバーを止めて送信を失敗させると、記事がanalyzedのまま残る

```
--- DB status --- {1: 'notified', 2: 'skipped', 3: 'notified', 4: 'pending', 5: 'analyzed'}
--- 異常系: Webhook失敗時はanalyzed維持 ---
  [analyzed維持] Slack通知失敗(次回再送): Slackへの送信に失敗: ...
ALL OK
```

3の異常系が通った時点で、このステップの目的はほぼ達成です。実際のSlackへの送信は、Webhook URLを設定して同じコマンドを叩くだけになりました。

追記: この後、実運用初日に「1メッセージ208件」という洗礼を受けました。その顛末と通知の2レーン化は[#4.5](https://zenn.dev/katamarize/articles/step4-notification-two-lane)にまとめています。

## 次回予告

Step 5はタスクスケジューラでの常駐化です。コードは書かず、バッチとログだけで「2日間手を触れずに通知が届く」状態を目指します。毎朝7時、自分専用のニュースが勝手に届くところまであと一歩です。
