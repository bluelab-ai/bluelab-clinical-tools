from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.services.dmp_orchestrator import DMPOrchestrator

router = APIRouter(dependencies=[Depends(get_current_user)])
orchestrator = DMPOrchestrator()


class ChatRequest(BaseModel):
    message: str


@router.post("/send")
async def send_message(body: ChatRequest, request: Request):
    return StreamingResponse(
        orchestrator.send_message(request.state.workspace, body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/start-dmp")
async def start_dmp(request: Request):
    return StreamingResponse(
        orchestrator.start_dmp(request.state.workspace),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
