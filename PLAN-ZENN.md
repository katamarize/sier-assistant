# Zenn記事 公開計画(2026-07-19決定)

M1で溜めた下書き7本を公開する計画。**公開作業のたびにこのファイルのチェックボックスを更新する。**

## 方針

- **公開順は時系列順**(執筆順)。記事同士が相対リンクで繋がるシリーズ構成であり、BSOD番外編や#4.5の「事故記事」も前の記事を前提に書かれているため、順番を入れ替えると文中の参照が破綻する
- **ペースは週2本**(目安: 月・木)。7本を約3週間半で出し切る。一気に全部出すとフォロワーのタイムラインを埋めるだけで読まれないため、間隔を空ける
- 公開直前に natural-japanese スキルで最終lintをかける(low_burstinessは技術記事では残す判断済み)

## 公開順と目安日

| # | ファイル | タイトル(略) | 目安日 | 状態 |
|---|---|---|---|---|
| 1 | step1-ollama-structured-output.md | OllamaにJSONを厳密に返させる | 7/20(月) | ⬜ 未公開 |
| 2 | step2-rss-diff-detection.md | RSS収集とSQLite差分検知 | 7/23(木) | ⬜ 未公開 |
| 3 | step3-incident-gpu-bsod.md | 推論中にPCが突然落ちた話(番外編) | 7/27(月) | ⬜ 未公開 |
| 4 | step3-pipeline-sources-yaml.md | sources.yamlとクラッシュ耐性の実証 | 7/30(木) | ⬜ 未公開 |
| 5 | step4-slack-webhook.md | Slack通知も再送できるキューとして設計 | 8/3(月) | ⬜ 未公開 |
| 6 | step4-notification-two-lane.md | 運用初日、Slackに208件届いた(#4.5) | 8/6(木) | ⬜ 未公開 |
| 7 | step5-task-scheduler.md | 常駐させない常駐化 | 8/10(月) | ⬜ 未公開 |

日付は目安。ずれても順番だけ守る。

## 公開手段: 案A(GitHub連携)に決定(2026-07-19)

このリポジトリ(katamarize/sier-assistant)をZennにGitHub連携する。`articles/` がリポジトリ直下にあり、全ファイル名がZennのslug規則(小文字英数ハイフン12〜50文字)を満たしているためそのまま使える。`published: true` にしてmainへpushすれば公開される。

- 対応済み: `image.png` → `images/slack-notification.png` へ移動し記事の参照を修正。本計画ファイルもZennがパースしないよう `articles/` の外(ルートのPLAN-ZENN.md)へ移動
- **残作業(ユーザー操作)**: zenn.devのダッシュボード「GitHubからのデプロイ」でこのリポジトリを連携する(初回のみ)。ローカルプレビューは `npx zenn preview`

## 1本ごとの公開前チェックリスト

1. **相対リンクの置換**: 文中の `./stepX-....md` 形式のリンクを、公開済み記事のZenn URL(`https://zenn.dev/<user>/articles/<slug>`)に置き換える。前の記事が公開済みになって初めてURLが確定するので、時系列順ならこの作業が自然に回る
2. **画像**: `image.png`(#4のみ)のアップロード/パス修正
3. **natural-japanese スキルで最終lint**(執筆前にロード、lint→判断→収束)
4. **frontmatter確認**: `published: true` に変更、topics・emojiの見直し
5. 公開後、このファイルの状態列を ✅ に更新し、次の記事のリンク置換に使うURLを控える

## 備考

- #1・#2に「Ollama」が登場するのは歴史的経緯としてそのまま残す(番外編でllama.cppへの移行理由が語られる構成が、シリーズとしての伏線になっている)。CLAUDE.mdの前提とも整合
- M2のStep完了記事(Step 6〜9)は、この7本の公開が進んでから同じペースに合流させる
