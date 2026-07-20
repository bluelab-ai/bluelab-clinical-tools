"""清理 TFL QC 流程产生的中间文件，保留原始输入和最终报告"""
import os, sys, glob, argparse, shutil


# 中间文件/文件夹模式（相对于项目目录）
INTERMEDIATE_PATTERNS = [
    # Phase 1 匹配
    "表格-清单-映射表.json",
    "映射复核.html",
    # Phase 2 提取的 Excel 文件夹
    "表格",
    "清单",
    # Phase 3 各 pair 独立结果
    "QC结果-Pair*.md",
    # 子代理遗留的临时 Python 脚本
    "qc_pair*.py",
    # 临时文件和符号链接
    "表格附件.docx",
    "清单附件.docx",
]

KEPT_PATTERNS = [
    "*.docx",
    "*.pdf",
    "QC报告-汇总.md",
    "QC结果-全部合并.md",
]


def find_entries(target_dir: str, patterns: list[str]) -> list[str]:
    """在目录下按模式找文件和文件夹，返回匹配的相对路径列表"""
    found = []
    for pat in patterns:
        full_pat = os.path.join(target_dir, pat)
        for f in glob.glob(full_pat):
            found.append(os.path.basename(f))
    return sorted(set(found))


def main():
    parser = argparse.ArgumentParser(description="清理 TFL QC 中间文件")
    parser.add_argument("target", nargs="?", default=os.getcwd(),
                        help="项目目录 (默认当前目录)")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="只列出要删除的文件，不实际删除")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="跳过确认，直接删除")
    args = parser.parse_args()

    target = args.target
    if not os.path.isdir(target):
        print(f"目录不存在: {target}")
        sys.exit(1)

    to_delete = find_entries(target, INTERMEDIATE_PATTERNS)
    kept = find_entries(target, KEPT_PATTERNS)

    if not to_delete:
        print("没有找到中间文件，无需清理。")
        return

    print(f"目标目录: {target}\n")
    print(f"待删除 ({len(to_delete)} 个中间文件/文件夹):")
    for f in to_delete:
        fpath = os.path.join(target, f)
        if os.path.isdir(fpath):
            # 统计文件夹内文件数
            file_count = sum(1 for _ in glob.glob(os.path.join(fpath, "**", "*"), recursive=True) if os.path.isfile(_))
            print(f"  ✕ {f}/  (文件夹, {file_count} 个文件)")
        else:
            size = os.path.getsize(fpath)
            print(f"  ✕ {f}  ({size:,} bytes)")
    print()
    print(f"保留的文件 ({len(kept)} 个):")
    for f in kept:
        print(f"  ✓ {f}")

    if args.dry_run:
        print(f"\n[--dry-run] 未执行删除。")
        return

    if not args.yes:
        resp = input(f"\n确认删除以上 {len(to_delete)} 个中间文件? [y/N]: ").strip().lower()
        if resp not in ('y', 'yes'):
            print("已取消。")
            return

    for f in to_delete:
        fpath = os.path.join(target, f)
        if os.path.isdir(fpath):
            shutil.rmtree(fpath)
            print(f"  已删除: {f}/")
        elif os.path.islink(fpath):
            os.unlink(fpath)
            print(f"  已删除: {f} (symlink)")
        else:
            os.remove(fpath)
            print(f"  已删除: {f}")

    print(f"\n清理完成，删除了 {len(to_delete)} 个中间文件/文件夹。")


if __name__ == '__main__':
    main()
