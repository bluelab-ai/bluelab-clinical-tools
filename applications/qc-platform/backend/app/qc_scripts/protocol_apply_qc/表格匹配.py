#!/usr/bin/env python3
"""
将表格目录与方案提取的 JSON 匹配，填补各分析的「表格」字段。

用法:
  python 表格匹配.py -s ../方案输出/xxx.json -t ../表格输出/表格-标题索引.json
  python 表格匹配.py -s ../方案输出/xxx.json -t ../表格输出/表格-标题索引.json --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from anthropic import Anthropic

# ============================================================================
# 配置
# ============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent

import sys, os as _os
_sys_path_add = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..')
if _sys_path_add not in sys.path:
    sys.path.insert(0, _sys_path_add)
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL as API_MODEL

API_BASE_URL = LLM_API_BASE
API_AUTH_TOKEN = LLM_API_KEY

# ============================================================================
# 表格目录解析
# ============================================================================


def parse_catalog_md(md_path: str) -> list[dict]:
    """从 Markdown 或 JSON 表格目录解析出结构化列表。"""
    with open(md_path, encoding="utf-8") as f:
        text = f.read()

    # 先尝试 JSON 数组格式（extract_tables.py 的 表格-标题索引.json）
    if text.strip().startswith("["):
        try:
            items = json.loads(text)
            tables = []
            for t in items:
                sets = t.get("analysis_sets", [])
                tables.append({
                    "num": t.get("num", ""),
                    "name": t.get("title", ""),
                    "section": t.get("section", ""),
                    "analysis_set": ", ".join(sets) if sets else t.get("population", ""),
                })
            return tables
        except json.JSONDecodeError:
            pass  # 回退到 Markdown / 旧 JSON 解析

    # 再尝试 JSON 对象格式（extract_table_catalog.py --json 的输出）
    if text.strip().startswith("{"):
        try:
            data = json.loads(text)
            tables = []
            for t in data.get("tables", []):
                sets = t.get("analysis_sets", [])
                tables.append({
                    "num": t.get("num", ""),
                    "name": t.get("title", ""),
                    "section": t.get("section", ""),
                    "analysis_set": ", ".join(sets) if sets else "",
                })
            return tables
        except json.JSONDecodeError:
            pass  # 回退到 Markdown 解析

    tables = []
    current_section = []
    # 跟踪章节层级
    for line in text.split("\n"):
        line = line.rstrip()

        # 标题行
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line.lstrip("# ").strip()
            # 修剪章节栈
            current_section = current_section[: level - 1]
            current_section.append(title)
            continue

        # 表格数据行: | 表11.5.1.1 | xxx | FAS |
        if line.startswith("| 表") and not line.startswith("| 表号"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and re.match(r"\d+(?:[\.\-]\d+)*", parts[1].removeprefix("表")):
                table_num = parts[1].removeprefix("表")
                table_name = parts[2]
                analysis_set = parts[3] if parts[3] and parts[3] != "—" else ""
                tables.append({
                    "num": table_num,
                    "name": table_name,
                    "section": " > ".join(current_section),
                    "analysis_set": analysis_set,
                })

    return tables


def catalog_summary(tables: list[dict]) -> str:
    """生成表格目录的紧凑摘要，供 LLM 匹配使用。"""
    lines = ["# 表格目录（供匹配用）", ""]
    current_section = ""
    for t in tables:
        sec = t["section"]
        if sec != current_section:
            current_section = sec
            lines.append(f"\n## {sec}")
        lines.append(f"| 表{t['num']} | {t['name']} | {t['analysis_set'] or '—'} |")
    return "\n".join(lines)


# ============================================================================
# LLM 匹配
# ============================================================================

MATCH_SYSTEM_PROMPT = """你是临床试验统计程序员。根据以下信息，将表格编号匹配到各分析类别。

## 输入
1. 方案提取的 JSON（各分析类别有「条目」描述分析内容，「表格」字段为空）
2. 表格目录（按章节组织的表格列表，含表号、表名、分析集）

## 匹配规则
- 根据分析类别的名称和条目内容，判断该分析对应表格目录中哪些表
- 表格的分析集标签（FAS/PPS/SS）应与分析类别声明的分析人群匹配
- 同一分析可能对应多张表（如分层分析、协方差分析等），全部列出
- 每张表号后面用括号标注其分析集，如 "11.5.1.1(FAS), 11.5.1.2(PPS), 11.5.1.7(FAS)"
- 如果某个分析在表格目录中找不到对应表格，表格字段留空 ""

## 典型对应关系
- 主要终点分析 → 疗效指标 > 主要疗效指标 下的表
- 次要终点分析 → 疗效指标 > 次要疗效指标 下的表
- 安全性分析 → 安全性指标 下的表
- 受试者分布分析 → 病例分布 下的表
- 人口学与基线特征分析 → 人口学信息和基线资料 + 治疗期信息 下的表

## 输出格式
返回纯 JSON，不要 ```json``` 包裹，不要额外解释。
在输入的 JSON 基础上，只修改「表格」字段的值，其他内容原样保留。
只修改那些有对应表格的分析类别（受试者分布分析、人口学与基线特征分析、主要终点分析、次要终点分析、安全性分析）。
不要修改其他字段。

输出格式示例：
{
  "统计分析计划": {
    "分析人群": {...},
    "主要终点分析": {
      "分析人群": "FAS、PPS",
      "表格": "11.5.1.1(FAS), 11.5.1.2(PPS), 11.5.1.7(FAS), 11.5.1.8(PPS)",
      "条目": [...]
    }
  }
}"""


def match_tables(client: Anthropic, scheme_json: dict, catalog_text: str,
                 verbose: bool = True) -> dict:
    """调用 LLM 匹配表格。"""
    scheme_str = json.dumps(scheme_json, ensure_ascii=False, indent=2)

    user_msg = f"""请根据以下表格目录，为方案提取 JSON 中的各分析类别填入对应的表格编号。

## 表格目录
{catalog_text}

## 方案提取 JSON（表格字段待填充）
{scheme_str}"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=API_MODEL,
                max_tokens=8192,
                temperature=0,
                system=MATCH_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                thinking={"type": "disabled"},
            )
        except Exception as e:
            if verbose:
                print(f"  ⚠️ API 异常 (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
                continue
            break

        full_text = "".join(b.text for b in resp.content if b.type == "text")
        if not full_text.strip():
            if verbose:
                print(f"  ⚠️ API 空返回，重试 {attempt + 1}/{max_retries}...")
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
            continue

        # 清理 JSON
        json_text = full_text.strip()
        json_text = re.sub(r"^```(?:json)?\s*\n?", "", json_text)
        json_text = re.sub(r"\n?```\s*$", "", json_text)

        try:
            result = json.loads(json_text)
            if "统计分析计划" in result:
                return result
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", full_text, re.DOTALL)
            if m:
                try:
                    result = json.loads(m.group())
                    if "统计分析计划" in result:
                        return result
                except json.JSONDecodeError:
                    pass

        if verbose:
            print(f"  ⚠️ JSON 解析失败，重试 {attempt + 1}/{max_retries}...")
        if attempt < max_retries - 1:
            time.sleep((attempt + 1) * 2)

    if verbose:
        print("  ❌ 匹配失败")
    return scheme_json


# ============================================================================
# 主流程
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="表格匹配：将表格目录与方案 JSON 匹配，填补表格字段")
    parser.add_argument("-s", "--scheme", required=True, help="方案提取 JSON 路径")
    parser.add_argument("-t", "--table-catalog", required=True, help="表格索引 JSON 或 MD 路径")
    parser.add_argument("-o", "--output", default=None, help="输出路径（默认覆盖原 JSON）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印匹配结果，不写文件")
    args = parser.parse_args()

    if not os.path.exists(args.scheme):
        sys.exit(f"方案 JSON 不存在: {args.scheme}")
    if not os.path.exists(args.table_catalog):
        sys.exit(f"表格目录文件不存在: {args.table_catalog}")

    # 读取输入
    with open(args.scheme, encoding="utf-8") as f:
        scheme = json.load(f)

    catalog_tables = parse_catalog_md(args.table_catalog)
    catalog_text = catalog_summary(catalog_tables)

    print(f"📋 表格目录: {len(catalog_tables)} 张表")
    print(f"📄 方案 JSON: {os.path.basename(args.scheme)}")

    # 统计当前空表格字段
    plan = scheme.get("统计分析计划", scheme)
    empty_fields = []
    for cat, val in plan.items():
        if isinstance(val, dict) and "表格" in val and val["表格"] == "":
            empty_fields.append(cat)
    print(f"🔍 待匹配的分析类别: {empty_fields}")

    # LLM 匹配
    client = Anthropic(base_url=API_BASE_URL, auth_token=API_AUTH_TOKEN, timeout=180, max_retries=3)
    result = match_tables(client, scheme, catalog_text)

    # 输出
    out_path = args.output or args.scheme

    if args.dry_run:
        # 只打印匹配结果
        plan = result.get("统计分析计划", result)
        for cat in empty_fields:
            val = plan.get(cat, {})
            tables = val.get("表格", "") if isinstance(val, dict) else ""
            print(f"\n  [{cat}]")
            print(f"    分析人群: {val.get('分析人群', '')}")
            print(f"    表格: {tables or '(未匹配)'}")
        return

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 打印匹配摘要
    plan = result.get("统计分析计划", result)
    matched = 0
    for cat in empty_fields:
        val = plan.get(cat, {})
        tables = val.get("表格", "") if isinstance(val, dict) else ""
        count = len(tables.split(",")) if tables else 0
        print(f"  ✅ {cat}: {count} 张表 → {tables[:80]}{'...' if len(tables)>80 else ''}")
        if tables:
            matched += 1

    print(f"\n💾 已保存 → {out_path}")
    print(f"   匹配成功: {matched}/{len(empty_fields)}")


if __name__ == "__main__":
    main()
