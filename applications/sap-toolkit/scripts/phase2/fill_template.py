#!/usr/bin/env python3
"""
通用填充脚本
根据模板代码加载对应的 fill_template.py 并执行
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


def fill_template(template_code, data_path, output_path=None):
    """
    填充模板

    参数:
        template_code: 模板代码（如 F_G2_RR）
        data_path: 数据文件路径
        output_path: 输出文件路径（默认为数据文件同目录下的 填充结果.json）
    """
    # 检查模板代码目录是否存在
    template_dir = os.path.join(CODE_DIR, template_code)
    if not os.path.exists(template_dir):
        return {"ok": False, "error": f"模板代码目录不存在: {template_code}"}

    # 检查 fill_template.py 是否存在
    fill_script = os.path.join(template_dir, "fill_template.py")
    if not os.path.exists(fill_script):
        return {"ok": False, "error": f"fill_template.py 不存在: {template_code}"}

    # 检查语义 JSON 是否存在
    semantic_path = os.path.join(template_dir, f"{template_code}.json")
    if not os.path.exists(semantic_path):
        return {"ok": False, "error": f"语义 JSON 不存在: {template_code}"}

    # 检查数据文件是否存在
    if not os.path.exists(data_path):
        return {"ok": False, "error": f"数据文件不存在: {data_path}"}

    try:
        # 加载 fill_template 模块
        module = load_module(fill_script)

        # 读取数据
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 读取语义 JSON
        with open(semantic_path, "r", encoding="utf-8") as f:
            semantic = json.load(f)

        # 调用 fill_template 函数
        if hasattr(module, "fill_template"):
            # 获取 projects 列表，兼容 endpoint 格式
            projects = data.get("projects", [])
            if not projects and "endpoint" in data:
                projects = [data["endpoint"]]

            # 检查函数签名，看是否需要 visits 参数
            import inspect
            sig = inspect.signature(module.fill_template)
            params = list(sig.parameters.keys())

            if "visits" in params:
                # 需要 visits 参数
                visits = data.get("visits", ["筛选期", "治疗期", "30天随访"])
                result = module.fill_template(semantic, projects, visits)
            else:
                # 不需要 visits 参数
                result = module.fill_template(semantic, projects)
        else:
            return {"ok": False, "error": f"fill_template.py 中没有 fill_template 函数"}

        # 确定输出路径（默认输出到临时目录，使用唯一ID避免并行冲突）
        if output_path is None:
            import tempfile, uuid
            unique_id = uuid.uuid4().hex[:8]
            output_path = os.path.join(tempfile.gettempdir(), f"填充结果_{template_code}_{unique_id}.json")

        # 保存结果
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return {"ok": True, "output_path": output_path}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def fill_template_from_data(data_path, output_path=None):
    """
    从数据文件推断模板代码并填充

    参数:
        data_path: 数据文件路径
        output_path: 输出文件路径
    """
    template_code = get_template_code(data_path)
    return fill_template(template_code, data_path, output_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="通用填充脚本")
    parser.add_argument("template_code", help="模板代码（如 F_G2_RR）")
    parser.add_argument("data_path", help="数据文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径", default=None)

    args = parser.parse_args()

    result = fill_template(args.template_code, args.data_path, args.output)

    if result["ok"]:
        print(f"✓ 填充完成: {result['output_path']}")
    else:
        print(f"✗ 填充失败: {result['error']}", file=sys.stderr)
        sys.exit(1)
