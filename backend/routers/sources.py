"""Sources / connectors management endpoints.

    GET    /api/sources                  → list every connector + its status
    GET    /api/sources/{id}             → single connector snapshot
    POST   /api/sources/{id}/configure   → save the connector's config dict
    POST   /api/sources/{id}/test        → run test_connection() with current config
    DELETE /api/sources/{id}             → clear the connector's stored config

Every mutating endpoint broadcasts an `edition_dirty` event so connected
browsers refresh.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import connectors, ws_manager

router = APIRouter()


def _describe_one(connector_id: str) -> dict[str, Any]:
    for s in connectors.describe_all():
        if s["id"] == connector_id:
            return s
    raise HTTPException(404, detail=f"unknown connector '{connector_id}'")


@router.get("/sources")
async def list_sources():
    return {"sources": connectors.describe_all()}


@router.get("/sources/{connector_id}")
async def get_source(connector_id: str):
    return _describe_one(connector_id)


class ConfigurePayload(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


@router.post("/sources/{connector_id}/configure")
async def configure_source(connector_id: str, payload: ConfigurePayload):
    c = connectors.get_connector(connector_id)
    if not c:
        raise HTTPException(404, detail=f"unknown connector '{connector_id}'")

    schema_fields = {f.name for f in c.config_schema}
    unknown = [k for k in payload.config if k not in schema_fields]
    if unknown:
        raise HTTPException(400, detail=f"unknown fields for {connector_id}: {unknown}")

    connectors.store.save_config(connector_id, payload.config)
    await ws_manager.broadcast(
        {
            "type": "edition_dirty",
            "reason": "sources",
            "connector_id": connector_id,
            "action": "configure",
        }
    )
    return _describe_one(connector_id)


@router.post("/sources/{connector_id}/test")
async def test_source(connector_id: str):
    c = connectors.get_connector(connector_id)
    if not c:
        raise HTTPException(404, detail=f"unknown connector '{connector_id}'")
    result = await connectors.test_connector(connector_id)
    return {"result": result, "source": _describe_one(connector_id)}


@router.delete("/sources/{connector_id}")
async def delete_source(connector_id: str):
    c = connectors.get_connector(connector_id)
    if not c:
        raise HTTPException(404, detail=f"unknown connector '{connector_id}'")
    removed = connectors.store.delete(connector_id)
    if removed:
        await ws_manager.broadcast(
            {
                "type": "edition_dirty",
                "reason": "sources",
                "connector_id": connector_id,
                "action": "delete",
            }
        )
    return {"removed": removed, "source": _describe_one(connector_id)}
