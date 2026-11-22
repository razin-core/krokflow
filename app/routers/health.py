"""Healthcheck router."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from app.db import get_db
from app.schemas import HealthOut
from app.services.catalog_service import get_health_stats

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> HealthOut:
    return get_health_stats(conn)
