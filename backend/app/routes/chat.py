"""Conversation endpoints share the exact same food service as the form."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.schemas.chat import ChatRequest
from app.services.session_service import SessionError

router = APIRouter(prefix="/api")


@router.get("/agent/status")
async def agent_status(request: Request):
    return request.app.state.food_agent.status()


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    try:
        return await request.app.state.food_agent.chat(body)
    except SessionError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from None
    except ValidationError:
        raise HTTPException(status_code=422, detail="筛选条件无效，请检查区域、金额、评分和数量。") from None
