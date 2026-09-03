#!/usr/bin/env python3
"""
F_G1_QUANSUB_N_N 模板演示脚本
支持自定义亚组和指标数据
"""

import os
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

def main():
    print("=" * 60)
    print("F_G1_QUANSUB_N_N 模板演示")
    print("定量指标亚组描述表（单组-无缺失）")
    print("=" * 60)
    print()

    # 示例数据配置
    demo_data = {
        "table_name": "生命体征检查",
        "subgroups": ["男性", "女性"],
        "projects": [
            {"name": "收缩压", "unit": "mmHg"},
            {"name": "舒张压", "unit": "mmHg"},
            {"name": "心率", "unit": "次/分"}
        ]
    }

    print("📊 示例数据配置:")
    print(f"   表格名称: {demo_data['table_name']}")
    print(f"   亚组: {', '.join(demo_data['subgroups'])}")
    print(f"   指标:")
    for proj in demo_data['projects']:
        print(f"     - {proj['name']} ({proj['unit']})")
    print()

    # 保存示例数据
    data_path = os.path.join(SCRIPT_DIR, "演示数据.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(demo_data, f, ensure_ascii=False, indent=2)
    print(f"✓ 示例数据已保存: {data_path}")
    print()

    # 运行数据填充
    print("🔄 正在进行数据填充...")
    from fill_template import fill_template, load_json

    semantic_path = os.path.join(SCRIPT_DIR, "F_G1_QUANSUB_N_N.json")
    semantic = load_json(semantic_path)
    filled_data = fill_template(semantic, demo_data["projects"], demo_data["subgroups"])

    # 保存填充结果
    result_path = os.path.join(SCRIPT_DIR, "演示结果.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(filled_data, f, ensure_ascii=False, indent=2)
    print(f"✓ 填充完成: {result_path}")
    print()

    # 生成Word文档
    print("📄 正在生成Word文档...")
    from gen_docx import generate_docx

    output_path = os.path.join(SCRIPT_DIR, "演示输出.docx")
    generate_docx(filled_data, output_path)

    file_size = os.path.getsize(output_path)
    print(f"✓ Word文档已生成: {output_path}")
    print(f"   文件大小: {file_size:,} 字节")
    print()

    # 统计信息
    indicator_count = len(filled_data.get("indicators", []))
    subgroup_count = len(demo_data["subgroups"])
    total_rows = indicator_count * subgroup_count * 5  # 每个指标每个亚组5行

    print("📊 统计信息:")
    print(f"   指标数量: {indicator_count}")
    print(f"   亚组数量: {subgroup_count}")
    print(f"   总行数: {total_rows}")
    print(f"   表格列数: 4 (亚组 | 项目 | 指标 | 结果)")
    print()

    # 打开文档
    print("📖 正在打开Word文档...")
    os.system(f'open "{output_path}"')
    print()

    print("🎉 演示完成！")
    print()
    print("提示:")
    print("  1. 可以修改 演示数据.json 文件来自定义数据")
    print("  2. 重新运行本脚本即可生成新的表格")
    print("  3. 生成的Word文档使用三线表格式，符合学术规范")

if __name__ == "__main__":
    main()
