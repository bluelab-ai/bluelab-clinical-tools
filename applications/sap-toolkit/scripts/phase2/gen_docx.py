#!/usr/bin/env python3
"""
通用生成脚本
根据模板代码加载对应的 gen_docx.py 并执行
"""

import json
import os
import sys
import importlib.util
from pathlib import Path

# 模板代码目录
CODE_DIR = os.path.join(os.path.dirname(__file__), "模板代码")


def load_module(module_path):
    """动态加载 Python 模块"""
    spec = importlib.util.spec_from_file_location("module", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_template_code(data_path):
    """从数据文件名推断模板代码"""
    filename = os.path.basename(data_path)
    # 移除 .json 后缀
    table_name = filename.replace(".json", "")
    return table_name


def gen_docx(template_code, data_path, output_path=None):
    """
    生成 Word 文档

    参数:
        template_code: 模板代码（如 F_G2_RR）
        data_path: 填充结果 JSON 文件路径
        output_path: 输出 Word 文件路径（默认为数据文件同目录下的 输出结果.docx）
    """
    # 检查模板代码目录是否存在
    template_dir = os.path.join(CODE_DIR, template_code)
    if not os.path.exists(template_dir):
        return {"ok": False, "error": f"模板代码目录不存在: {template_code}"}

    # 检查 gen_docx.py 是否存在
    gen_script = os.path.join(template_dir, "gen_docx.py")
    if not os.path.exists(gen_script):
        return {"ok": False, "error": f"gen_docx.py 不存在: {template_code}"}

    # 检查数据文件是否存在
    if not os.path.exists(data_path):
        return {"ok": False, "error": f"数据文件不存在: {data_path}"}

    try:
        # 加载 gen_docx 模块
        module = load_module(gen_script)

        # 读取数据
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 调用 generate_docx 函数
        if hasattr(module, "generate_docx"):
            # 确定输出路径
            if output_path is None:
                import tempfile
                output_path = os.path.join(tempfile.gettempdir(), f"输出结果_{template_code}.docx")

            module.generate_docx(data, output_path)
        elif hasattr(module, "build_docx"):
            # 有些模块使用 build_docx 函数
            if output_path is None:
                import tempfile
                output_path = os.path.join(tempfile.gettempdir(), f"输出结果_{template_code}.docx")

            doc = module.build_docx(data)
            doc.save(output_path)
        else:
            return {"ok": False, "error": f"gen_docx.py 中没有 generate_docx 或 build_docx 函数"}

        return {"ok": True, "output_path": output_path}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def gen_docx_from_data(data_path, output_path=None):
    """
    从数据文件推断模板代码并生成 Word

    参数:
        data_path: 填充结果 JSON 文件路径
        output_path: 输出 Word 文件路径
    """
    template_code = get_template_code(data_path)
    return gen_docx(template_code, data_path, output_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="通用生成脚本")
    parser.add_argument("template_code", help="模板代码（如 F_G2_RR）")
    parser.add_argument("data_path", help="填充结果 JSON 文件路径")
    parser.add_argument("-o", "--output", help="输出 Word 文件路径", default=None)

    args = parser.parse_args()

    result = gen_docx(args.template_code, args.data_path, args.output)

    if result["ok"]:
        print(f"✓ 生成完成: {result['output_path']}")
    else:
        print(f"✗ 生成失败: {result['error']}", file=sys.stderr)
        sys.exit(1)
