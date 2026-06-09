from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import get_current_user, get_project
from app.services import dmp_orchestrator

router = APIRouter(dependencies=[Depends(get_current_user)])


class ChatRequest(BaseModel):
    message: str


@router.post("/clear")
async def clear_session(request: Request, project: str = Depends(get_project)):
    import os
    ws_dir = dmp_orchestrator._ws_project_dir(request.state.workspace, project)
    os.makedirs(ws_dir, exist_ok=True)
    dmp_orchestrator.clear_session(ws_dir)
    return {"status": "ok"}


@router.post("/send")
async def send_message(body: ChatRequest, request: Request, project: str = Depends(get_project)):
    ws_dir = dmp_orchestrator._ws_project_dir(request.state.workspace, project)
    return StreamingResponse(
        dmp_orchestrator.send_message(ws_dir, body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/continue-dmp")
async def continue_dmp(request: Request, project: str = Depends(get_project)):
    ws_dir = dmp_orchestrator._ws_project_dir(request.state.workspace, project)
    return StreamingResponse(
        dmp_orchestrator.continue_dmp(ws_dir, project),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/start-dmp")
async def start_dmp(request: Request, project: str = Depends(get_project)):
    ws_dir = dmp_orchestrator._ws_project_dir(request.state.workspace, project)
    return StreamingResponse(
        dmp_orchestrator.start_dmp(ws_dir, project),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
