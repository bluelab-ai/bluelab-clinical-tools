import os
import uuid
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from app.dependencies import get_current_user
from app.models import User
from app.config import FILES_DIR

router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".json", ".md"}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: str = Form("sap"),
    current_user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式: {ext}")

    # Save to user-specific directory
    user_dir = os.path.join(FILES_DIR, str(current_user.id))
    os.makedirs(user_dir, exist_ok=True)

    # Generate unique filename
    unique_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(user_dir, unique_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # Return the relative path for later use
    rel_path = os.path.relpath(file_path, os.path.dirname(FILES_DIR))
    return {"filename": file.filename, "path": rel_path, "size": len(content)}
