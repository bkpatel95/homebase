"""POST /api/chat — streams a Claude response as Server-Sent Events.

Request body:
  {
    "session_id": "<uuid>",
    "message":    "the user's message"
  }

Response: text/event-stream. Each event is one JSON object per `data:` line
(see chat.claude_client.stream_with_tools for the event vocabulary).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..chat import claude_client, session, system_prompt as sp
from ..chat.tools import TOOLS  # noqa: F401  (forces tool registration on import)
from ..routers.edition import get_edition

log = logging.getLogger("homebase.chat")

router = APIRouter()

CHAT_USER_MAX_LEN = 1500


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=4, max_length=80)
    message: str = Field(..., min_length=1, max_length=CHAT_USER_MAX_LEN)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


async def _yield_with_keepalive(gen: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """Wrap the model stream with a periodic keep-alive comment so proxies
    (cloudflared, nginx) don't time the connection out during a long thinking
    pause.
    """
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def pump():
        try:
            async for ev in gen:
                await queue.put(ev)
        finally:
            await queue.put(None)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if ev is None:
                return
            yield _sse(ev)
    finally:
        pump_task.cancel()


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return JSONResponse(
            {"error": "chat_unavailable",
             "detail": "ANTHROPIC_API_KEY is not configured on the server. Add it to prod/homebase/.env and restart the daily-bhavi container."},
            status_code=503,
        )

    sid = req.session_id
    user_text = req.message.strip()
    if not user_text:
        return JSONResponse({"error": "empty_message"}, status_code=400)

    # Build the conversation: persisted history + this new user turn.
    history = session.store.get(sid)
    user_message = {"role": "user", "content": user_text}
    messages = history + [user_message]
    # Pre-record the user turn — even if the model fails, we keep history.
    session.store.append(sid, user_message)

    # Compile the latest edition so the system prompt knows current state.
    edition = await get_edition()

    system_text = sp.build_system_prompt(mood=edition.get("mood", "midday"), edition=edition)
    model = claude_client.pick_model(user_text)
    log.info("chat: session=%s model=%s msg=%r", sid[:8], model, user_text[:80])

    async def event_source() -> AsyncIterator[str]:
        captured = list(messages)  # claude_client mutates this
        try:
            async for ev in _yield_with_keepalive(
                claude_client.stream_with_tools(
                    system_prompt=system_text,
                    messages=captured,
                    model=model,
                )
            ):
                yield ev
        finally:
            # Persist any assistant turns + tool_result blocks (everything after
            # the initial user message we already appended).
            new_turns = captured[len(history) + 1:]
            for m in new_turns:
                session.store.append(sid, m)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # tell nginx not to buffer the SSE stream
            "Connection": "keep-alive",
        },
    )


@router.delete("/chat/{session_id}")
async def clear_session(session_id: str):
    session.store.clear(session_id)
    return {"ok": True}


@router.get("/chat/{session_id}")
async def get_session(session_id: str):
    msgs = session.store.get(session_id)
    # Return only the textual content (skip tool_use / tool_result blocks)
    # so the frontend can rehydrate the visible transcript.
    visible: list[dict[str, Any]] = []
    for m in msgs:
        content = m.get("content")
        if isinstance(content, str):
            visible.append({"role": m["role"], "text": content})
        elif isinstance(content, list):
            text = "".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
            if text:
                visible.append({"role": m["role"], "text": text})
    return {"messages": visible}
