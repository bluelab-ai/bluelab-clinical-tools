#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理 QC 流程的中间产物，把最终报告挪到工作目录根部，然后删掉两个中间目录。

用法::

    python3 cleanup.py [--qc-dir qc_output] [--tables-dir tables_output] \\
                       [--target-dir .] [--yes] [--dry-run]

行为::

1. 把 `qc_output/总体QC报告.md` 和 `qc_output/QC可视化报告.html` 移动到
   `--target-dir`（默认 `.` 即 cwd）
2. `qc_output/` 整目录删除
3. `tables_output/` 整目录删除
4. 原始输入文件（docx/pdf、外部 xlsx）和 skill 本身（SKILL.md / scripts/ /
   assets/ / reference/）都不动

安全约定::

- 默认交互式确认（读到 y/yes 才执行）
- `--yes` / `-y` 跳过确认，供 SKILL.md Phase 7 自动化调用
- `--dry-run` 只打印计划，不实际动手
- 报告文件不存在时显著告警——很可能你还没跑完 Phase 6 就来清理了
"""
import argparse
import os
import shutil
import sys
from pathlib import Path


# qc_output/ 里作为"最终报告"移出保留的文件名（白名单）
# 主名 + 常见变体（防手动调整 --out 时名字不同）
REPORT_KEEP = [
    "总体QC报告.md",
    "QC可视化报告.html",
    # 变体兼容
    "QC总体报告.md",
    "总体报告.md",
    "report-viewer.html",
]


def humansize(n_bytes):
    x = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if x < 1024:
            return f"{x:.1f} {unit}"
        x /= 1024
    return f"{x:.1f} TB"


def dir_size_and_count(path):
    total_size = total_count = 0
    for p in Path(path).rglob("*"):
        if p.is_file():
            total_size += p.stat().st_size
            total_count += 1
    return total_size, total_count


def find_reports_to_move(qc_dir):
    """找 qc_dir 里所有需要移出保留的报告文件。"""
    if not qc_dir.exists():
        return []
    return [qc_dir / name for name in REPORT_KEEP if (qc_dir / name).is_file()]


def print_plan(reports, target_dir, qc_dir, tables_dir):
    """打印计划。"""
    print("─" * 60)

    print("移动（qc_output/ 里的报告 → 目标目录）：")
    if reports:
        for src in reports:
            dst = target_dir / src.name
            print(f"  ↪ {src.name}  ({humansize(src.stat().st_size)})  →  {dst}")
    else:
        print("  （qc_output/ 里没找到 总体QC报告.md 或 QC可视化报告.html）")

    print("\n删除：")
    qc_exists = qc_dir.exists()
    if qc_exists:
        size, n = dir_size_and_count(qc_dir)
        print(f"  📁 {qc_dir}/  （{n} 文件，{humansize(size)}）")
    else:
        print(f"  📁 {qc_dir}/  不存在，跳过")

    tables_exists = tables_dir.exists()
    if tables_exists:
        size, n = dir_size_and_count(tables_dir)
        print(f"  📁 {tables_dir}/  （{n} 文件，{humansize(size)}）")
    else:
        print(f"  📁 {tables_dir}/  不存在，跳过")

    print("\n保持不动：SKILL.md / scripts/ / assets/ / reference/ + 原始输入文件")
    print("─" * 60)
    return qc_exists, tables_exists


def do_cleanup(reports, target_dir, qc_dir, tables_dir, qc_exists, tables_exists):
    """执行移动 + 删除。返回 (moved 数, err 数)。"""
    n_moved = n_err = 0
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. 移动报告到 target_dir
    for src in reports:
        dst = target_dir / src.name
        try:
            if dst.exists() and dst.resolve() != src.resolve():
                dst.unlink()
            shutil.move(str(src), str(dst))
            n_moved += 1
        except OSError as e:
            print(f"  ✗ 移动失败 {src} → {dst}: {e}", file=sys.stderr)
            n_err += 1

    # 2. 删除 qc_dir 整目录（此时报告已挪走）
    if qc_exists:
        try:
            shutil.rmtree(qc_dir)
        except OSError as e:
            print(f"  ✗ 删除 {qc_dir} 失败: {e}", file=sys.stderr)
            n_err += 1

    # 3. 删除 tables_dir 整目录
    if tables_exists:
        try:
            shutil.rmtree(tables_dir)
        except OSError as e:
            print(f"  ✗ 删除 {tables_dir} 失败: {e}", file=sys.stderr)
            n_err += 1

    return n_moved, n_err


def main():
    ap = argparse.ArgumentParser(
        description="清理 QC 中间产物：把最终报告挪到 target-dir，删除 tables_output/ 与 qc_output/"
    )
    ap.add_argument("--qc-dir", default="qc_output",
                    help="QC 输出目录（默认 qc_output）；会被整个删除")
    ap.add_argument("--tables-dir", default="tables_output",
                    help="表格提取目录（默认 tables_output）；会被整个删除")
    ap.add_argument("--target-dir", default=".",
                    help="报告最终存放位置（默认 . 即当前工作目录）")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="跳过交互确认（Phase 7 自动化调用时用）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印计划，不实际动手")
    args = ap.parse_args()

    qc_dir = Path(args.qc_dir).resolve()
    tables_dir = Path(args.tables_dir).resolve()
    target_dir = Path(args.target_dir).resolve()

    reports = find_reports_to_move(qc_dir)
    qc_exists, tables_exists = print_plan(reports, target_dir, qc_dir, tables_dir)

    if not reports and (qc_exists or tables_exists):
        print("\n⚠️  没找到最终报告文件——如果你还没跑完 Phase 6，现在清理会丢掉所有中间"
              "产物且没有任何报告留下。", file=sys.stderr)

    if not qc_exists and not tables_exists:
        print("\n两个目录都不存在，无事可做。")
        return

    if args.dry_run:
        print("\n[--dry-run] 未执行。")
        return

    if not args.yes:
        try:
            resp = input("\n确认执行？(y/N): ").strip().lower()
        except EOFError:
            resp = ""
        if resp not in ("y", "yes"):
            print("已取消。")
            return

    n_moved, n_err = do_cleanup(reports, target_dir, qc_dir, tables_dir,
                                qc_exists, tables_exists)

    print(f"\n完成：报告移动 {n_moved} 份，两个中间目录已删除"
          + (f"，失败 {n_err} 项" if n_err else "") + "。")
    for src in reports:
        print(f"  → {target_dir / src.name}")


if __name__ == "__main__":
    main()
