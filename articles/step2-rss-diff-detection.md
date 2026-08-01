---
title: "RSS収集とSQLiteによる差分検知の設計 — ローカルLLMを利用した自分専用ニュースbot開発記 #2"
emoji: "📡"
type: "tech"
topics: ["python", "sqlite", "feedparser", "rss"]
published: true
---

## この記事について

「自分専用ニュースbot」開発記の第2回です。[前回](https://zenn.dev/katamarize/articles/step1-ollama-structured-output)はローカルLLM(Ollama)にJSONを厳密に返させるところまで作りました。今回はLLMとは完全に独立したパート、**RSSフィードの収集と、SQLiteによる「既読管理」(同じ記事を2回通知しない仕組み)** を作ります。

ゴールは「同じRSSフィードを2回実行したとき、2回目は新着0件になる」こと。地味ですが、これができないと毎回同じニュースで通知が飛んでくる、実用に耐えないbotになってしまいます。

(雑談)
記事は毎週末に上げようと思っていたのに、先週は「スプラトゥーン レイダース」に週末の時間を費やしてしまいました。沼すぎる。楽しい。

## 作ったもの

```
src/
├── collectors/
│   └── rss.py          # fetch_rss(url, source_id) -> list[Item]
└── core/
    ├── models.py         # Item dataclass を追加
    ├── storage.py         # SQLiteの初期化・読み書き
    └── diff.py            # 新着判定
scripts/
└── check_rss.py           # 動作確認スクリプト
```

### 1. collector の戻り値の型を先に固定する

RSS収集(今回)の後には、いずれHTML差分監視(ライブ・グッズ情報更新の一元管理をしたい)を追加する予定があります。将来collectorが増えてもパイプライン側を書き換えずに済むよう、**collectorの戻り値の型を先に決めておきました**。

```python:src/core/models.py
@dataclass
class Item:
    source_id: str
    item_key: str       # RSS: entry id / HTML: 本文ハッシュ(将来)
    title: str
    url: str
    content: str        # 正規化済み本文
    published_at: str | None
```

`item_key` は「同じ記事かどうか」を判定する主キーです。RSSならフィードのentry idをそのまま使い、HTML差分監視(将来)では本文のハッシュ値を使う想定にしています。どちらの collector も `Item` さえ返せば、後続の差分検知・保存ロジックは一切変更不要になります。

### 2. RSS collector: フィード形式のクセを吸収する

```python:src/collectors/rss.py
def fetch_rss(url: str, source_id: str) -> list[Item]:
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries:
        item_key = entry.get("id") or entry.get("link")
        items.append(
            Item(
                source_id=source_id,
                item_key=item_key,
                title=_normalize(entry.get("title", "")),
                url=entry.get("link", ""),
                content=_normalize(entry.get("summary", "") or entry.get("description", "")),
                published_at=entry.get("published") or entry.get("updated"),
            )
        )
    return items
```

`feedparser` はRSS/Atomの差異をよく吸収してくれますが、entry に `id` が無いフィードも普通に存在します(なんで無いんだ)。なので `id` がなければ `link` を `item_key` に使うフォールバックを入れました。また、`summary` にはHTMLタグが含まれることが多いので、正規表現でタグ除去・空白正規化する `_normalize()` を通しています。

### 3. SQLiteに2つのテーブルを持つ理由

`DESIGN.md` の段階で、役割の異なる2つのテーブルを用意すると決めていました。

```sql
-- 既読管理専用(差分検知だけが見る)
CREATE TABLE seen_items (
    source_id    TEXT,
    item_key     TEXT,
    content_hash TEXT,
    first_seen   TEXT,
    PRIMARY KEY (source_id, item_key)
);

-- 収集した記事の内容とLLM処理状態(パイプラインのキューを兼ねる)
CREATE TABLE items (
    id           INTEGER PRIMARY KEY,
    source_id    TEXT,
    title        TEXT,
    url          TEXT,
    content      TEXT,
    status       TEXT DEFAULT 'pending',
    importance   INTEGER,
    summary      TEXT,
    tags         TEXT,
    created_at   TEXT
);
```

`seen_items` は「もう見た記事か」を `(source_id, item_key)` の複合主キーだけで高速判定するための軽量テーブル。`items` は本文やLLMの分析結果まで持つ「本体」で、`status` カラムが `pending → analyzed → notified`(または `skipped`)と遷移していくキューになります(このキュー設計は次回Step 3で活きてきます)。

`content_hash` は今回のRSS収集単体では実質使っていません(新着判定はentry idベースの `item_key` のみ)。将来のHTML差分監視で「entry idという概念がなく、本文の変化だけを検知したい」ケースに備えて、先に列だけ用意している形です。

### 4. storage.py と diff.py の依存方向

```python:src/core/diff.py
from src.core import storage
from src.core.models import Item


def filter_new_items(items: list[Item]) -> list[Item]:
    return [item for item in items if not storage.is_seen(item.source_id, item.item_key)]
```

`diff.py` が `storage.py` の `is_seen()` を呼ぶ一方向の依存にしました。`DESIGN.md` の契約で「`seen_items` テーブルを直接触ってよいのはStep 2(収集まわり)だけで、Step 3以降(パイプライン)は `diff.py` の関数を経由して間接的に使う」と決めていたためです。`storage.py` 側が `diff.py` に依存する形にすると循環importになるので、`content_hash` の計算は `storage.py` 側の `mark_seen()` 内で完結させています。

```python:src/core/storage.py(抜粋)
def mark_seen(item: Item) -> None:
    content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_items "
            "(source_id, item_key, content_hash, first_seen) VALUES (?, ?, ?, ?)",
            (item.source_id, item.item_key, content_hash, datetime.now(timezone.utc).isoformat()),
        )
```

`INSERT OR IGNORE` にしているのは、`(source_id, item_key)` の主キー制約に違反する再実行があってもエラーにせず黙って無視させたいからです。

## 検証: AWS What's New フィードで実行

`scripts/check_rss.py` で AWS What's New のRSS(`https://aws.amazon.com/about-aws/whats-new/recent/feed/`)を取得し、1回目・2回目で挙動を比較しました。

**1回目**

```
取得件数: 100
新着件数: 100
  + Amazon EC2 network/EBS instances now available in additional regions
  + Amazon EMR on EKS now supports Apache Spark troubleshooting agent
  ...(以下98件)
```

**2回目(同じフィードをそのまま再実行)**

```
取得件数: 100
新着件数: 0
```

フィード自体は毎回100件返ってきますが、2回目は全て既読と判定されて新着0件。狙い通りの挙動になりました。

DB の中身も直接確認しました(この環境には `sqlite3` CLIが入っていなかったので、Pythonの `sqlite3` モジュールから)。

```
tables: ['seen_items', 'items']
items count: 100
seen_items count: 100

--- items sample ---
(1, 'aws-whats-new', 'pending', 'Amazon EC2 network/EBS instances now available in additional regions', '2026-07-13T16:16:14...')

--- seen_items sample ---
('aws-whats-new', 'c6479f0087bed55379be122cc166b163cf7f192a', '587544fdf6fd576234ee72e7a512ce4b8a3dfaec8d4102be7d1c4740e9a3c780', '2026-07-13T16:16:14...')
```

`items` は全件 `status='pending'` のまま(LLM分析はまだStep 1の `analyze()` と繋いでいないため)、`seen_items` にはentry idとSHA-256のハッシュがちゃんと記録されています。

## 次回予告

Step 3では、今回のRSS収集(Step 2)とStep 1のLLM疎通を1本のパイプラインにつなぎ、`sources.yaml` で監視対象を宣言的に管理できるようにします。「LLMが止まっていても収集は止めない」「1件のLLM失敗で全体を止めない」というキュー設計の本領が、ここで発揮される予定です。
