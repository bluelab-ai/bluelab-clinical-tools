#!/usr/bin/env python3
"""
三线表格式修复工具
==================
检查并修复 Word 表格的边框，确保符合三线表格式：
- 表头行：顶部有线 + 底部有线
- 数据行：无边框
- 最后一行：底部有线

用法:
    python -m scripts.phase2.fix_three_line_table <docx文件路径>
"""

import sys
import os
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def set_cell_border(cell, position, val="single", sz="4"):
    """设置单元格边框"""
    tc = cell._tc
    tcPr = tc.find(qn('w:tcPr'))
    if tcPr is None:
        tcPr = OxmlElement('w:tcPr')
        tc.insert(0, tcPr)

    tcBorders = tcPr.find(qn('w:tcBorders'))
    if tcBorders is None:
        tcBorders = OxmlElement('w:tcBorders')
        tcPr.append(tcBorders)

    # 找到或创建对应的边框元素
    border = tcBorders.find(qn(f'w:{position}'))
    if border is None:
        border = OxmlElement(f'w:{position}')
        tcBorders.append(border)

    if val == "nil":
        border.set(qn('w:val'), 'nil')
        border.set(qn('w:sz'), '0')
        border.set(qn('w:space'), '0')
        border.set(qn('w:color'), 'auto')
    else:
        border.set(qn('w:val'), val)
        border.set(qn('w:sz'), sz)
        border.set(qn('w:space'), '0')
        border.set(qn('w:color'), 'auto')


def clear_cell_borders(cell):
    """清除单元格所有边框"""
    for position in ['top', 'left', 'bottom', 'right']:
        set_cell_border(cell, position, val="nil")


def fix_three_line_table(table):
    """
    修复表格为三线表格式
    返回: (修复的行数, 是否有改动)
    """
    rows = table.rows
    if len(rows) < 2:
        return 0, False

    fixed = 0

    for i, row in enumerate(rows):
        for cell in row.cells:
            if i == 0:
                # 表头行：top=single, bottom=single, left=nil, right=nil
                set_cell_border(cell, 'top', val='single', sz='4')
                set_cell_border(cell, 'bottom', val='single', sz='4')
                set_cell_border(cell, 'left', val='nil')
                set_cell_border(cell, 'right', val='nil')
            elif i == len(rows) - 1:
                # 最后一行：bottom=single, 其他nil
                set_cell_border(cell, 'top', val='nil')
                set_cell_border(cell, 'bottom', val='single', sz='4')
                set_cell_border(cell, 'left', val='nil')
                set_cell_border(cell, 'right', val='nil')
            else:
                # 数据行：全部nil
                set_cell_border(cell, 'top', val='nil')
                set_cell_border(cell, 'bottom', val='nil')
                set_cell_border(cell, 'left', val='nil')
                set_cell_border(cell, 'right', val='nil')
            fixed += 1

    return fixed, True


def fix_docx(input_path, output_path=None):
    """修复文档中所有表格的三线表格式"""
    if output_path is None:
        output_path = input_path

    doc = Document(input_path)
    total_fixed = 0

    for i, table in enumerate(doc.tables):
        fixed, changed = fix_three_line_table(table)
        if changed:
            total_fixed += fixed
            print(f"✅ 表格{i+1}: 修复 {fixed} 个单元格", file=sys.stderr)

    if total_fixed > 0:
        doc.save(output_path)
        print(f"✅ 已保存: {output_path}", file=sys.stderr)
    else:
        print("ℹ️ 无需修复", file=sys.stderr)

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python fix_three_line_table.py <docx文件> [输出文件]", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    fix_docx(input_path, output_path)
