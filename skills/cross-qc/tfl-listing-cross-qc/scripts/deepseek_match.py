#!/usr/bin/env python3
"""
DeepSeek API 表格-清单匹配工具

用于关键字匹配无法覆盖的表格，通过 DeepSeek LLM 语义理解进行匹配。

使用:
    # 单表匹配（从 docx 提取清单列表）
    python3 deepseek_match.py --table "表格名" --docx "清单文件.docx"

    # 批量重匹配（读取匹配结果，仅处理余弦相似度兜底的表）
    python3 deepseek_match.py --retry "表格-清单-映射表.json" --docx "清单文件.docx"

    # 单表匹配（手动指定清单列表）
    python3 deepseek_match.py --table "表格名" --listings "清单1: xxx\n清单2: yyy"

环境变量:
    DEEPSEEK_API_KEY    DeepSeek API Key（也可通过 --api-key 传入）
"""

import argparse
import os
import sys
import re
import json
from openai import OpenAI

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"

MATCH_PROMPT = """你是一个临床试验数据管理专家。你的任务是：根据表格名称的语义，从下方清单列表中找出最匹配的一个清单。

表格名称：{table_name}

清单列表：
{listings_text}

请仔细分析表格名称的核心主题（忽略人群标签如FAS/PPS/SS、时间/访视描述如"术后""筛选期"等干扰信息），在清单列表中找到语义最匹配的清单。

请只返回最匹配的清单编号（整数），不要返回任何其他内容。
如果确实无法确定匹配哪个清单，请返回 0。

编号："""


def extract_listings_from_docx(path):
    """从清单 docx 提取清单列表（复用 match_tables_listings 的提取函数）"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from match_tables_listings import extract_listings_with_variables
    listings = extract_listings_with_variables(path)
    return {l['num']: l for l in listings}


def build_listings_text(listings_dict):
    """构建清单列表文本"""
    lines = []
    for num in sorted(listings_dict.keys()):
        l = listings_dict[num]
        lines.append(f"清单{num}: {l['title']}")
    return '\n'.join(lines)


def match_single(table_name, listings_dict, api_key=None):
    """用 DeepSeek API 匹配单个表格到清单"""
    key = api_key or API_KEY
    if not key:
        print("错误: 未设置 DEEPSEEK_API_KEY 环境变量，也未通过 --api-key 传入")
        sys.exit(1)

    client = OpenAI(api_key=key, base_url=BASE_URL)
    listings_text = build_listings_text(listings_dict)
    prompt = MATCH_PROMPT.format(table_name=table_name, listings_text=listings_text)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=10,
    )

    raw = response.choices[0].message.content.strip()
    # 提取第一个整数
    m = re.search(r'\d+', raw)
    if m:
        num = int(m.group(0))
        if num in listings_dict:
            return num, listings_dict[num]['title']
        elif num == 0:
            return None, f"无法确定（API 返回: {raw}）"
        else:
            return None, f"编号 {num} 不在清单列表中（API 返回: {raw}）"
    else:
        return None, f"无法解析 API 返回: {raw}"


def retry_cosine_matches(json_path, listings_dict, api_key=None):
    """读取匹配结果 JSON，对余弦相似度兜底的表重新用 DeepSeek 匹配"""
    import json
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for entry in data:
        if entry['匹配方法'] == '余弦相似度匹配':
            table_name = entry['表格名称']
            print(f"\n重匹配: {table_name}")
            num, matched = match_single(table_name, listings_dict, api_key)
            if num is not None and num in listings_dict:
                l = listings_dict[num]
                entry['最佳匹配'] = {
                    "清单编号": l['num'],
                    "清单名称": l['title'],
                    "清单人群": l.get('population', '-'),
                }
                entry['匹配方法'] = "DeepSeek匹配"
                entry['是否需要人工审核'] = "是"
                print(f"  原匹配: 清单{entry['最佳匹配']['清单编号']} {entry['最佳匹配']['清单名称']}")
                print(f"  新匹配: 清单{l['num']}: {l['title']}")
            else:
                print(f"  匹配失败: {matched}")

    return data


def main():
    parser = argparse.ArgumentParser(description="DeepSeek API 表格-清单匹配工具")
    parser.add_argument('--table', type=str, help='要匹配的表格名称')
    parser.add_argument('--docx', type=str, help='清单 docx 文件路径')
    parser.add_argument('--listings', type=str, help='清单列表文本，每行格式: 清单X: 名称')
    parser.add_argument('--retry', type=str, help='批量重匹配：现有的表格-清单-映射表.json 路径')
    parser.add_argument('--api-key', type=str, help='DeepSeek API Key（优先于环境变量）')
    parser.add_argument('--output', type=str, help='输出文件路径（仅 --retry 模式，默认覆盖原 JSON 文件）')
    args = parser.parse_args()

    api_key = args.api_key or API_KEY

    # 解析清单列表
    listings_dict = {}
    if args.docx:
        listings_dict = extract_listings_from_docx(args.docx)
        print(f"从 docx 提取到 {len(listings_dict)} 个清单")
    elif args.listings:
        for line in args.listings.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            m = re.match(r'清单\s*(\d+)\s*[:：]\s*(.+)', line)
            if m:
                num = int(m.group(1))
                name = m.group(2).strip()
                listings_dict[num] = {'num': num, 'title': name}
        print(f"从参数解析到 {len(listings_dict)} 个清单")

    if not listings_dict:
        print("错误: 未提供清单列表，请使用 --docx 或 --listings 参数")
        sys.exit(1)

    if args.retry:
        # 批量重匹配模式
        results = retry_cosine_matches(args.retry, listings_dict, api_key)
        output_path = args.output or args.retry

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        retried = sum(1 for r in results if r['匹配方法'] == 'DeepSeek匹配')
        print(f"\n已写入: {output_path}")
        print(f"DeepSeek 重匹配: {retried} 对")

        # 同时输出 JSON
        json_path = output_path.rsplit('.', 1)[0] + '.json' if '.' in output_path else output_path + '.json'
        json_output = []
        for i, cols in enumerate(results):
            table_name, table_pop, listing_label, listing_pop, method, review = cols
            m = re.match(r'清单(\d+):\s*(.+)', listing_label)
            listing_num = int(m.group(1)) if m else None
            listing_name = m.group(2) if m else listing_label
            json_output.append({
                "表格编号": i,
                "表格名称": table_name,
                "表格人群": table_pop,
                "最佳匹配": {
                    "清单编号": listing_num,
                    "清单名称": listing_name,
                    "清单人群": listing_pop,
                },
                "匹配方法": method,
                "是否需要人工审核": review,
            })
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_output, f, ensure_ascii=False, indent=2)
        print(f"已写入 JSON: {json_path}")

    elif args.table:
        # 单表匹配模式
        num, matched = match_single(args.table, listings_dict, api_key)
        if num:
            print(f"匹配成功: 清单{num}: {matched}")
        else:
            print(f"匹配失败: {matched}")
    else:
        print("错误: 请指定 --table 或 --retry 参数")
        sys.exit(1)


if __name__ == "__main__":
    main()
