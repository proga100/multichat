from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.types import Message, ProviderName, Role
from app.providers.base import ProviderCallError, ProviderConfigurationError
from app.providers.factory import make_provider

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatOnceRequest(BaseModel):
    prompt: str = Field(min_length=1)
    premium: bool = False


class ChatOnceResponse(BaseModel):
    provider: ProviderName
    model: str
    content: str


@router.post("/once")
async def chat_once(request: ChatOnceRequest) -> ChatOnceResponse:
    messages = [Message(role=Role.USER, content=request.prompt)]

    try:
        provider = make_provider(ProviderName.ANTHROPIC, premium=request.premium)
        content = await provider.complete(messages)
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderCallError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatOnceResponse(
        provider=provider.name,
        model=provider.model,
        content=content,
    )
