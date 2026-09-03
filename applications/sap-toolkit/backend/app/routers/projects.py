import json
import os
import shutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Project, User
from app.dependencies import get_current_user
from app.config import SAP_OUTPUT_BASE

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    sap_path: str
    crf_path: str | None = None


class UpdateTablesRequest(BaseModel):
    tables: list[dict]


@router.get("")
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    projects = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "name": p.name,
            "sap_filename": p.sap_filename,
            "crf_filename": p.crf_filename,
            "status": p.status,
            "phase": p.phase,
            "tables_count": p.tables_count,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in projects
    ]


@router.post("")
def create_project(
    req: CreateProjectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not req.name.strip():
        raise HTTPException(400, "项目名称不能为空")

    # Resolve absolute paths
    # __file__ = app/routers/projects.py → need 3 dirname to reach backend/
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sap_abs = req.sap_path if os.path.isabs(req.sap_path) else os.path.join(base, req.sap_path)
    crf_abs = (req.crf_path if os.path.isabs(req.crf_path) else os.path.join(base, req.crf_path)) if req.crf_path else None

    if not os.path.exists(sap_abs):
        raise HTTPException(400, "SAP 文件不存在")

    # Create output directory
    output_dir = os.path.join(SAP_OUTPUT_BASE, f"sap_output_{current_user.id}_{req.name.strip()}")
    os.makedirs(output_dir, exist_ok=True)

    sap_filename = os.path.basename(sap_abs)
    crf_filename = os.path.basename(crf_abs) if crf_abs else None

    project = Project(
        user_id=current_user.id,
        name=req.name.strip(),
        sap_filename=sap_filename,
        crf_filename=crf_filename,
        sap_path=sap_abs,
        crf_path=crf_abs,
        output_dir=output_dir,
        status="pending",
        phase="pending",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return {
        "id": project.id,
        "name": project.name,
        "status": project.status,
        "phase": project.phase,
    }


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    return {
        "id": p.id,
        "name": p.name,
        "sap_filename": p.sap_filename,
        "crf_filename": p.crf_filename,
        "status": p.status,
        "phase": p.phase,
        "tables_count": p.tables_count,
        "output_dir": p.output_dir,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")

    # 删除输出目录
    if p.output_dir and os.path.exists(p.output_dir):
        shutil.rmtree(p.output_dir, ignore_errors=True)

    # 删除上传的文件
    for path in [p.sap_path, p.crf_path]:
        if path and os.path.exists(path):
            os.remove(path)

    db.delete(p)
    db.commit()
    return {"message": "项目已删除"}


@router.get("/{project_id}/tables")
def get_tables(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.output_dir:
        raise HTTPException(404, "项目输出目录不存在")

    tables_json = os.path.join(p.output_dir, "tables.json")
    if not os.path.exists(tables_json):
        raise HTTPException(404, "表格目录尚未生成，请先完成阶段一")

    with open(tables_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@router.put("/{project_id}/tables")
def update_tables(
    project_id: int,
    req: UpdateTablesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.output_dir:
        raise HTTPException(404, "项目输出目录不存在")

    # Build the new tables.json
    # Re-index all tables sequentially, preserve data_source and projects
    indexed_tables = []
    for i, t in enumerate(req.tables, start=1):
        entry = {
            "category": t.get("category", ""),
            "index": i,
            "name": t.get("name", ""),
        }
        if "data_source" in t:
            entry["data_source"] = t["data_source"]
        if "projects" in t:
            entry["projects"] = t["projects"]
        indexed_tables.append(entry)

    data = {"total": len(indexed_tables), "tables": indexed_tables}

    tables_json = os.path.join(p.output_dir, "tables.json")
    with open(tables_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Sync prompts.json and generate manual table JSONs
    _sync_prompts_and_manual_tables(p.output_dir, indexed_tables)

    # Update project
    p.tables_count = len(indexed_tables)
    p.phase = "catalog"
    p.status = "completed"
    db.commit()

    return {"total": len(indexed_tables), "tables": indexed_tables}


def _sync_prompts_and_manual_tables(output_dir: str, tables: list):
    """同步 prompts.json 并为手动填写的表格生成 JSON"""
    prompts_file = os.path.join(output_dir, "prompts.json")
    info_dir = os.path.join(output_dir, "05_表格信息")
    os.makedirs(info_dir, exist_ok=True)

    # Load existing prompts.json if exists
    existing_prompts = {}
    if os.path.exists(prompts_file):
        with open(prompts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            existing_prompts[item["name"]] = item

    # Skip keywords for auto-fetch (same as generate_prompts)
    skip_keywords = ["主要疗效终点", "器械缺陷", "不良事件", "实验室检查", "生命体征", "合并用药"]
    skip_names = ["各中心病例分布情况", "各中心人群划分情况"]

    new_prompt_items = []
    for t in tables:
        name = t.get("name", "")
        category = t.get("category", "")
        data_source = t.get("data_source", "auto")
        projects = t.get("projects", [])

        if data_source == "manual" and projects:
            # Generate table JSON for manual items
            table_json = {
                "table_name": name,
                "projects": projects,
            }
            safe_name = name.replace("/", "_").replace("\\", "_")
            json_file = os.path.join(info_dir, f"{safe_name}.json")
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(table_json, f, ensure_ascii=False, indent=2)

        elif data_source == "auto":
            # Check if should skip
            if any(kw in category for kw in skip_keywords):
                continue
            if any(skip_name in name for skip_name in skip_names):
                continue

            # Preserve existing custom prompt or generate default
            if name in existing_prompts:
                new_prompt_items.append(existing_prompts[name])
            else:
                new_prompt_items.append({
                    "name": name,
                    "category": category,
                    "instruction": _build_instruction(name),
                    "enabled": True,
                })

    # Write updated prompts.json
    prompts_data = {
        "common": {
            "extract_rules": COMMON_EXTRACT_RULES,
            "output_format": COMMON_OUTPUT_FORMAT,
            "notes": COMMON_NOTES,
        },
        "items": new_prompt_items,
    }

    with open(prompts_file, "w", encoding="utf-8") as f:
        json.dump(prompts_data, f, ensure_ascii=False, indent=2)

    # 清理 05_表格信息/ 中已不在 tables.json 的残留文件
    if os.path.exists(info_dir):
        valid_names = {t.get("name", "") for t in tables}
        # 也保留文件名中 / 被替换为 _ 的变体
        valid_safe_names = {n.replace("/", "_").replace("\\", "_") for n in valid_names}
        for fname in os.listdir(info_dir):
            if not fname.endswith(".json"):
                continue
            table_name_stem = fname[:-5]  # 去掉 .json
            if table_name_stem not in valid_names and table_name_stem not in valid_safe_names:
                # 再检查文件内部的 table_name 字段
                fpath = os.path.join(info_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    inner_name = data.get("table_name", "")
                    if inner_name not in valid_names:
                        os.remove(fpath)
                except Exception:
                    pass


@router.get("/{project_id}/results")
def get_project_results(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.output_dir or not os.path.exists(p.output_dir):
        return {"tables": None, "content_files": []}

    result = {"tables": None, "content_files": []}

    # Load tables.json
    tables_json = os.path.join(p.output_dir, "tables.json")
    if os.path.exists(tables_json):
        with open(tables_json, "r", encoding="utf-8") as f:
            result["tables"] = json.load(f)

    # List content extraction files
    content_dir = os.path.join(p.output_dir, "02_内容提取")
    if os.path.exists(content_dir):
        result["content_files"] = [
            f for f in os.listdir(content_dir)
            if f.endswith(".md") or f.endswith(".json")
        ]

    return result


@router.get("/{project_id}/content/{filename}")
def get_project_content(project_id: int, filename: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")

    content_dir = os.path.join(p.output_dir, "02_内容提取")
    file_path = os.path.join(content_dir, filename)

    if not os.path.exists(file_path):
        raise HTTPException(404, "文件不存在")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {"filename": filename, "content": content}


@router.get("/{project_id}/download/{file_type}")
def download_project_file(project_id: int, file_type: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from fastapi.responses import FileResponse

    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.output_dir:
        raise HTTPException(404, "项目输出目录不存在")

    if file_type == "markdown":
        file_path = os.path.join(p.output_dir, "表格目录_汇总.md")
        if not os.path.exists(file_path):
            raise HTTPException(404, "Markdown 报告尚未生成")
        return FileResponse(file_path, filename=f"{p.name}_表格目录.md", media_type="text/markdown")
    elif file_type == "docx":
        for candidate in ["合并的表格_formatted.docx", "填充的表格/合并的表格_formatted.docx"]:
            file_path = os.path.join(p.output_dir, candidate)
            if os.path.exists(file_path):
                return FileResponse(file_path, filename=f"{p.name}_表格.docx")
        raise HTTPException(404, "Word 文档尚未生成")
    elif file_type == "tables":
        file_path = os.path.join(p.output_dir, "tables.json")
        if not os.path.exists(file_path):
            raise HTTPException(404, "表格目录尚未生成")
        return FileResponse(file_path, filename=f"{p.name}_tables.json")
    else:
        raise HTTPException(400, f"不支持的文件类型: {file_type}")


# ===== Prompts 端点 =====

# 公共规则（与 scripts/phase2/extract_table_info.py 中的 prompt 保持一致）
COMMON_EXTRACT_RULES = """1. 提取该表格所需的测量项目或记录项目
2. 每个项目要**一个一个列出**，不要合并
3. 区分定性项目和定量项目：
   - **定性项目**（分类型）：需要列出所有可能的分类选项，使用 categories 字段
   - **定量项目**（数值型）：只需要名称和单位，使用 unit 字段
4. **不要提取以下类型的项目**：
   - 文本输入框（如 Char(100)、Char(200) 等自由填写的文本字段）
   - 日期输入框（如"日期型"、"部分日期型"等日期字段）
   - 时间输入框
   - 这些字段在CRF中通常显示为"XXX Char(N)"或"XXX 日期型"
5. 只提取**有固定分类选项**的定性项目和**有明确单位**的定量项目
6. **项目名称规范化**：去掉CRF中的编码和缩写（如CS、TIA、MHYN等），只保留中文描述名称。例如："不明原因脑卒中CS" → "不明原因脑卒中"，"短暂性脑缺血发作TIA" → "短暂性脑缺血发作\""""

COMMON_OUTPUT_FORMAT = """必须使用 write_table_json 工具保存结果（不要使用 write_json），数据结构如下：
{{
    "table_name": "<表名>",
    "projects": [
        {{
            "name": "定性项目名称",
            "categories": ["分类1", "分类2", "分类3"]
        }},
        {{
            "name": "定量项目名称",
            "unit": "单位"
        }}
    ]
}}"""

COMMON_NOTES = """- 每个 project 必须有 name 字段，以及 categories 或 unit 之一
- 如果没有可分析的项目，projects 设为 []"""


def _build_instruction(table_name: str) -> str:
    """根据表名构造表特定的 instruction（与 extract_table_info.py 逻辑一致）"""
    if "入组病例" in table_name:
        return f'请从 CRF 中提取"试验完成情况"中的"退出试验原因"相关信息。\n\n【提取要求】\n1. 找到 CRF 中"试验完成情况"或"研究完成情况"相关的页面\n2. 提取所有"退出试验原因"或"退出研究原因"的选项\n3. 每个退出原因作为一项，不要合并\n\n【输出格式】\n必须使用 write_table_json 工具保存结果（不要使用 write_json），数据结构如下：\n{{\n    "table_name": "{table_name}",\n    "projects": [\n        {{\n            "name": "退出试验原因",\n            "categories": ["原因1", "原因2", "原因3", "..."]\n        }}\n    ]\n}}\n\n注意：\n- 只提取退出原因的分类选项，不需要提取具体数据\n- 如果有"其他"选项，也要包含在内'
    elif "方案偏离" in table_name:
        return f'请从 CRF 中提取"试验方案偏离情况记录"中的"方案偏离类型"相关信息。\n\n【提取要求】\n1. 找到 CRF 中"试验方案偏离情况记录"或"方案偏离"相关的页面\n2. 提取所有"方案偏离类型"的选项\n3. 每个偏离类型作为一项，不要合并\n\n【输出格式】\n必须使用 write_table_json 工具保存结果（不要使用 write_json），数据结构如下：\n{{\n    "table_name": "{table_name}",\n    "projects": [\n        {{\n            "name": "方案偏离类型",\n            "categories": ["类型1", "类型2", "类型3", "..."]\n        }}\n    ]\n}}\n\n注意：\n- 只提取方案偏离类型的分类选项，不需要提取具体数据\n- 如果有"其他"选项，也要包含在内'
    else:
        prompt_table_name = table_name.replace("基线信息-", "").replace("基线信息", "")
        if not prompt_table_name.strip():
            prompt_table_name = table_name
        return f'请从 CRF 中提取"{prompt_table_name}"所需的分析项目。'


@router.post("/{project_id}/generate-prompts")
def generate_prompts(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """基于 tables.json 生成 prompts.json"""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.output_dir:
        raise HTTPException(400, "项目输出目录不存在")

    tables_file = os.path.join(p.output_dir, "tables.json")
    if not os.path.exists(tables_file):
        raise HTTPException(400, "tables.json 不存在，请先完成阶段一")

    with open(tables_file, "r", encoding="utf-8") as f:
        tables_data = json.load(f)

    tables = tables_data.get("tables", [])

    # 跳过的 category 关键词（与 batch_extract_tables.py 一致）
    skip_keywords = ["主要疗效终点", "器械缺陷", "不良事件", "实验室检查", "生命体征", "合并用药"]
    skip_names = ["各中心病例分布情况", "各中心人群划分情况"]

    items = []
    for t in tables:
        category = t.get("category", "")
        name = t.get("name", "")

        if any(kw in category for kw in skip_keywords):
            continue
        if any(skip_name in name for skip_name in skip_names):
            continue

        items.append({
            "name": name,
            "category": category,
            "instruction": _build_instruction(name),
            "enabled": True,
        })

    prompts_data = {
        "common": {
            "extract_rules": COMMON_EXTRACT_RULES,
            "output_format": COMMON_OUTPUT_FORMAT,
            "notes": COMMON_NOTES,
        },
        "items": items,
    }

    prompts_file = os.path.join(p.output_dir, "prompts.json")
    with open(prompts_file, "w", encoding="utf-8") as f:
        json.dump(prompts_data, f, ensure_ascii=False, indent=2)

    p.phase = "prompts"
    db.commit()

    return prompts_data


@router.get("/{project_id}/prompts")
def get_prompts(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """读取 prompts.json"""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.output_dir:
        raise HTTPException(400, "项目输出目录不存在")

    prompts_file = os.path.join(p.output_dir, "prompts.json")
    if not os.path.exists(prompts_file):
        raise HTTPException(404, "prompts.json 不存在，请先生成 prompts")

    with open(prompts_file, "r", encoding="utf-8") as f:
        return json.load(f)


@router.put("/{project_id}/prompts")
def update_prompts(project_id: int, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """保存修改后的 prompts.json"""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.output_dir:
        raise HTTPException(400, "项目输出目录不存在")

    prompts_file = os.path.join(p.output_dir, "prompts.json")
    with open(prompts_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {"message": "保存成功"}


# ===== Table Info 端点（审核编辑页面用） =====

@router.get("/{project_id}/table-info")
def list_table_info(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """列出 05_表格信息/ 下所有表格 JSON"""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")

    info_dir = os.path.join(p.output_dir, "05_表格信息")
    if not os.path.exists(info_dir):
        return {"tables": []}

    # 读取 tables.json 获取排序顺序
    tables_json_path = os.path.join(p.output_dir, "tables.json")
    order_map = {}
    if os.path.exists(tables_json_path):
        with open(tables_json_path, "r", encoding="utf-8") as f:
            tables_data = json.load(f)
        for t in tables_data.get("tables", []):
            order_map[t["name"]] = t.get("index", 999)

    result = []
    for fname in sorted(os.listdir(info_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(info_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            table_name = data.get("table_name", fname.replace(".json", ""))
            result.append({
                "filename": fname,
                "table_name": table_name,
                "projects": data.get("projects", []),
                "sort_order": order_map.get(table_name, 999),
            })
        except Exception:
            continue

    # 按 tables.json 中的顺序排序
    result.sort(key=lambda x: x["sort_order"])
    return {"tables": result}


class UpdateTableInfoRequest(BaseModel):
    projects: list[dict]


@router.put("/{project_id}/table-info/{filename}")
def update_table_info(
    project_id: int,
    filename: str,
    req: UpdateTableInfoRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存修改后的单个表格 JSON"""
    p = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not p:
        raise HTTPException(404, "项目不存在")

    info_dir = os.path.join(p.output_dir, "05_表格信息")
    fpath = os.path.join(info_dir, filename)

    if not os.path.exists(fpath):
        raise HTTPException(404, "表格文件不存在")

    # 读取原文件获取 table_name
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["projects"] = req.projects

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {"message": "保存成功", "filename": filename}
