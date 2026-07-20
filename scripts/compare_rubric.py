"""Step 6 検証: ルーブリック改訂の before/after 比較。

本番DB(data/assistant.db)を読み取り専用で開き、importance の各層から
サンプルを抽出。旧プロンプト(退避済み fixture)と新プロンプト(現行ファイル)を
同一サンプルに当てて再評価し、importance 分布の偏りが緩和されるかを確認する。

本番DBには一切書き込まない(既存評価は上書きしない)。

使い方:
    uv run python scripts/compare_rubric.py            # 各層7件ずつ
    uv run python scripts/compare_rubric.py --per 10   # 各層10件ずつ
"""

import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.llm_client import LLMUnavailableError, analyze

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "data" / "assistant.db"
_OLD_PROMPT = (_ROOT / "scripts" / "fixtures" / "analyze_item_old.md").read_text(
    encoding="utf-8"
)
_NEW_PROMPT = (_ROOT / "src" / "llm" / "prompts" / "analyze_item.md").read_text(
    encoding="utf-8"
)


def _load_sample(per_level: int) -> list[sqlite3.Row]:
    # 読み取り専用で接続(URI の mode=ro)。誤って書き込まないための保険。
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows: list[sqlite3.Row] = []
    for level in (1, 2, 3, 4, 5):
        # 層ごとに件数を揃えて抽出(ランダム)。content が空のものは除外。
        cur = conn.execute(
            """
            SELECT id, title, content, importance
            FROM items
            WHERE importance = ? AND content IS NOT NULL AND content != ''
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (level, per_level),
        )
        rows.extend(cur.fetchall())
    conn.close()
    return rows


def _evaluate(rows: list[sqlite3.Row]) -> list[dict]:
    results = []
    for i, row in enumerate(rows, 1):
        title, content = row["title"], row["content"]
        print(f"  [{i}/{len(rows)}] id={row['id']} 再評価中...", flush=True)
        try:
            old = analyze(title, content, prompt_template=_OLD_PROMPT)
            new = analyze(title, content, prompt_template=_NEW_PROMPT)
        except LLMUnavailableError as e:
            print(f"    skip (LLM error): {e}")
            continue
        results.append(
            {
                "id": row["id"],
                "title": title,
                "db": row["importance"],
                "old": old.importance,
                "new": new.importance,
            }
        )
    return results


def _print_dist(label: str, values: list[int]) -> None:
    c = Counter(values)
    total = len(values)
    print(f"\n=== {label}(n={total})===")
    for level in (1, 2, 3, 4, 5):
        n = c.get(level, 0)
        pct = (n / total * 100) if total else 0
        bar = "#" * n
        print(f"  {level}: {n:3d} ({pct:5.1f}%) {bar}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per", type=int, default=7, help="importance 各層の抽出件数")
    args = parser.parse_args()

    rows = _load_sample(args.per)
    print(f"サンプル {len(rows)} 件を再評価します(新旧プロンプト × 各1回)")
    results = _evaluate(rows)
    if not results:
        print("有効な結果がありません")
        return

    _print_dist("DB(参考・改訂前の本番値)", [r["db"] for r in results])
    _print_dist("旧プロンプト(再評価)", [r["old"] for r in results])
    _print_dist("新プロンプト(ルーブリック)", [r["new"] for r in results])

    # 旧→新 の遷移(何が動いたか)
    shift = defaultdict(int)
    for r in results:
        shift[(r["old"], r["new"])] += 1
    print("\n=== 旧→新 の遷移(変化したものだけ)===")
    for (o, n), cnt in sorted(shift.items()):
        if o != n:
            print(f"  {o} → {n}: {cnt}件")
    unchanged = sum(cnt for (o, n), cnt in shift.items() if o == n)
    print(f"  (変化なし: {unchanged}件)")

    # 個別の内訳
    print("\n=== 個別(旧→新)===")
    for r in results:
        mark = "  " if r["old"] == r["new"] else "* "
        t = (r["title"] or "")[:40]
        print(f"  {mark}id={r['id']:<5} {r['old']}→{r['new']}  {t}")


if __name__ == "__main__":
    main()
