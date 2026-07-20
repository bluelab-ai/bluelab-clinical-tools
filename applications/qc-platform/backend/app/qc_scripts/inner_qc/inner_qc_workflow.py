"""
Inner Table QC Workflow
========================
LangGraph + Anthropic SDK 混合架构 — 临床试验表格表内一致性核查管线。

架构:
  LangGraph:     Phase 1 → 2 → 3 → 4 → 5 → 6  确定性管线 + 阶段门控
  Anthropic SDK: Phase 4 内部并行 LLM 调用 (ThreadPoolExecutor + tool-use loop)

运行:
    python inner_qc_workflow.py \
        --api-key sk-xxx \
        --table 表格附件.docx \
        --project /path/to/project

    可选:
        --baseline-xlsx 人群划分表.xlsx   (外部人数基准)
        --baseline-json baseline.json     (已抽好的基准 JSON)

    默认使用 DeepSeek Anthropic 兼容端点:
      --api-base https://api.deepseek.com/anthropic
      --model deepseek-v4-pro

依赖:
    pip install langgraph langchain openpyxl anthropic
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict, cast
from collections.abc import Sequence

import operator

import anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed

_sys_path_add = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
if _sys_path_add not in sys.path:
    sys.path.insert(0, _sys_path_add)
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver


# ═══════════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════════

# 表型 → 规则文档 映射（classify_and_rename.py 输出的类型字段）
TYPE_TO_RULE = {
    "标准定性定量表": "标准定性定量表.md",
    "事件表": "事件表.md",
    "交叉表": "交叉表.md",
    "病例分布表": "病例分布表.md",
    "入组病例表": "入组病例表.md",
    "人群划分表": "人群划分表.md",
    "协方差": "协方差表.md",
    "other": None,  # 无规则文档，subagent 标"待人工"
}

# Phase 3 外部核查适用的表型（这些表的 §2.4 在 Phase 3 由外部 subagent 处理）
EXTERNAL_QC_TYPES = ("人群划分表", "病例分布表", "入组病例表")


class TableInfo(TypedDict):
    """单张表的信息"""
    idx: int                       # 编号（文件名前导数字）
    filename: str                  # 完整文件名
    table_type: str                # 表型（来自 classify_and_rename）
    table_title: str               # 表格标题
    analysis_set: str              # 人群类型 FAS|PPS|SS|随机化人群|-
    xlsx_path: str                 # 绝对路径


class InnerQCState(TypedDict, total=False):
    """贯穿全部 Phase 的全局状态"""

    # ── CLI 输入 ──
    table_input: str               # 表格附件路径 (docx/pdf)
    project_dir: str               # 项目工作目录
    skill_dir: str                 # inner_qc 资源目录
    model: str                     # LLM 模型名
    api_key: str                   # API key（直接传参）
    api_base: str                  # API base URL
    baseline_xlsx: str             # 外部人群划分表 xlsx（可选，旧参数，仍支持）
    baseline_json: str             # 已有 baseline.json（可选）
    external_population: str       # 外部人群划分表 xlsx（Phase 3 外部核查用）
    external_randomization: str    # 外部随机表 xlsx（Phase 3 外部核查用）
    max_pairs: int                 # 最多 QC 表数（0=全部）
    max_retries: int               # 缺失结果最大重试次数（默认2）
    no_subagent: bool              # 是否跳过 Phase 5 subagent 核查
    skip_cleanup: bool             # 是否跳过 Phase 7 清理（调试用）

    # ── Phase 1 产出 ──
    tables_output_dir: str         # tables_output/ 目录
    tables_meta_path: str          # tables_meta.json 路径（docx 模式）

    # ── Phase 2 产出 ──
    classified_tables: list[TableInfo]  # 分类重命名后的表列表

    # ── Phase 3 产出（外部核查，可选）──
    external_ref_path: str         # tables_output/external_ref.json 路径
    skip_external_qc: bool         # 是否跳过 Phase 3（无外部表时自动跳过）
    phase3_table_indices: list[int]  # Phase 3 已处理的表编号（Phase 5 需跳过）

    # ── Phase 4 产出 ──
    baseline_path: str             # tables_output/baseline.json 路径
    population_table_idx: int      # TFL 内人群划分表编号（Phase 4 需跳过），0=无

    # ── Phase 5 调度 ──
    qc_tables: list[TableInfo]     # 需要 QC 的表（排除已处理的人群划分表+Phase3表）
    total_tables: int              # QC 表总数
    qc_output_dir: str             # qc_output/ 目录
    # 收集各表报告路径；operator.add 自动 append
    qc_report_paths: Annotated[list[str], operator.add]

    # ── Phase 6 产出 ──
    merged_report_path: str        # 总体QC报告.md
    viewer_html_path: str          # QC可视化报告.html

    # ── 控制 ──
    current_phase: str             # init | phase1_done | phase2_done | ...
    error_message: str             # 错误信息


# ═══════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_skill_dir() -> str:
    """自动解析 inner_qc 资源目录（与本脚本同目录）"""
    env = os.environ.get("INNER_QC_SKILL_DIR")
    if env:
        return env
    candidate = Path(__file__).parent
    if candidate.exists():
        return str(candidate.resolve())
    raise FileNotFoundError(
        "无法自动定位 inner_qc 目录，请设置环境变量 INNER_QC_SKILL_DIR"
    )


def _run_script(script_path: str, args: list[str], cwd: str | None = None,
                ) -> subprocess.CompletedProcess:
    """运行 Python 脚本，输出实时打印，返回结果"""
    cmd = ["python3", script_path] + args
    print(f"  → {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        out = result.stdout.strip()
        if len(out) > 2000:
            out = out[:2000] + "\n  ... (输出已截断)"
        print(f"  stdout:\n{out}")
    if result.stderr:
        err = result.stderr.strip()
        if len(err) > 1000:
            err = err[:1000] + "\n  ... (stderr 已截断)"
        print(f"  stderr:\n{err}")
    return result


def _create_anthropic_client(state: InnerQCState) -> anthropic.Anthropic:
    """根据 state 中的配置构建 Anthropic SDK 客户端"""
    api_key = state.get("api_key", "")
    api_base = state.get("api_base", LLM_API_BASE)

    if not api_key:
        raise ValueError(
            "缺少 API key。请通过 --api-key 参数传入。\n"
            "示例: --api-key sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        )

    return anthropic.Anthropic(
        api_key=api_key,
        base_url=api_base,
        timeout=300,
        max_retries=3,
    )


def _parse_table_info_from_filename(filename: str, tables_dir: str) -> TableInfo | None:
    """从 classify_and_rename 输出的文件名解析表信息。

    文件名格式: 编号-类型-标题-人群类型.xlsx
    例: 03-标准定性定量表-表 14.4.1 疗效分级-FAS.xlsx
    """
    if not filename.endswith(".xlsx"):
        return None

    stem = filename[:-5]  # 去掉 .xlsx
    parts = stem.split("-", 3)  # 最多分 4 段
    if len(parts) < 4:
        return None

    idx_str, table_type, title, analysis_set = parts
    try:
        idx = int(idx_str)
    except ValueError:
        return None

    return TableInfo(
        idx=idx,
        filename=filename,
        table_type=table_type,
        table_title=title,
        analysis_set=analysis_set,
        xlsx_path=os.path.join(tables_dir, filename),
    )


def _scan_classified_tables(tables_dir: str) -> list[TableInfo]:
    """扫描 tables_output 中分类重命名后的 xlsx，返回 TableInfo 列表"""
    tables: list[TableInfo] = []
    if not os.path.isdir(tables_dir):
        return tables

    for fname in sorted(os.listdir(tables_dir)):
        info = _parse_table_info_from_filename(fname, tables_dir)
        if info:
            tables.append(info)

    return tables


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1: 提取表格
# ═══════════════════════════════════════════════════════════════════════════

def phase1_extract(state: InnerQCState) -> dict:
    """从 DOCX/PDF 提取表格为逐张 Excel，输出到 tables_output/"""
    print("\n" + "=" * 60)
    print("📊 Phase 1: 提取表格到 Excel")
    print("=" * 60)

    skill = state["skill_dir"]
    table_input = state["table_input"]
    project = state["project_dir"]
    tables_out = os.path.join(project, "tables_output")
    # 重跑时清空旧产出，避免文件累计翻倍
    if os.path.isdir(tables_out):
        for f in os.listdir(tables_out):
            if f.endswith(".xlsx") or f == "tables_meta.json":
                os.unlink(os.path.join(tables_out, f))
    os.makedirs(tables_out, exist_ok=True)

    is_pdf = table_input.lower().endswith(".pdf")
    script_name = "extract_tables_pdf.py" if is_pdf else "extract_tables.py"
    script_path = os.path.join(skill, script_name)

    result = _run_script(script_path, [table_input, "--out", tables_out])

    if result.returncode != 0:
        return {"error_message": f"Phase 1 提取失败: {result.stderr}", "current_phase": "error"}

    # 检查产出
    xlsx_count = len([f for f in os.listdir(tables_out) if f.endswith(".xlsx")])
    if xlsx_count == 0:
        return {"error_message": "Phase 1 未提取到任何表格", "current_phase": "error"}

    meta_path = os.path.join(tables_out, "tables_meta.json")

    print(f"  提取表格: {xlsx_count} 张")
    if os.path.exists(meta_path):
        print(f"  元数据: {meta_path}")
    print("✅ Phase 1 完成")

    return {
        "tables_output_dir": tables_out,
        "tables_meta_path": meta_path if os.path.exists(meta_path) else "",
        "current_phase": "phase1_done",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: 表型分类与重命名
# ═══════════════════════════════════════════════════════════════════════════

def phase2_classify(state: InnerQCState) -> dict:
    """调用 classify_and_rename.py 判型并重命名"""
    print("\n" + "=" * 60)
    print("🏷️  Phase 2: 表型分类与重命名")
    print("=" * 60)

    skill = state["skill_dir"]
    tables_dir = state["tables_output_dir"]
    script_path = os.path.join(skill, "classify_and_rename.py")

    result = _run_script(script_path, [tables_dir])

    if result.returncode != 0:
        return {"error_message": f"Phase 2 分类失败: {result.stderr}", "current_phase": "error"}

    # 扫描分类后的表
    tables = _scan_classified_tables(tables_dir)
    if not tables:
        return {"error_message": "Phase 2 未生成任何分类表", "current_phase": "error"}

    # 统计
    type_counts: dict[str, int] = {}
    for t in tables:
        type_counts[t["table_type"]] = type_counts.get(t["table_type"], 0) + 1

    print(f"  分类表数: {len(tables)}")
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}")
    if "other" in type_counts:
        print(f"  ⚠️  {type_counts['other']} 张 other 表将标为「待人工」")

    print("✅ Phase 2 完成")

    return {
        "classified_tables": tables,
        "current_phase": "phase2_done",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3: 外部核查（可选 — 需用户上传外部人群划分表/随机表）
# ═══════════════════════════════════════════════════════════════════════════

def _build_external_qc_system_prompt(tbl: TableInfo, state: InnerQCState) -> str:
    """为 Phase 3 外部核查构建 system prompt（只跑 §2.4 R-050~R-053）。"""
    skill = state["skill_dir"]
    tables_dir = state["tables_output_dir"]
    qc_output_dir = state["qc_output_dir"]
    external_ref_path = state.get("external_ref_path", "")

    rule_doc_filename = TYPE_TO_RULE.get(tbl["table_type"])
    if rule_doc_filename:
        rule_doc_path = os.path.join(skill, "assets", rule_doc_filename)
        try:
            with open(rule_doc_path) as f:
                rule_content = f.read()
        except Exception:
            rule_content = "（规则文档不可用）"
    else:
        rule_content = "（该表型无对应规则文档）"

    template_content = ""
    template_path = os.path.join(skill, "reference", "subagent_output_template.md")
    try:
        with open(template_path) as f:
            template_content = f.read()
    except Exception:
        pass

    return f"""你是一个临床试验方面的高级统计师，正在执行 **Phase 3 外部核查**——用外部权威数据核查本表分中心/人群相关字段。

## 本表信息
- 表编号: {tbl['idx']}
- 表型: {tbl['table_type']}
- 表格文件: {tables_dir}/{tbl['filename']}
- 规则文档: assets/{rule_doc_filename}（**只读 §2.4 "用外部参照的规则片段"这一段**）
- 外部参照: {external_ref_path}
- 共享核查库: `{skill}/qc_lib.py`（`import sys; sys.path.insert(0, "{skill}"); from qc_lib import ...`）

## 表型规则文档（本表需执行的 QC 规则 + 代码模板）
{rule_content}

## 输出模板
{template_content}

## 步骤
1. 加载 external_ref.json
2. 读 xlsx，定位分中心行 / 分析集列 / 剔除原因行等（这是你的语义工作）
3. 按 §2.4 代码模板跑 R-050~R-053（本表适用哪几条就跑哪几条；ext_ref 里没抽到的字段静默跳过）
4. 双产物：
   - JSON: `Issues.to_json("{qc_output_dir}/qc_ext_{tbl['idx']:02d}.json")`
   - MD:  严格按输出模板 write_file 写到 `{qc_output_dir}/qc_ext_{tbl['idx']:02d}.md`

## 纪律
- 输出必须包含四行元数据: `##META_TABLE` / `##META_TYPE` / `##META_ANALYSIS_SET` / `##META_CONCLUSION`（缺一不可，见模板）
- 本阶段**只跑 R-050~R-053**——本表其他内部规则由 Phase 4/5 负责，不在这里重复
- external_ref 里没有的字段 → 静默跳过，不产 Finding，不算"通过"
- 数字对不上 → MAJOR；文本对不上（剔除原因措辞差异）→ MINOR
- 算术一律调 `qc_lib`，不准 LLM 眼算
"""


def phase3_external_qc(state: InnerQCState) -> dict:
    """Phase 3 外部核查：用外部权威表核查 TFL 人群划分表/病例分布表/入组病例表。

    门控：--external-population 或 --external-randomization 至少提供一个才执行，
    都没提供则跳过整个 Phase 3。
    """
    print("\n" + "=" * 60)
    print("🔗 Phase 3: 外部核查（R-050~R-053）")
    print("=" * 60)

    skill = state["skill_dir"]
    project = state["project_dir"]
    tables_dir = state["tables_output_dir"]
    tables = state.get("classified_tables", [])

    ext_pop = state.get("external_population", "")
    ext_rand = state.get("external_randomization", "")

    # 门控：没有任何外部表 → 跳过
    has_pop = bool(ext_pop and os.path.exists(ext_pop))
    has_rand = bool(ext_rand and os.path.exists(ext_rand))

    if not has_pop and not has_rand:
        print("  ⏭️  未提供外部人群划分表/随机表，跳过 Phase 3")
        return {
            "skip_external_qc": True,
            "external_ref_path": "",
            "phase3_table_indices": [],
            "current_phase": "phase3_done",
        }

    # 1. 构建 external_ref.json
    prepare_script = os.path.join(skill, "prepare_external_ref.py")
    ref_out = os.path.join(tables_dir, "external_ref.json")

    if not os.path.exists(prepare_script):
        print("  ⚠️ prepare_external_ref.py 不存在，跳过 Phase 3")
        return {
            "skip_external_qc": True,
            "external_ref_path": "",
            "phase3_table_indices": [],
            "current_phase": "phase3_done",
        }

    args = ["--out", ref_out]
    if has_pop:
        args += ["--population", ext_pop]
    if has_rand:
        args += ["--randomization", ext_rand]

    result = _run_script(prepare_script, args, cwd=project)
    if result.returncode != 0 or not os.path.exists(ref_out):
        print("  ⚠️ prepare_external_ref.py 失败，跳过外部核查")
        return {
            "skip_external_qc": True,
            "external_ref_path": "",
            "phase3_table_indices": [],
            "current_phase": "phase3_done",
        }

    print(f"  ✅ external_ref.json → {ref_out}")

    # 2. 找出 Phase 3 适用的表（人群划分表/病例分布表/入组病例表）
    ext_tables = [t for t in tables if t["table_type"] in EXTERNAL_QC_TYPES]
    if not ext_tables:
        print("  ⏭️  TFL 中没有人群划分表/病例分布表/入组病例表，跳过外部核查")
        return {
            "skip_external_qc": False,
            "external_ref_path": ref_out,
            "phase3_table_indices": [],
            "current_phase": "phase3_done",
        }

    print(f"  📌 Phase 3 待核查: {len(ext_tables)} 张表")

    # 3. 更新 state 以便 subagent 能访问 external_ref_path
    state["external_ref_path"] = ref_out
    state["qc_output_dir"] = os.path.join(project, "qc_output")
    os.makedirs(state["qc_output_dir"], exist_ok=True)

    # 4. 为每张表构建 prompt 并并行执行
    if state.get("no_subagent"):
        print("  ⏭️  跳过 subagent 核查 (--no-subagent)")
        return {
            "skip_external_qc": False,
            "external_ref_path": ref_out,
            "phase3_table_indices": [t["idx"] for t in ext_tables],
            "current_phase": "phase3_done",
        }

    prompt_specs = []
    for tbl in ext_tables:
        system_prompt = _build_external_qc_system_prompt(tbl, state)
        prompt_specs.append({"table": tbl, "system_prompt": system_prompt, "file_prefix": "qc_ext"})

    total = len(prompt_specs)
    max_workers = min(total, 8)
    phase3_indices: list[int] = []
    qc_report_paths: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_run_single_table_qc, spec, state): spec["table"]["idx"]
            for spec in prompt_specs
        }
        completed = 0
        for future in as_completed(future_map):
            tidx = future_map[future]
            try:
                idx, md_path, json_path = future.result()
            except Exception as e:
                print(f"  ❌ 表 {tidx:02d} (Phase 3): 异常退出 ({e})")
                completed += 1
                continue
            completed += 1
            if md_path or json_path:
                phase3_indices.append(tidx)
                if md_path:
                    qc_report_paths.append(md_path)
            else:
                print(f"  ⚠️ 表 {tidx:02d} (Phase 3): 未生成报告")
            print(f"  进度: {completed}/{total}")

    # 重试失败的
    max_retries = state.get("max_retries", 2)
    failed = [t["idx"] for t in ext_tables if t["idx"] not in phase3_indices]
    for retry in range(max_retries):
        if not failed:
            break
        print(f"\n  🔄 Phase 3 重试 {retry + 1}/{max_retries}: {len(failed)} 张表...")
        retry_specs = [s for s in prompt_specs if s["table"]["idx"] in failed]
        still_failed: list[int] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            retry_futures = {
                executor.submit(_run_single_table_qc, spec, state): spec["table"]["idx"]
                for spec in retry_specs
            }
            for future in as_completed(retry_futures):
                tidx = retry_futures[future]
                try:
                    idx, md_path, json_path = future.result()
                except Exception:
                    still_failed.append(tidx)
                    continue
                if md_path or json_path:
                    phase3_indices.append(tidx)
                    if md_path:
                        qc_report_paths.append(md_path)
                else:
                    still_failed.append(tidx)
        failed = still_failed

    if failed:
        print(f"  ⚠️ Phase 3 最终仍有 {len(failed)} 张表未生成报告: {failed}")

    print(f"✅ Phase 3 完成: {len(phase3_indices)} 张表已外部核查")

    return {
        "skip_external_qc": False,
        "external_ref_path": ref_out,
        "phase3_table_indices": phase3_indices,
        "qc_report_paths": qc_report_paths,
        "current_phase": "phase3_done",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4: 建立人数基准
# ═══════════════════════════════════════════════════════════════════════════

def phase3_baseline(state: InnerQCState) -> dict:
    """Phase 4: 提取人数基准 baseline.json。

    分支:
      A: Phase 3 外部核查已产出 baseline.json → 直接使用
      B: 外部 baseline.json 已提供 → 直接使用
      C: 外部 人群划分表.xlsx 提供 → extract_baseline.py 直抽
      D: TFL 内含人群划分表 → extract_baseline.py 直抽
      E: 都没有 → 跳过，基准类规则静默失效
    """
    print("\n" + "=" * 60)
    print("📏 Phase 4: 建立人数基准")
    print("=" * 60)

    skill = state["skill_dir"]
    project = state["project_dir"]
    tables_dir = state["tables_output_dir"]
    tables = state.get("classified_tables", [])

    baseline_out = os.path.join(tables_dir, "baseline.json")

    # Branch A: 外部 baseline.json 已提供（--baseline-json 参数）
    if state.get("baseline_json"):
        src = state["baseline_json"]
        if os.path.exists(src):
            import shutil
            shutil.copy(src, baseline_out)
            print(f"  ✅ 使用外部 baseline.json: {src}")
            print("✅ Phase 4 完成")
            return {"baseline_path": baseline_out, "population_table_idx": 0,
                    "current_phase": "phase3_done"}
        else:
            print(f"  ⚠️ 外部 baseline.json 不存在: {src}，尝试其他方式...")

    api_key = state.get("api_key", "")
    api_base = state.get("api_base", LLM_API_BASE)
    model = state.get("model", LLM_MODEL)

    # Branch B: 外部 人群划分表.xlsx
    if state.get("baseline_xlsx"):
        xlsx = state["baseline_xlsx"]
        if os.path.exists(xlsx):
            script_path = os.path.join(skill, "extract_baseline.py")
            cmd = [xlsx, "--out", baseline_out, "--api-key", api_key,
                   "--api-base", api_base, "--model", model]
            result = _run_script(script_path, cmd)
            if result.returncode == 0 and os.path.exists(baseline_out):
                print(f"  ✅ 外部人群划分表 → {baseline_out}")
                print("✅ Phase 4 完成")
                return {"baseline_path": baseline_out, "population_table_idx": 0,
                        "current_phase": "phase3_done"}
            else:
                print(f"  ⚠️ extract_baseline.py 失败，尝试 TFL 内人群划分表...")
        else:
            print(f"  ⚠️ 外部人群划分表不存在: {xlsx}")

    # Branch C: 查找 TFL 内人群划分表 → extract_baseline.py 抽数
    pop_tables = [t for t in tables if t["table_type"] == "人群划分表"]
    if pop_tables:
        pop_xlsx = pop_tables[0]["xlsx_path"]
        pop_idx = pop_tables[0]["idx"]
        print(f"  📌 发现 TFL 内人群划分表: 编号 {pop_idx}")
        script_path = os.path.join(skill, "extract_baseline.py")
        cmd = [pop_xlsx, "--out", baseline_out, "--api-key", api_key,
               "--api-base", api_base, "--model", model]
        result = _run_script(script_path, cmd)
        if result.returncode == 0 and os.path.exists(baseline_out):
            print(f"  ✅ TFL 内人群划分表 → {baseline_out}")
            print("✅ Phase 4 完成")
            return {"baseline_path": baseline_out, "population_table_idx": 0,
                    "current_phase": "phase3_done"}
        else:
            print(f"  ⚠️ extract_baseline.py 抽取失败，baseline 不可用，基准类规则将静默跳过")

    else:
        # Branch D: 没有人群划分表
        print("  ⚠️ 未找到人群划分表，基准类规则（R-003/009/028/036）将静默跳过")

    print("✅ Phase 4 完成")
    return {"baseline_path": "", "population_table_idx": 0,
            "current_phase": "phase3_done"}


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5: 逐表 QC（一表一 subagent，并行）
# ═══════════════════════════════════════════════════════════════════════════

def _build_table_system_prompts(tables: list[TableInfo], state: InnerQCState) -> list[dict]:
    """为每张待核查表构建包含 skill 内容的完整 system prompt"""
    skill = state["skill_dir"]
    project = state["project_dir"]
    tables_dir = state["tables_output_dir"]
    qc_output_dir = state["qc_output_dir"]
    baseline_path = state.get("baseline_path", "")

    # 读取共享资源
    def _read_skill_file(path: str, label: str) -> str:
        try:
            with open(path) as f:
                content = f.read()
            if content.startswith("---"):
                end = content.find("---", 3)
                if end != -1:
                    content = content[end + 3:].strip()
            return content
        except Exception:
            return f"（{label} 文件不可用: {path}）"

    template_content = _read_skill_file(
        os.path.join(skill, "reference", "subagent_output_template.md"),
        "subagent_output_template.md",
    )

    prompt_specs: list[dict] = []

    for tbl in tables:
        tidx = tbl["idx"]
        ttype = tbl["table_type"]

        # 读取表型对应的规则文档
        rule_doc_filename = TYPE_TO_RULE.get(ttype)
        if rule_doc_filename:
            rule_doc_path = os.path.join(skill, "assets", rule_doc_filename)
            rule_content = _read_skill_file(rule_doc_path, rule_doc_filename)
        else:
            rule_content = "（该表型无对应规则文档，所有项目标「待人工」）"

        # 基线存在性 — 条件构建
        has_baseline = bool(baseline_path and os.path.exists(baseline_path))
        if has_baseline:
            baseline_note = f"人数基准文件已就绪: `{baseline_path}`"
            baseline_section = f"""---
## 基线核查
- 加载基线：`baseline = json.load(open("{baseline_path}"))`  # 结构: {{"FAS":{{"试验组":N,"对照组":N,"合计":N}},"PPS":{{...}},"SS":{{...}},"ITT":{{...}},"mITT":{{...}}}}
- **N 值一致性**：表头各组 N 和表内合计，用 `check_le` 核对 ≤ baseline 对应分析集人数
- **R-028 张冠李戴**：表题写某分析集但合计人数恰等于另一分析集人数 → MAJOR
- **R-036 表头 ⊆ 表题**：表头出现的 FAS/ITT/mITT/PPS/SS 必须全部包含在表题声明分析集中，否则 → MAJOR
---
"""
            steps_block = f"""## 步骤
1. 完整阅读上方规则文档，理解自然语言规则 + 代码模板（§二）
2. `grid = qc_lib.read_grid("{tables_dir}/{tbl['filename']}")` 读取 xlsx；语义定位表头行、分组列、数据区
3. 加载基线：`baseline = json.load(open("{baseline_path}"))`
4. 参考规则文档代码模板 + 上方基线核查，结合本表实际表头位置编写完整 QC 脚本，用 Bash 执行
5. 双产物（同一轮内完成）："""
        else:
            baseline_note = "无人数基准文件，基准类规则（R-003/009/028/036）静默跳过。"
            baseline_section = ""
            steps_block = f"""## 步骤
1. 完整阅读上方规则文档，理解自然语言规则 + 代码模板（§二）
2. `grid = qc_lib.read_grid("{tables_dir}/{tbl['filename']}")` 读取 xlsx；语义定位表头行、分组列、数据区
3. 参考规则文档代码模板，结合本表实际表头位置编写完整 QC 脚本，用 Bash 执行
4. 双产物（同一轮内完成）："""

        # 分析集说明
        aset = tbl["analysis_set"]
        if aset == "-":
            aset_note = "分析集为 `-`（表题/父节未声明分析集）——这不视为错误，按现有数据正常核查。"
        else:
            aset_note = f"分析集: {aset}"

        # Phase 3 边界：本表若是 病例分布表/入组病例表，规则文档 §2.4 已在 Phase 3 处理
        phase3_boundary_note = ""
        if tbl["table_type"] in ("病例分布表", "入组病例表"):
            phase3_boundary_note = (
                "\n⚠️ **Phase 边界**：本表的 §2.4（外部参照类 R-050~R-053）"
                "已在 Phase 3 由外部核查 subagent 处理，"
                "**本阶段跳过 §2.4**，只跑 §2.2 / §2.3。\n"
            )

        full_system_prompt = f"""你是临床试验方面的高级统计师，你要对此表格进行内部 QC（表内一致性核查）。

## 本表信息
- 表编号: {tidx}
- 表标题: {tbl['table_title']}
- 表型: {ttype}
- {aset_note}
- 表格文件: {tables_dir}/{tbl['filename']}
- 共享核查库: `{skill}/qc_lib.py`（`import sys; sys.path.insert(0, "{skill}"); from qc_lib import ...`）
- {baseline_note}

{baseline_section}{phase3_boundary_note}
---
## 表型规则文档（本表需执行的 QC 规则 + 代码模板）
{rule_content}
---
## 输出模板（markdown 报告输出标准格式，禁止增删元数据行）
{template_content}
{steps_block}
   - 机器读 JSON：**必须**用 `iss.to_json("{qc_output_dir}/qc_{tidx:02d}.json")` 落盘，禁止手写 `json.dump` 或 write_file 构造 JSON，禁止改名（如 `qc_XX_checks.json`）——build_reports.py 依赖 `Issues.to_json` 产出的结构化格式
   - 人读 markdown：严格按上方输出模板用 write_file 写到 `{qc_output_dir}/qc_{tidx:02d}.md`

## 纪律
- 输出必须包含四行元数据: `##META_TABLE` / `##META_TYPE` / `##META_ANALYSIS_SET` / `##META_CONCLUSION`（缺一不可，连续放在文件最开头，中间不能有空行）
- `##META_ANALYSIS_SET` 只填纯 acronym（FAS/ITT/mITT/PPS/SS）或 `随机化人群` 或 `-`；禁止 `FAS人群`/`ITT集` 等带后缀写法；`mITT` 首字母小写其余大写
- `##META_CONCLUSION` 取 PASS/CRITICAL/MAJOR/MINOR/SUGGESTION 之一
- 缺数据/N=0/取不到值 → 静默跳过，不产 Finding（不是"通过"）
- 判不了但疑似异常 → level="待人工"
- 表型为 `other` → 至少产一条 level="待人工"
- 分析集为 `-` 不视为问题，按数据照常核查
- **不要基于表名/表题关键词判断"疗效表 vs 安全性/AE 表"，也不要据此对分析集合不合规下结论**——R-030 已删除，文件名声明的分析集是什么就按什么核查
- 算术一律调 `qc_lib`（`check_sum / check_pct / check_ordered / check_le` 等），不准 LLM 眼算
- 所有 Finding 必须包含具体期望值 vs 实际值，禁止写"应一致/不一致/有偏差"
- SOC 人数 ≤ ΣPT 是 MedDRA 正常行为，不是错误
- 基准比对用 ≤（子集表人数更少属正常），只有超过才报

## 问题分级
- **Critical** — 可能影响主要/安全性结论（N值严重矛盾、主要终点不可复现）
- **Major** — 影响报告质量或可追溯性（表题分析集与分母不一致、Σn≠N、%≠n/N）
- **Minor** — 格式/脚注/编码/表号（N标注不统一、表号引用错误）
- **Suggestion** — 非错误，建议改进（补脚注、措辞统一）
- **待人工** — 判不了但疑似异常，需人工确认

## 禁止
- META_CONCLUSION 取 PASS 却列了问题
- PASS 表只写"未发现问题"不搬原表
- 用独立核查清单代替原表标注
- 原表结构与原始 xlsx 不一致（行列/表头/分组/多截面必须保留）
"""

        prompt_specs.append({
            "table": tbl,
            "system_prompt": full_system_prompt,
        })

    return prompt_specs


def _run_single_table_qc(table_spec: dict, state: InnerQCState) -> tuple[int, str | None, str | None]:
    """使用 Anthropic SDK 对单张表运行 tool-use 循环。

    Returns:
        (table_idx, md_report_path, json_report_path) — 失败返回 (idx, None, None)
    """
    tbl: TableInfo = table_spec["table"]
    system_prompt: str = table_spec["system_prompt"]
    tidx = tbl["idx"]
    project = state["project_dir"]
    qc_output_dir = state["qc_output_dir"]

    client = _create_anthropic_client(state)
    model = state.get("model", LLM_MODEL)

    user_prompt = f"请开始对编号 {tidx:02d}（{tbl['table_title']}，表型: {tbl['table_type']}）进行表内一致性核查，按 Skill 指令逐步执行。"

    messages = [{"role": "user", "content": user_prompt}]
    max_iterations = 30

    tools = [
        {
            "name": "bash",
            "description": "执行 shell 命令。用 python3 + openpyxl 读取 Excel，或运行 QC 核查脚本。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"}
                },
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "读取文件内容。注意：.xlsx 是二进制格式，请用 bash + python3 openpyxl 读取。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "要读取的文件路径（相对于项目目录）"}
                },
                "required": ["file_path"],
            },
        },
        {
            "name": "write_file",
            "description": "将内容写入文件。用于输出 QC 报告 md 和 JSON 结果。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "输出文件路径（相对于项目目录）"},
                    "content": {"type": "string", "description": "要写入的文件内容"}
                },
                "required": ["file_path", "content"],
            },
        },
    ]

    for iteration in range(max_iterations):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=system_prompt,
                messages=messages,
                tools=tools,
            )
        except Exception as e:
            import traceback
            print(f"  ❌ Pair {tidx:02d} API 调用失败 (iteration {iteration}): {e}")
            traceback.print_exc()
            if iteration < 2:
                import time
                time.sleep(5)
                continue
            return (tidx, None, None)

        # 解析响应
        text_blocks: list[str] = []
        tool_requests: list[dict] = []

        for block in response.content:
            if block.type == "text":
                text_blocks.append(block.text)
            elif block.type == "tool_use":
                tool_requests.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            # thinking / redacted_thinking 块跳过

        # 构建 assistant 消息
        assistant_content: list[dict] = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            # thinking / redacted_thinking 块不需回传

        # 若只有 thinking 块（无 text/tool_use），补一个占位以防空 content 被 API 拒绝
        if not assistant_content:
            assistant_content = [{"type": "text", "text": "（思考中）"}]

        messages.append({"role": "assistant", "content": assistant_content})

        # 无工具调用 → LLM 认为完成
        if not tool_requests:
            text = "\n".join(text_blocks)
            if any(kw in text for kw in ["完成", "核查完毕", "报告已写入", "报告已生成"]):
                break
            # 继续引导
            messages.append({
                "role": "user",
                "content": "请确认是否已生成 QC报告 md 文件和 JSON 结果文件？如未完成请继续。",
            })
            continue

        # 执行工具调用
        tool_results: list[dict] = []
        for tr in tool_requests:
            tool_name = tr["name"]
            tool_input = tr["input"]

            if tool_name == "bash":
                cmd = tool_input.get("command", "")
                try:
                    r = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True,
                        timeout=300, cwd=project,
                    )
                    result_text = r.stdout
                    if r.stderr:
                        result_text += f"\n[stderr]\n{r.stderr}"
                    if r.returncode != 0:
                        result_text += f"\n[exit code: {r.returncode}]"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": result_text[:8000] or "(空输出)",
                    })
                except subprocess.TimeoutExpired:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": "命令超时 (>300s)",
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": f"执行失败: {e}",
                    })

            elif tool_name == "read_file":
                file_path = tool_input.get("file_path", tool_input.get("path", ""))
                try:
                    # 安全检查：不允许读取绝对路径以外的敏感文件
                    if not file_path or ".." in file_path:
                        raise ValueError("无效文件路径")
                    abs_path = os.path.join(project, file_path) if not os.path.isabs(file_path) else file_path
                    with open(abs_path) as f:
                        content = f.read()
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": content[:8000] if len(content) > 8000 else content,
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": f"读取失败: {e}",
                    })

            elif tool_name == "write_file":
                file_path = tool_input.get("file_path", tool_input.get("path", ""))
                content = tool_input.get("content", "")
                try:
                    if not file_path or ".." in file_path:
                        raise ValueError("无效文件路径")
                    abs_path = os.path.join(project, file_path) if not os.path.isabs(file_path) else file_path
                    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                    with open(abs_path, "w") as f:
                        f.write(content)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": f"文件已写入: {abs_path} ({len(content)} 字符)",
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": f"写入失败: {e}",
                    })

            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tr["id"],
                    "content": f"未知工具: {tool_name}",
                })

        messages.append({"role": "user", "content": tool_results})

    # 检查产出 — 允许调用方指定文件名前缀（Phase 3 用 "qc_ext"，Phase 5 用 "qc"）
    file_prefix = table_spec.get("file_prefix", "qc")
    md_path = os.path.join(qc_output_dir, f"{file_prefix}_{tidx:02d}.md")
    json_path = os.path.join(qc_output_dir, f"{file_prefix}_{tidx:02d}.json")

    md_ok = os.path.exists(md_path)
    json_ok = os.path.exists(json_path)

    if md_ok or json_ok:
        print(f"  ✅ 表 {tidx:02d}: md={'✅' if md_ok else '❌'} json={'✅' if json_ok else '❌'}")
        return (tidx, md_path if md_ok else None, json_path if json_ok else None)
    else:
        print(f"  ❌ 表 {tidx:02d}: 未生成任何报告文件")
        return (tidx, None, None)


def phase4_prepare(state: InnerQCState) -> dict:
    """Phase 5 准备：确定待核查表清单，创建 qc_output/ 目录"""
    print("\n" + "=" * 60)
    print("🔍 Phase 5 准备: 确定待核查表清单")
    print("=" * 60)

    tables = state.get("classified_tables", [])
    max_pairs = state.get("max_pairs", 0)
    phase3_indices = set(state.get("phase3_table_indices", []))

    # 排除 Phase 3 已处理的外部核查表（它们已有 qc_ext_*.json/md）
    qc_tables = [t for t in tables if t["idx"] not in phase3_indices]
    if max_pairs > 0 and len(qc_tables) > max_pairs:
        qc_tables = qc_tables[:max_pairs]
        print(f"  限制最多 {max_pairs} 张表")

    qc_output_dir = os.path.join(state["project_dir"], "qc_output")
    # 只清空 Phase 5 自己的旧报告（qc_*.md/json），保留 Phase 3 的 qc_ext_*
    if os.path.isdir(qc_output_dir):
        for fname in os.listdir(qc_output_dir):
            # qc_05.md / qc_05.json 是 Phase 5 的，qc_ext_03.md 是 Phase 3 的
            if fname.startswith("qc_") and not fname.startswith("qc_ext_"):
                os.unlink(os.path.join(qc_output_dir, fname))
    os.makedirs(qc_output_dir, exist_ok=True)

    print(f"  待核查表: {len(qc_tables)} 张")

    print("✅ Phase 5 准备完成")

    return {
        "qc_tables": qc_tables,
        "total_tables": len(qc_tables),
        "qc_output_dir": qc_output_dir,
        "current_phase": "phase4_prepare_done",
    }


def phase4_run_qc(state: InnerQCState) -> dict:
    """Phase 5: 并行运行逐表 QC subagent（一表一 agent）"""
    print("\n" + "=" * 60)
    print("🔬 Phase 5: 逐表 QC（并行 subagent）")
    print("=" * 60)

    qc_tables = state.get("qc_tables", [])
    if not qc_tables:
        print("  ⚠️ 没有待核查的表，跳过 Phase 4")
        return {"current_phase": "phase4_done"}

    if state.get("no_subagent"):
        print("  ⏭️  跳过 subagent 核查 (--no-subagent)")
        return {"current_phase": "phase4_done"}

    qc_output_dir = state["qc_output_dir"]

    # 0. 增量恢复：检查已落盘的 qc_*.json，跳过已完成表
    already_done: dict[int, tuple[str, str]] = {}  # idx -> (md_path, json_path)
    for tbl in qc_tables:
        tidx = tbl["idx"]
        md = os.path.join(qc_output_dir, f"qc_{tidx:02d}.md")
        jn = os.path.join(qc_output_dir, f"qc_{tidx:02d}.json")
        if os.path.exists(md) and os.path.getsize(md) > 0 and os.path.exists(jn) and os.path.getsize(jn) > 0:
            already_done[tidx] = (md, jn)
    if already_done:
        skipped = {tidx for tidx in already_done}
        qc_tables = [t for t in qc_tables if t["idx"] not in skipped]
        print(f"  ♻️  复用已完成的 {len(already_done)} 张表: {sorted(skipped)}")
        if not qc_tables:
            print("  ✅ 全部表已完成，跳过大模型调用")
            return {
                "qc_report_paths": [md for md, _ in already_done.values()],
                "current_phase": "phase4_done",
            }

    # 构建 system prompt（baseline.json 已由 Phase 3 产出）
    prompt_specs = _build_table_system_prompts(qc_tables, state)
    total = len(prompt_specs)
    if total == 0:
        print("  无待核查表")
        return {"current_phase": "phase4_done"}

    print(f"  启动 {total} 个并行 subagent（跳过 {len(already_done)} 个已完成）...")
    max_workers = min(max(total, 1), 8)

    qc_report_paths: list[str] = [md for md, _ in already_done.values()]
    json_paths: list[str] = [jn for _, jn in already_done.values()]
    failed_indices: list[int] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_run_single_table_qc, spec, state): spec["table"]["idx"]
            for spec in prompt_specs
        }

        completed = 0
        for future in as_completed(future_map):
            tidx = future_map[future]
            try:
                idx, md_path, json_path = future.result()
            except Exception as e:
                print(f"  ❌ 表 {tidx:02d}: 异常退出 ({e})")
                failed_indices.append(tidx)
                completed += 1
                continue

            completed += 1
            if md_path:
                qc_report_paths.append(md_path)
            if json_path:
                json_paths.append(json_path)
            if not md_path and not json_path:
                failed_indices.append(tidx)
            print(f"  进度: {completed}/{total}")

    # ── 重试失败的 ──
    max_retries = state.get("max_retries", 2)
    for retry in range(max_retries):
        if not failed_indices:
            break
        print(f"\n  🔄 重试 {retry + 1}/{max_retries}: {len(failed_indices)} 张表...")
        retry_specs = [s for s in prompt_specs if s["table"]["idx"] in failed_indices]
        still_failed: list[int] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            retry_futures = {
                executor.submit(_run_single_table_qc, spec, state): spec["table"]["idx"]
                for spec in retry_specs
            }
            for future in as_completed(retry_futures):
                tidx = retry_futures[future]
                try:
                    idx, md_path, json_path = future.result()
                except Exception:
                    still_failed.append(tidx)
                    continue
                if md_path:
                    qc_report_paths.append(md_path)
                if json_path:
                    json_paths.append(json_path)
                if not md_path and not json_path:
                    still_failed.append(tidx)

        failed_indices = still_failed

    if failed_indices:
        print(f"  ⚠️ 最终仍有 {len(failed_indices)} 张表未生成报告: {failed_indices}")

    print(f"✅ Phase 5 完成: {len(qc_report_paths)} MD + {len(json_paths)} JSON")

    return {
        "qc_report_paths": qc_report_paths,
        "current_phase": "phase4_done",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 6: 合并报告 + HTML 可视化（两个独立步骤）
# ═══════════════════════════════════════════════════════════════════════════

def phase6_merge(state: InnerQCState) -> dict:
    """Phase 6a: 合并所有 qc_*.json 为 markdown 总报告（使用 merge_qc.py）"""
    print("\n" + "=" * 60)
    print("📝 Phase 6: 合并报告")
    print("=" * 60)

    skill = state["skill_dir"]
    project = state["project_dir"]
    qc_output_dir = state["qc_output_dir"]
    baseline_path = state.get("baseline_path", "")
    table_input = state["table_input"]

    # 优先用 merge_qc.py（proven），备选 build_reports.py（新版）
    merge_script = os.path.join(skill, "merge_qc.py")
    if not os.path.exists(merge_script):
        merge_script = os.path.join(skill, "build_reports.py")
    if not os.path.exists(merge_script):
        print("  ⚠️ 没有可用的合并脚本，跳过")
        return {"current_phase": "phase6_merge_done"}

    args = [qc_output_dir]
    if baseline_path and os.path.exists(baseline_path):
        args += ["--baseline", baseline_path]
    args += ["--source", os.path.basename(table_input)]

    report_path = os.path.join(qc_output_dir, "总体QC报告.md")
    args += ["--out", report_path]

    result = _run_script(merge_script, args, cwd=project)

    if result.returncode != 0:
        print(f"  ⚠️ 合并脚本返回非零: {result.returncode}")

    md_ok = os.path.exists(report_path)
    print(f"✅ Phase 6 合并完成: md={'✅' if md_ok else '❌'}")

    return {
        "merged_report_path": report_path if md_ok else "",
        "current_phase": "phase6_merge_done",
    }


def phase6_build_viewer(state: InnerQCState) -> dict:
    """Phase 6b: 调用 build_report_viewer.py 生成 HTML 可视化报告（保留封面页模板）"""
    print("\n" + "=" * 60)
    print("🌐 Phase 6: 生成 HTML 可视化报告")
    print("=" * 60)

    skill = state["skill_dir"]
    project = state["project_dir"]
    qc_output_dir = state["qc_output_dir"]
    tables_dir = state["tables_output_dir"]

    build_script = os.path.join(skill, "build_report_viewer.py")
    if not os.path.exists(build_script):
        print("  ⚠️ build_report_viewer.py 不存在，跳过 HTML 构建")
        return {"current_phase": "phase6_done"}

    output_html = os.path.join(qc_output_dir, "QC可视化报告.html")
    args = [
        "--reports-dir", qc_output_dir,
        "--tables-dir", tables_dir,
        "--output", output_html,
    ]

    result = _run_script(build_script, args, cwd=project)

    if result.returncode != 0:
        print(f"  ⚠️ build_report_viewer.py 返回非零: {result.returncode}")

    html_ok = os.path.exists(output_html)
    print(f"✅ Phase 6 可视化完成: html={'✅' if html_ok else '❌'}")

    return {
        "viewer_html_path": output_html if html_ok else "",
        "current_phase": "phase6_done",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 7: 清理中间产物
# ═══════════════════════════════════════════════════════════════════════════

def phase7_cleanup(state: InnerQCState) -> dict:
    """Phase 7: 移 markdown 报告到项目根 + 删除 tables_output/ 中间目录。

    注意：HTML 可视化报告保留在 qc_output/ 不动，供 Web 下载接口访问。
    """
    print("\n" + "=" * 60)
    print("🧹 Phase 7: 清理中间产物")
    print("=" * 60)

    if state.get("skip_cleanup"):
        print("  ⏭️  跳过清理 (--skip-cleanup)")
        return {"current_phase": "phase7_done"}

    skill = state["skill_dir"]
    project = state["project_dir"]
    qc_output_dir = state.get("qc_output_dir", os.path.join(project, "qc_output"))
    tables_dir = state.get("tables_output_dir", os.path.join(project, "tables_output"))

    # 只移动 markdown 总报告到项目根（HTML 保留在 qc_output/ 供下载）
    md_src = os.path.join(qc_output_dir, "总体QC报告.md")
    md_dst = os.path.join(project, "总体QC报告.md")
    if os.path.exists(md_src):
        import shutil
        if os.path.exists(md_dst):
            os.unlink(md_dst)
        shutil.move(md_src, md_dst)
        print(f"  ↪ 总体QC报告.md → {md_dst}")

    # 删除 tables_output/ 中间目录
    if os.path.isdir(tables_dir):
        import shutil as _shutil
        _shutil.rmtree(tables_dir, ignore_errors=True)
        print(f"  🗑️  已删除 {tables_dir}/")

    print("✅ Phase 7 完成")
    return {"current_phase": "phase7_done"}


# ═══════════════════════════════════════════════════════════════════════════
# 组装 LangGraph 管线
# ═══════════════════════════════════════════════════════════════════════════

def _after_phase(state: InnerQCState) -> str:
    if state.get("error_message"):
        return "error_end"
    return "continue"


def _after_phase4_prepare(state: InnerQCState) -> str:
    if state.get("error_message"):
        return "error_end"
    return "phase4_run_qc"


def _after_phase3_external(state: InnerQCState) -> str:
    """Phase 3 后路由：无论跳过还是执行完，都进 Phase 4 baseline"""
    if state.get("error_message"):
        return "error_end"
    return "phase3_baseline"


def build_inner_qc_workflow(enable_checkpoint: bool = True) -> StateGraph:
    """构建完整内部 QC 工作流（七阶段）。

    管线: P1→P2→P3(external,可选)→P4(baseline)→P5(prep)→P5(run)→P6(reports)→P7(cleanup)→END
    """
    builder = StateGraph(InnerQCState)

    # 注册节点
    builder.add_node("phase1_extract", phase1_extract)
    builder.add_node("phase2_classify", phase2_classify)
    builder.add_node("phase3_external_qc", phase3_external_qc)
    builder.add_node("phase3_baseline", phase3_baseline)
    builder.add_node("phase4_prepare", phase4_prepare)
    builder.add_node("phase4_run_qc", phase4_run_qc)
    builder.add_node("phase6_merge", phase6_merge)
    builder.add_node("phase6_build_viewer", phase6_build_viewer)
    builder.add_node("phase7_cleanup", phase7_cleanup)

    # 管线: 1→2→3_ext→3_baseline→4_prep→4_run→6_merge→6_viewer→7_cleanup→END
    builder.set_entry_point("phase1_extract")

    builder.add_conditional_edges(
        "phase1_extract", _after_phase,
        {"continue": "phase2_classify", "error_end": END},
    )
    builder.add_conditional_edges(
        "phase2_classify", _after_phase,
        {"continue": "phase3_external_qc", "error_end": END},
    )
    # Phase 3 external QC → always proceed to baseline (skip or done)
    builder.add_conditional_edges(
        "phase3_external_qc", _after_phase3_external,
        {"phase3_baseline": "phase3_baseline", "error_end": END},
    )
    builder.add_conditional_edges(
        "phase3_baseline", _after_phase,
        {"continue": "phase4_prepare", "error_end": END},
    )
    builder.add_conditional_edges(
        "phase4_prepare", _after_phase4_prepare,
        {"phase4_run_qc": "phase4_run_qc", "error_end": END},
    )
    builder.add_conditional_edges(
        "phase4_run_qc", _after_phase,
        {"continue": "phase6_merge", "error_end": END},
    )
    builder.add_conditional_edges(
        "phase6_merge", _after_phase,
        {"continue": "phase6_build_viewer", "error_end": END},
    )
    builder.add_conditional_edges(
        "phase6_build_viewer", _after_phase,
        {"continue": "phase7_cleanup", "error_end": END},
    )
    builder.add_edge("phase7_cleanup", END)

    checkpointer = MemorySaver() if enable_checkpoint else None
    return builder.compile(checkpointer=checkpointer)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Inner Table QC — 临床试验表格表内一致性核查管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
    # 基本用法
    python inner_qc_workflow.py --api-key sk-xxx --table 表格.docx --project ./project

    # 使用外部人数基准
    python inner_qc_workflow.py --api-key sk-xxx --table 表格.docx \\
        --baseline-xlsx 人群划分表.xlsx --project ./project

    # 外部核查（Phase 3）：用外部权威表核查 TFL 分中心/人群数据
    python inner_qc_workflow.py --api-key sk-xxx --table 表格.docx \\
        --external-population 人群划分表.xlsx --external-randomization 随机表.xlsx \\
        --project ./project

    # 限制核查表数
    python inner_qc_workflow.py --api-key sk-xxx --table 表格.docx \\
        --max-pairs 5 --project ./project

    # 跳过 subagent 核查（仅提取+分类+基线）
    python inner_qc_workflow.py --api-key sk-xxx --table 表格.docx \\
        --no-subagent --project ./project

    # 调试：跳过 Phase 7 清理
    python inner_qc_workflow.py --api-key sk-xxx --table 表格.docx \\
        --skip-cleanup --project ./project
""",
    )

    parser.add_argument("--table", required=True, help="表格附件路径 (docx/pdf)")
    parser.add_argument("--project", required=True, help="项目工作目录（产出将写入此目录）")
    parser.add_argument("--api-key", default=LLM_API_KEY,
                        help="API key（DeepSeek Anthropic 兼容，也可通过环境变量 ANTHROPIC_AUTH_TOKEN 设置）")
    parser.add_argument("--api-base", default=LLM_API_BASE,
                        help="API base URL (默认: https://api.deepseek.com/anthropic)")
    parser.add_argument("--model", default=LLM_MODEL, help="LLM 模型名")
    parser.add_argument("--skill-dir", help="inner_qc 资源目录（默认自动解析）")
    parser.add_argument("--baseline-xlsx", help="外部人群划分表 xlsx（旧参数，仍支持，等价于 --external-population）")
    parser.add_argument("--baseline-json", help="已抽好的 baseline.json（可选）")
    parser.add_argument("--external-population", default="",
                        help="外部人群划分表 xlsx（Phase 3 外部核查用，需含'筛选号'列）")
    parser.add_argument("--external-randomization", default="",
                        help="外部随机表 xlsx（Phase 3 外部核查用，需含'筛选号'列）")
    parser.add_argument("--max-pairs", type=int, default=0,
                        help="最多 QC 表数（0=全部）")
    parser.add_argument("--max-retries", type=int, default=2,
                        help="缺失结果最大重试次数（默认2）")
    parser.add_argument("--no-subagent", action="store_true",
                        help="跳过 Phase 5 subagent LLM 核查")
    parser.add_argument("--skip-cleanup", action="store_true",
                        help="跳过 Phase 7 清理中间产物（调试用）")
    parser.add_argument("--no-checkpoint", action="store_true",
                        help="禁用 LangGraph checkpointer")

    args = parser.parse_args()

    # 验证输入
    if not os.path.exists(args.table):
        print(f"❌ 表格文件不存在: {args.table}")
        sys.exit(1)

    # 创建项目目录
    project_dir = os.path.abspath(args.project)
    os.makedirs(project_dir, exist_ok=True)

    # 解析 skill 目录
    skill_dir = args.skill_dir or _resolve_skill_dir()
    if not os.path.isdir(skill_dir):
        print(f"❌ inner_qc 目录不存在: {skill_dir}")
        sys.exit(1)

    # 初始状态
    # --baseline-xlsx 向后兼容：等价于 --external-population
    ext_pop = args.external_population or args.baseline_xlsx or ""
    initial_state: InnerQCState = {
        "table_input": os.path.abspath(args.table),
        "project_dir": project_dir,
        "skill_dir": skill_dir,
        "model": args.model,
        "api_key": args.api_key or "",
        "api_base": args.api_base,
        "baseline_xlsx": os.path.abspath(ext_pop) if ext_pop else "",
        "baseline_json": os.path.abspath(args.baseline_json) if args.baseline_json else "",
        "external_population": os.path.abspath(ext_pop) if ext_pop else "",
        "external_randomization": os.path.abspath(args.external_randomization) if args.external_randomization else "",
        "max_pairs": args.max_pairs or 0,
        "max_retries": args.max_retries,
        "no_subagent": args.no_subagent,
        "skip_cleanup": args.skip_cleanup,
        "qc_report_paths": [],
        "current_phase": "init",
        "error_message": "",
    }

    # 构建并运行
    workflow = build_inner_qc_workflow(enable_checkpoint=not args.no_checkpoint)

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Inner Table QC — 临床试验表格表内一致性核查              ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  表格: {args.table}")
    print(f"║  项目: {project_dir}")
    print(f"║  模型: {args.model}")
    if ext_pop:
        print(f"║  外部人群划分表: {ext_pop}")
    if args.external_randomization:
        print(f"║  外部随机表: {args.external_randomization}")
    if args.baseline_json:
        print(f"║  基线 JSON: {args.baseline_json}")
    if args.no_subagent:
        print(f"║  模式: 仅提取+分类+基线（跳过 subagent 核查）")
    if args.skip_cleanup:
        print(f"║  调试: 跳过 Phase 7 清理")
    print("╚══════════════════════════════════════════════════════════════╝")

    # 开始执行
    config = {"configurable": {"thread_id": os.path.basename(project_dir)}}

    try:
        result = workflow.invoke(initial_state, config)
    except Exception as e:
        print(f"\n❌ 管线执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if result.get("error_message"):
        print(f"\n❌ 管线中断: {result['error_message']}")
        return

    # 打印最终产出
    print("\n" + "=" * 60)
    print("🎉 内部 QC 管线全部完成!")
    print(f"📂 最终产出: {project_dir}")
    if result:
        if result.get("external_ref_path"):
            print(f"   🔗 {result['external_ref_path']}")
        if result.get("baseline_path"):
            print(f"   📏 {result['baseline_path']}")
        if result.get("merged_report_path"):
            print(f"   📝 {result['merged_report_path']}")
        if result.get("viewer_html_path"):
            print(f"   🌐 {result['viewer_html_path']} (交互式浏览)")
        if not result.get("skip_cleanup") and not args.skip_cleanup:
            print(f"   🧹 中间目录已清理（tables_output/、qc_output/）")
    print("=" * 60)


if __name__ == "__main__":
    main()
