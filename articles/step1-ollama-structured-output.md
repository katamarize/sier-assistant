---
title: "OllamaのStructured OutputでJSONを確実に返させる(Python + Qwen3) #1"
emoji: "🦙"
type: "tech"
topics: ["ollama", "python", "llm", "qwen3", "structuredoutput"]
published: true
---

:::message
**ローカルLLMで作る自分専用ニュースbot** シリーズの1本目です。この記事だけでも読めます。  
次: [feedparser + SQLite で RSS の既読管理を実装する](https://zenn.dev/katamarize/articles/step2-rss-diff-detection)
:::

## この記事について

### 開発の動機

新人SIerの私が、毎朝自分に必要な技術ニュースだけを自動収集・要約・通知してくれる「自分専用のニュースbot」を作ります。

発端は三つありました。

一つ目は、大学時代に組んだゲーミングPC(i5 12400F・RTX 3070 VRAM 8GB・DDR4 RAM 32GB、2023年夏に自作)。社会人になってからPCゲームを起動する時間が取れなくなり(ゲームはもっぱらSwitchのスプラトゥーン)、RTX 3070がすっかり遊休資産になっていました。どうせならこのGPUで、最近よく耳にするローカルLLMを動かしてみたい。

二つ目は、技術ニュースとの付き合い方です。仕事が落ち着いている時期は自分からニュースサイトを覗きに行けるのに、繁忙期に入るとアンテナが完全に折れる自覚がありました。それなら、見るべきニュースだけを向こうから通知してくれる仕組みを作ればいいのでは?

三つ目は、Claude Code(Fable)を個人開発で使ってみたかったこと。業務では活用しているものの、自分のプロジェクトでゼロから任せたことはありませんでした。

この三つが重なって、このプロジェクトが始まっています。

### 開発のゴール

今回のゴールはシンプルで、**ローカルLLM(Ollama)に記事のテキストを渡し、機械可読なJSONで「重要度」や「通知すべきか」を判定させる**ところまで。収集(RSS)やSlack通知はまだ登場しません。設計全体はリポジトリの `DESIGN.md` / `PLAN.md` にまとめていて、この記事はその「Step 1」に対応します。

なお、LLM実行基盤はこの時点ではOllamaです。のちにllama.cpp(llama-server)へ移行するのですが、その顛末は番外編(#2.5)で書きます。記事は当時の構成のまま残しています。

## なぜLLMの役割を「理解・整理」だけに絞ったか

収集や差分検知(何が新着記事か)まで全部LLMにやらせると、動きは面白いのですが再現性がなく、後からデバッグもしづらくなります。今回のプロジェクトでは

- 収集・差分検知 → 決定論的にPythonで実装(Step 2以降)
- 「この記事は重要か」「新人SIerにどう関係するか」の**解釈**だけ → LLMに任せる

と役割を割り切りました。LLMの出力もPythonのdataclassとして受け取れる形に固定し、後続のパイプライン(Step 3)やSlack通知(Step 4)がLLMの出力形式に振り回されないようにしています。

## 作ったもの

```
src/
├── core/
│   └── models.py             # AnalysisResult dataclass
└── llm/
    ├── ollama_client.py       # analyze(title, content) -> AnalysisResult
    └── prompts/
        └── analyze_item.md    # プロンプト本文(コードから分離)
scripts/
└── check_llm.py               # 動作確認用スクリプト
```

### 1. 出力スキーマを dataclass で固定する

```python:src/core/models.py
from dataclasses import dataclass


@dataclass
class AnalysisResult:
    summary: str
    beginner_note: str
    importance: int
    tags: list[str]
    should_notify: bool
    reason: str
```

- `summary`: 3行以内の要約
- `beginner_note`: 新人SIerへの影響を1文で
- `importance`: 1〜5の整数
- `should_notify`: 通知すべきか
- `reason`: 判定理由。プロンプト改善やデバッグのために「なぜその判定になったか」を必ず言語化させている

### 2. プロンプトはコードから切り離す

プロンプトは `src/llm/ollama_client.py` の中に文字列で埋め込まず、`src/llm/prompts/analyze_item.md` という独立ファイルに置きました。

```markdown:src/llm/prompts/analyze_item.md(抜粋)
あなたは新人SIer(社会人1〜2年目、Javaを中心とした業務システム開発が主戦場)のために、
日々の技術ニュースを整理するアシスタントです。

以下の記事を読み、その新人SIerにとっての価値を判断してください。

# 記事
タイトル: {title}

本文:
{content}

# 出力方針
- summary: 記事の内容を3行以内の日本語で要約する
- beginner_note: この新人SIerの業務・学習にどう関係するかを1文で述べる...
（以下略）
```

理由は2つあります。

1. **プロンプトはコードより頻繁に手直しする**ので、変更履歴をコードの差分と分けて追いたい
2. コードを読まなくても「LLMに何を指示しているか」が一目でわかる

`{title}` `{content}` は Python 側で `str.format()` により埋め込みます。

### 3. Ollamaクライアント本体

```python:src/llm/ollama_client.py
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "beginner_note": {"type": "string"},
        "importance": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "should_notify": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": [
        "summary", "beginner_note", "importance",
        "tags", "should_notify", "reason",
    ],
}


class LLMUnavailableError(Exception):
    pass


def analyze(title: str, content: str) -> AnalysisResult:
    prompt = _PROMPT_TEMPLATE.format(title=title, content=content)
    client = ollama.Client(host=OLLAMA_HOST, timeout=_TIMEOUT_SECONDS)

    last_error: Exception | None = None
    for _ in range(_MAX_ATTEMPTS):
        try:
            response = client.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format=_RESPONSE_SCHEMA,
                options={"temperature": _TEMPERATURE},
            )
            data = json.loads(response["message"]["content"])
            return AnalysisResult(**data)
        except Exception as e:
            last_error = e

    raise LLMUnavailableError(
        f"Ollama analysis failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
```

`ollama` 公式Pythonパッケージの `chat()` は、`format` 引数に**JSON Schemaの辞書をそのまま渡せます**。これでLLMの出力が、指定したスキーマに従ったJSON文字列として返ってくるので、`json.loads()` した後に `AnalysisResult(**data)` でそのままdataclass化できます。普通に便利。

他の実装ポイント:

- `temperature=0.2`: 分析タスクなので創造性より一貫性を優先
- `timeout=120`秒: ローカルGPU(RTX 3070・VRAM 8GB)での推論時間を考慮
- 例外は種類を問わず一度だけリトライし、それでも失敗したら独自例外 `LLMUnavailableError` に包んで送出。呼び出し元(将来のパイプライン)はこの例外だけを見ればよい設計にした

### 4. 環境変数

`.env` で `OLLAMA_HOST`(既定 `http://localhost:11434`)と `OLLAMA_MODEL`(既定 `qwen3:8b`)を切り替えられるようにしました。モデル比較検証をするときもコードを触らずに済みます。

## 検証

`scripts/check_llm.py` で、重要度が異なる3種類のダミー記事を用意して `analyze()` に通し、判定が記事の内容に応じて変わるかを目視確認しました。

| 記事 | importance | should_notify |
|---|---|---|
| Spring FrameworkのRCE脆弱性(CVSS 9.8) | 5 | True |
| 個人ブログのVSCodeテーマ紹介 | 1 | False |
| AWS Lambdaの新ランタイム対応 | 3 | True |

`reason` フィールドも「CVSSスコア9.8の深刻なセキュリティ脆弱性で、Javaベースの業務システム開発に直接影響し即時対応が求められる」のように、判定根拠がちゃんと日本語で返ってきました。モデルは `qwen3:8b`。8Bでここまで読めるのか、というのが正直な感想でした。

Ollamaへの接続ができない状況(存在しないポートを指定)も試し、2回のリトライ後に `LLMUnavailableError` が送出されることを確認。地味な確認ですが、これがStep 3で作るパイプラインの「LLM停止時はキューに積んだまま次回に回す」設計の前提になります。

## ハマったポイント: Windowsコンソールの文字化け

`scripts/check_llm.py` を `uv run python -m scripts.check_llm` でそのまま実行すると、日本語の出力が普通に文字化けしました。Pythonのコードを疑ったのですが、原因はWindowsのコンソール側。既定でShift_JIS系のコードページ(cp932)を使っていて、UTF-8の出力とズレていました。

対処として、スクリプト側で明示的に標準出力をUTF-8化しました。

```python
sys.stdout.reconfigure(encoding="utf-8")
```

環境変数 `PYTHONUTF8=1` や `PYTHONIOENCODING=utf-8` を都度指定する方法もありますが、スクリプト側で固定しておいた方が再現性が高いと判断しました。Step 5でファイルログ出力を実装するときも同じ配慮が必要になりそうな気がします。

## 次回予告

Step 2では、RSSフィードの収集と、SQLiteを使った「既読管理」(同じ記事を2回通知しない仕組み)を実装します。今回のLLM疎通とは完全に独立したパートなので、どちらから手を付けても進められる設計にしています。

---

※ 本記事は、Fable 5 を用いて執筆しています。
