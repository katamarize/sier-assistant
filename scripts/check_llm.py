"""Step 1 動作確認用スクリプト。

固定の日本語記事テキスト(重要/軽微)を analyze() に渡し、
should_notify の判定が記事の重要度に応じて変化することを目視確認する。
"""

import sys
from dataclasses import asdict

from src.llm.ollama_client import LLMUnavailableError, analyze

sys.stdout.reconfigure(encoding="utf-8")

SAMPLES = [
    (
        "重要: Spring Frameworkに深刻なRCE脆弱性、緊急パッチ公開",
        "Spring Frameworkの主要バージョンにリモートコード実行(RCE)を許す"
        "重大な脆弱性が発見された。CVSSスコアは9.8と評価されており、"
        "外部公開されているSpring製Webアプリケーションは早急なパッチ適用が"
        "推奨される。開発元は影響を受けるバージョン一覧と緊急パッチを"
        "公式サイトで公開した。",
    ),
    (
        "軽微: 個人ブログでのVSCodeテーマ紹介記事が公開",
        "あるエンジニアの個人ブログで、お気に入りのVSCode配色テーマを"
        "紹介する記事が公開された。業務での利用を推奨するものではなく、"
        "個人の好みに基づいた紹介にとどまる内容。",
    ),
    (
        "中程度: AWS Lambdaが新しいランタイムをサポート",
        "AWSはLambdaにおいて新しい言語ランタイムのサポートを発表した。"
        "既存の関数への影響はなく、新規関数作成時に選択可能になる。"
        "移行は任意であり、既存システムへの緊急対応は不要。",
    ),
]


def main() -> None:
    for title, content in SAMPLES:
        print(f"=== {title} ===")
        try:
            result = analyze(title, content)
        except LLMUnavailableError as e:
            print(f"  LLMUnavailableError: {e}")
            continue
        for key, value in asdict(result).items():
            print(f"  {key}: {value}")
        print()


if __name__ == "__main__":
    main()
