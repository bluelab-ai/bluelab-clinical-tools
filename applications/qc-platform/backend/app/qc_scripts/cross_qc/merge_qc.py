"""将 QC结果-PairN.md 按序号合并为一个层次分明的大 md 文件 v3.0 — 四级问题分级"""
import os, re, sys


def demote_headers(content: str) -> str:
    """将内容中所有 markdown 标题降一级（# → ##, ### → #### 等）"""
    lines = content.split('\n')
    result = []
    for line in lines:
        if line.startswith('#'):
            m = re.match(r'^(#{1,6})\s', line)
            if m:
                level = len(m.group(1))
                if level < 6:
                    line = '#' * (level + 1) + line[level:]
        result.append(line)
    return '\n'.join(result)


def extract_meta(content: str) -> tuple:
    """从 META 元数据行确定性提取表格名称、结论、清单信息（v3.0 格式）
    返回 (title, conclusion, listings_text)
    """
    title = ""
    conclusion = ""
    listings = ""

    m = re.search(r'^##META_TABLE:\s*(.+)$', content, re.MULTILINE)
    if m:
        title = m.group(1).strip()

    m = re.search(r'^##META_CONCLUSION:\s*(PASS|MAJOR|MINOR|SUGGESTION|PENDING)\s*$', content, re.MULTILINE)
    if m:
        conclusion = m.group(1).strip()

    m = re.search(r'^##META_LISTING:\s*(.+)$', content, re.MULTILINE)
    if m:
        listings = m.group(1).strip()

    return title, conclusion, listings


def extract_title(content: str) -> str:
    """提取表格名称 — 优先 META 行"""
    title, _, _ = extract_meta(content)
    if title:
        return title

    m = re.search(r'^#\s+.*Pair\s*\d+[：:]\s*(.+?)(?:\s+vs\s+.+)?$', content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r'\*\*表格名称\*\*[：:]\s*(.+)$', content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    for m in re.finditer(r'^###\s+(.+)$', content, re.MULTILINE):
        title = m.group(1).strip()
        if re.match(r'^(核查\d*[：:]|第\d|差异\d*[：:]|Check\s*\d|步骤\s*\d|\d+\.|结论|建议|基本信息|参考|QC规则|发现的问题)', title):
            continue
        return title
    return "未知表格"


# 分级显示配置
SEVERITY_CONFIG = {
    'MAJOR':      {'emoji': '🟠', 'label': 'Major',      'order': 0},
    'MINOR':      {'emoji': '🟡', 'label': 'Minor',      'order': 1},
    'SUGGESTION': {'emoji': '🔵', 'label': 'Suggestion', 'order': 2},
    'PENDING':    {'emoji': '🟣', 'label': '待人工',      'order': 3},
    'PASS':       {'emoji': '✅', 'label': '无问题',      'order': 4},
}

SEVERITY_LABEL_MAP = {
    'MAJOR': '🟠 Major',
    'MINOR': '🟡 Minor',
    'SUGGESTION': '🔵 Suggestion',
    'PENDING': '🟣 待人工',
    'PASS': '✅ 无问题',
}


def extract_conclusion(content: str) -> str:
    """提取结论 — 优先 META 行"""
    _, conclusion, _ = extract_meta(content)
    if conclusion:
        return SEVERITY_LABEL_MAP.get(conclusion, conclusion)

    # legacy fallback
    tail_len = max(len(content) // 3, 500)
    tail = content[-tail_len:]
    if re.search(r'\*\*判定[：:]\s*MAJOR\*\*', tail):
        return '🟠 Major'
    if re.search(r'\*\*判定[：:]\s*PENDING\*\*', tail):
        return '🟣 待人工'
    if re.search(r'\*\*判定[：:]\s*MINOR\*\*', tail):
        return '🟡 Minor'
    if re.search(r'\*\*判定[：:]\s*SUGGESTION\*\*', tail):
        return '🔵 Suggestion'
    if re.search(r'\*\*判定[：:]\s*PASS\*\*', tail):
        return '✅ 无问题'
    return '✅ 无问题'


def merge_qc_results(target_dir: str, output_file: str):
    files = []
    for fname in os.listdir(target_dir):
        m = re.match(r'^QC结果-Pair(\d+)\.md$', fname)
        if m:
            files.append((int(m.group(1)), fname))
    files.sort(key=lambda x: x[0])

    if not files:
        print("未找到 QC结果-PairN.md 文件")
        return

    # 先收集所有 pair 的标题和结论
    toc = []
    pair_data = []
    for num, fname in files:
        fpath = os.path.join(target_dir, fname)
        with open(fpath) as f:
            content = f.read()
        title, conclusion_v2, listings = extract_meta(content)
        if not title:
            title = extract_title(content)
        conclusion = extract_conclusion(content)
        toc.append((num, title, conclusion, conclusion_v2))
        pair_data.append((num, title, conclusion, conclusion_v2, listings, content))

    # 按 severity 统计
    from collections import Counter
    sev_counter = Counter()
    for _, _, _, sev, _, _ in pair_data:
        sev_counter[sev if sev else 'PASS'] += 1

    pass_n = sev_counter.get('PASS', 0)
    major_n = sev_counter.get('MAJOR', 0)
    minor_n = sev_counter.get('MINOR', 0)
    suggestion_n = sev_counter.get('SUGGESTION', 0)
    pending_n = sev_counter.get('PENDING', 0)
    total_issues = major_n + minor_n + suggestion_n

    with open(output_file, 'w') as out:
        # ========== 封面 ==========
        out.write("# TFL 反向质控核查 — QC 结果报告\n\n")
        out.write(f"**核查日期**: 2026-06-16  \n")
        docx_files = sorted([f for f in os.listdir(target_dir) if f.endswith('.docx') and not f.startswith('~')])
        for docx_f in docx_files:
            out.write(f"**源文件**: {docx_f}  \n")
        out.write(f"**核查对数**: {len(files)} 对\n\n")

        out.write("## 核查概览\n\n")
        out.write("| 分级 | 数量 |\n")
        out.write("|------|------|\n")
        out.write(f"| ✅ 无问题 | {pass_n} |\n")
        out.write(f"| 🟠 Major | {major_n} |\n")
        out.write(f"| 🟡 Minor | {minor_n} |\n")
        out.write(f"| 🔵 Suggestion | {suggestion_n} |\n")
        out.write(f"| 🟣 待人工 | {pending_n} |\n\n")

        if total_issues > 0:
            out.write(f"**问题总计**: {total_issues} 对存在问题，详见下方。\n\n")

        # ========== 问题分级标准 ==========
        out.write("## 问题分级标准\n\n")
        out.write("| 级别 | 定义 | 示例 |\n")
        out.write("|------|------|------|\n")
        out.write("| 🟠 Major | 明显错误：可验证的算术错误、数据不一致 | 合计≠各组之和；Table计数与Listing反推不一致；N值矛盾 |\n")
        out.write("| 🟡 Minor | 小问题：格式、表号、脚注、编码、舍入 | 表号引用错误；N标注格式不统一；百分比四舍五入不一致（≤0.2%） |\n")
        out.write("| 🔵 Suggestion | 疑似问题或改进建议 | 疑似不一致但无法确认；建议补充脚注；措辞统一建议 |\n")
        out.write("| 🟣 待人工 | 匹配疑似错误，需人工确认 | Listing内容与表格语义不匹配；清单人群与表格数据不符 |\n\n")

        out.write("---\n\n")

        # ========== 目录 ==========
        out.write("## 目录\n\n")
        for num, title, conclusion, sev in toc:
            short = title[:60] + ("..." if len(title) > 60 else "")
            badge = SEVERITY_CONFIG.get(sev if sev else 'PASS', SEVERITY_CONFIG['PASS'])
            out.write(f"- [Pair {num}: {short}](#pair-{num})  {badge['emoji']} {badge['label']}\n")
        out.write("\n---\n\n")

        # ========== 逐对拼接 ==========
        for idx, (num, title, conclusion, sev, listings, content) in enumerate(pair_data):
            if idx > 0:
                out.write("\n\n---\n\n")

            badge = SEVERITY_CONFIG.get(sev if sev else 'PASS', SEVERITY_CONFIG['PASS'])
            out.write(f'## <a id="pair-{num}"></a>Pair {num}: {title}\n\n')
            out.write(f"**结论: {badge['emoji']} {badge['label']}**\n\n")

            if listings:
                parts = [p.strip() for p in re.split(r'\|\|', listings)]
                out.write("| 参考清单 | 清单人群 |\n")
                out.write("|----------|----------|\n")
                for p in parts:
                    if '|' in p:
                        name, pop = p.split('|', 1)
                        out.write(f"| {name} | {pop} |\n")
                out.write("\n")

            # 去掉 META 行后再降级写入正文
            body = re.sub(r'^##META_\w+:.*\n?', '', content, flags=re.MULTILINE).strip()
            body = demote_headers(body)
            # 去掉第一个标题行（已被 Pair 标题替代）
            body = re.sub(r'^####\s+.*\n', '', body, count=1, flags=re.MULTILINE).strip()
            # 去掉原始文件自带的参考清单表格（merge已从META插入），支持多行
            body = re.sub(r'^\| 参考清单 \| 清单人群 \|\n\|[-| ]+\|\n(?:\|.+\|\n)*', '', body, count=1, flags=re.MULTILINE).strip()
            out.write(body)

        out.write("\n")

    print(f"已合并 {len(files)} 个文件 → {output_file}")
    print(f"层次: # 总标题 → ## Pair N → 原文件 ###/#### 等自动降级")
    print(f"PASS={pass_n} MAJOR={major_n} MINOR={minor_n} SUGGESTION={suggestion_n} PENDING={pending_n}")


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    output = sys.argv[2] if len(sys.argv) > 2 else os.path.join(target, 'QC结果-全部合并.md')
    merge_qc_results(target, output)
