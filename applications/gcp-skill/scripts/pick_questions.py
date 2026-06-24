#!/usr/bin/env python3
"""按规则从题库加权随机抽题。真随机，结果由调用方写入 training record 持久化。

用法:
  # 章节测验（第一章，3题，单选）
  python3 scripts/pick_questions.py --mode chapter --chapter 第一章

  # 章节测验（老手轨 B 分支，仅抽 🔴🟡 变化题）
  python3 scripts/pick_questions.py --mode chapter --chapter 第一章 --change-only

  # 结业考试（30题，每章5题）
  python3 scripts/pick_questions.py --mode final

输出: --ids-only 仅输出 ID 数组，否则输出含题目摘要的 JSON
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def weighted_sample(pool, count, change_weights):
    """从 pool 中不放回加权随机抽取 count 个。"""
    if count >= len(pool):
        return list(pool)

    remaining = list(pool)
    selected = []

    for _ in range(count):
        weights = [change_weights.get(q.get("change_level", "🟢"), 1) for q in remaining]
        total = sum(weights)
        if total == 0:
            break
        r = random.random() * total
        cumulative = 0
        for i, w in enumerate(weights):
            cumulative += w
            if r < cumulative:
                selected.append(remaining.pop(i))
                break

    return selected


def pick_chapter(bank, module, count, change_only=False, allowed_types=None):
    """从指定章节抽题。"""
    pool = [q for q in bank["questions"] if q["module"] == module]

    # 仅抽变化题（🔴🟡）
    if change_only:
        priority = [q for q in pool if q.get("change_level") in ("🔴", "🟡")]
        if len(priority) >= count:
            pool = priority

    # 按题型过滤
    if allowed_types:
        type_pool = [q for q in pool if q["type"] in allowed_types]
        if type_pool:
            pool = type_pool

    if len(pool) <= count:
        return pool

    change_weights = {"🔴": 3, "🟡": 2, "🟢": 1}
    return weighted_sample(pool, count, change_weights)


def pick_final(bank, rules):
    """结业考试：每章 5 题，加权随机。"""
    change_weights = rules.get("change_weight", {"🔴": 3, "🟡": 2, "🟢": 1})
    per_chapter = rules.get("per_chapter", 5)
    chapters = ["第一章", "第二章", "第三章", "第四章", "第五章", "第六章"]

    all_picks = []
    for ch in chapters:
        pool = [q for q in bank["questions"] if q["module"] == ch]
        if len(pool) <= per_chapter:
            picks = list(pool)
        else:
            picks = weighted_sample(pool, per_chapter, change_weights)
        picks.sort(key=lambda q: q["id"])
        all_picks.extend(picks)

    return all_picks


def main():
    parser = argparse.ArgumentParser(description="GCP 题库加权随机抽题")
    parser.add_argument("--mode", choices=["chapter", "final"], required=True)
    parser.add_argument("--chapter", help="章节名（如 第一章），chapter 模式必填")
    parser.add_argument("--change-only", action="store_true",
                        help="仅抽 🔴🟡 变化题（老手轨 B 分支使用）")
    parser.add_argument("--bank", default=str(ROOT / "exams" / "bank.json"))
    parser.add_argument("--rules-chapter", default=str(ROOT / "exams" / "chapter-quiz-rules.json"))
    parser.add_argument("--rules-final", default=str(ROOT / "exams" / "final-exam-rules.json"))
    parser.add_argument("--ids-only", action="store_true",
                        help="仅输出题目 ID 的 JSON 数组")

    args = parser.parse_args()

    bank = load_json(args.bank)

    if args.mode == "chapter":
        if not args.chapter:
            print("错误：chapter 模式需要 --chapter 参数", file=sys.stderr)
            sys.exit(1)
        rules = load_json(args.rules_chapter)
        mod_rules = rules["modules"].get(args.chapter, {})
        count = mod_rules.get("count", 3)
        allowed_types = mod_rules.get("types")

        picks = pick_chapter(bank, args.chapter, count,
                             change_only=args.change_only,
                             allowed_types=allowed_types)
    else:
        rules = load_json(args.rules_final)
        picks = pick_final(bank, rules)

    if args.ids_only:
        print(json.dumps([q["id"] for q in picks], ensure_ascii=False, indent=2))
    else:
        output = []
        for q in picks:
            output.append({
                "id": q["id"],
                "module": q["module"],
                "article": q["article"],
                "type": q["type"],
                "change_level": q.get("change_level", "🟢"),
                "question": q["question"][:60] + "…" if len(q["question"]) > 60 else q["question"],
            })
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
