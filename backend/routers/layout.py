"""GET/PUT /api/layout — thin wrapper around layout_store.

PUT broadcasts an `edition_dirty` event so connected browsers re-render.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import layout_store, ws_manager

router = APIRouter()


class LayoutPayload(BaseModel):
    priority: list[str] | None = None
    hidden: list[str] = Field(default_factory=list)
    ticker_items: list[str] | None = None


@router.get("/layout")
async def get_layout():
    return layout_store.get_state()


@router.put("/layout")
async def put_layout(payload: LayoutPayload):
    state: dict[str, Any] = layout_store.get_state()
    state["priority"] = payload.priority
    state["hidden"] = list(dict.fromkeys(payload.hidden))  # de-dupe, keep order
    state["ticker_items"] = payload.ticker_items
    for w in state["hidden"]:
        if w not in layout_store.ALL_WIDGETS:
            raise HTTPException(400, detail=f"unknown widget '{w}'")
    saved = layout_store.save_state(state, source="api:put_layout")
    await ws_manager.broadcast({"type": "edition_dirty", "reason": "api"})
    return saved


@router.post("/layout/reset")
async def reset_layout():
    saved = layout_store.save_state(dict(layout_store.DEFAULT_STATE), source="api:reset_layout")
    await ws_manager.broadcast({"type": "edition_dirty", "reason": "reset"})
    return saved
