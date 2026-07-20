#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从人群划分表 xlsx 抽出 baseline.json — LLM 自动识别所有人群标签。

与旧版不同：不再硬编码 FAS/PPS/SS 白名单。使用 Anthropic SDK tool loop
让 LLM 读 xlsx → 自动发现所有分析集标签 → 抽数 → 落盘 baseline.json。

用法::

    # 需要 API key
    python3 extract_baseline.py <人群划分表.xlsx> \
        --api-key sk-xxx \
        [--out tables_output/baseline.json]

    # 也可通过环境变量传入
    export ANTHROPIC_AUTH_TOKEN=sk-xxx
    python3 extract_baseline.py <人群划分表.xlsx>

输出 JSON 结构::

    {
      "FAS":        {"试验组": 50, "对照组": 48, "合计": 98},
      "PPS":        {"试验组": 47, "对照组": 45, "合计": 92},
      "SS":         {"试验组": 50, "对照组": 49, "合计": 99},
      "ITT人群":     {"试验组": 55, "对照组": 53, "合计": 108},
      "随机入组人群": {"试验组": 60, "对照组": 58, "合计": 118}
    }

人群标签完全由 LLM 从表格内容自动识别，无一遗漏。
"""

import argparse
import json
import os
import sys
import traceback

_sys_path_add = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
if _sys_path_add not in sys.path:
    sys.path.insert(0, _sys_path_add)
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL

# ═══════════════════════════════════════════════════════════════════════════
# Anthropic SDK tool-loop
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是临床试验数据专家。你的任务是从一张"人群划分表"xlsx 中提取所有分析集和各组人数。

## 步骤

1. 用 bash + python3 openpyxl 读取 xlsx 的全部内容（打印所有行列）
2. 定位表头：这张表列出了多个分析集（如 FAS/PPS/SS/ITT/mITT/随机入组人群/筛选人群 等），每个分析集下面是各组的人数（试验组、对照组、合计等）
3. 关键：**不要预设分析集名称**。从表头单元格中自动发现所有看起来像人群标签的列/行。识别依据：
   - 标准 acronym：FAS, PPS, SS, ITT, mITT（大小写不敏感）
   - 中文人群名：任何带「人群」「集」「分析集」后缀的标签，如 随机入组人群、筛选人群、ITT人群、SS人群、安全性分析集 等
   - 纯中文描述：如 指示病例
   - 英文全称：Full Analysis Set, Per Protocol Set, Safety Set 等
4. 定位组别：试验组、对照组、合计 等（可能在第一列、第一行、或其他位置，按表格实际布局判断）
5. 把每个分析集下各组的人数用 python 逐格提取出来
6. 如果表头布局不常规（如分析集在行方向而不是列方向），也要正确处理

## 输出

用 write_file 工具将结果写入输出路径。JSON 格式：

{
  "FAS": {"试验组": 50, "对照组": 48, "合计": 98},
  "PPS": {"试验组": 47, "对照组": 45, "合计": 92},
  ...
}

## 约束

- 不要跳过任何分析集——表里列了几个就抽几个
- 组别名称保留原文（试验组/对照组/安慰剂组/合计 等）
- 人数必须是从单元格实际读到的数字，不要编造
- 表格可能有多级表头、合并单元格，仔细处理"""


def extract_baseline_with_llm(xlsx_path: str, output_path: str,
                               api_key: str = "",
                               api_base: str = LLM_API_BASE,
                               model: str = LLM_MODEL) -> dict:
    """使用 Anthropic SDK tool loop 让 LLM 读 xlsx → 抽 baseline。"""

    if not api_key:
        api_key = LLM_API_KEY

    try:
        import anthropic
    except ImportError:
        raise SystemExit("请安装 anthropic SDK: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key, base_url=api_base, timeout=120, max_retries=3)

    # 工作目录设为 xlsx 所在目录，方便 LLM 相对路径访问
    work_dir = os.path.dirname(os.path.abspath(xlsx_path)) or "."
    xlsx_basename = os.path.basename(xlsx_path)

    tools = [
        {
            "name": "bash",
            "description": "执行 shell 命令。可用 python3 + openpyxl 读取 xlsx。工作目录已设为表格所在目录。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"}
                },
                "required": ["command"],
            },
        },
        {
            "name": "write_file",
            "description": "将 baseline JSON 写入输出文件。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "输出文件路径（绝对路径）"},
                    "content": {"type": "string", "description": "JSON 字符串"}
                },
                "required": ["path", "content"],
            },
        },
    ]

    user_prompt = f"""请从以下人群划分表 xlsx 中提取所有分析集和各组人数，写入 baseline.json。

表格文件: {xlsx_basename}
工作目录: {work_dir}
输出路径: {output_path}

先打印表格全部内容，然后逐分析集提取人数。"""

    messages = [{"role": "user", "content": user_prompt}]
    max_iterations = 20

    for iteration in range(max_iterations):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8192,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
            )
        except Exception as e:
            print(f"  ⚠ API 调用失败 (iteration {iteration}): {e}")
            break

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in (response.content or []):
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input

            if tool_name == "bash":
                import subprocess
                cmd = tool_input.get("command", "")
                print(f"  🔧 LLM 执行: {cmd[:120]}{'...' if len(cmd) > 120 else ''}")
                try:
                    r = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True,
                        timeout=120, cwd=work_dir,
                    )
                    result_text = r.stdout
                    if r.stderr:
                        result_text += "\n[stderr]\n" + r.stderr[:2000]
                    if r.returncode != 0:
                        result_text += f"\n[exit code: {r.returncode}]"
                except subprocess.TimeoutExpired:
                    result_text = "[timeout after 120s]"
                except Exception as exc:
                    result_text = f"[error: {exc}]"

            elif tool_name == "write_file":
                raw = tool_input.get("content", "")
                path = tool_input.get("path", output_path)

                # 尝试解析 JSON
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    import re
                    m = re.search(r'\{.*\}', raw, re.DOTALL)
                    if m:
                        parsed = json.loads(m.group())
                    else:
                        result_text = f"[JSON 解析失败] 原始内容前200字符: {raw[:200]}"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })
                        continue

                os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(parsed, f, ensure_ascii=False, indent=2)

                sets = "、".join(f"{s}({len(parsed[s])}组)" for s in parsed)
                result_text = f"✅ baseline.json 已写入 {path}\n覆盖分析集: {sets}\n内容:\n{json.dumps(parsed, ensure_ascii=False, indent=2)}"
                print(f"  ✅ {result_text.split(chr(10))[0]}")

            else:
                result_text = f"[未知工具: {tool_name}]"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text[:8000],
            })

        if not tool_results:
            break

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # 检查产出
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            baseline = json.load(f)
        print(f"\n✅ baseline.json 已生成 → {output_path}")
        print(f"   分析集: {'、'.join(baseline.keys())}")
        return baseline
    else:
        print(f"\n❌ LLM 未生成 baseline.json，请检查上述日志")
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="从人群划分表 xlsx 抽出 baseline.json — LLM 自动识别所有人群标签",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python3 extract_baseline.py 人群划分表.xlsx --api-key sk-xxx
    python3 extract_baseline.py 人群划分表.xlsx --api-key sk-xxx --out tables_output/baseline.json
    ANTHROPIC_AUTH_TOKEN=sk-xxx python3 extract_baseline.py 人群划分表.xlsx
        """,
    )
    ap.add_argument("xlsx", help="人群划分表 xlsx 路径")
    ap.add_argument("--out", default="tables_output/baseline.json",
                    help="输出 baseline.json 路径（默认 tables_output/baseline.json）")
    ap.add_argument("--api-key", default="",
                    help="Anthropic API key（优先于环境变量 ANTHROPIC_AUTH_TOKEN）")
    ap.add_argument("--api-base", default=LLM_API_BASE,
                    help="API base URL")
    ap.add_argument("--model", default=LLM_MODEL,
                    help="模型名称")
    args = ap.parse_args()

    if not os.path.exists(args.xlsx):
        sys.exit(f"错误：文件不存在 {args.xlsx}")

    extract_baseline_with_llm(
        xlsx_path=args.xlsx,
        output_path=os.path.abspath(args.out),
        api_key=args.api_key,
        api_base=args.api_base,
        model=args.model,
    )


if __name__ == "__main__":
    main()
