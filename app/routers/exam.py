"""KROK-1 exam simulator endpoints."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.db import get_db
from app.schemas import (
    ExamStartRequest,
    ExamStartResponse,
    ExamSubmitRequest,
    ExamSubmitResponse,
)
from app.services.auth_service import OptionalUserDep
from app.services.exam_service import start_exam, submit_exam

router = APIRouter(tags=["exam"])


@router.post("/exam/start", response_model=ExamStartResponse)
def exam_start(
    payload: ExamStartRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> ExamStartResponse:
    return start_exam(conn, payload)


@router.post("/exam/submit", response_model=ExamSubmitResponse)
def exam_submit(
    payload: ExamSubmitRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    user: OptionalUserDep,
) -> ExamSubmitResponse:
    try:
        return submit_exam(conn, payload, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
