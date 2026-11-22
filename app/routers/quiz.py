"""Quiz session, answer verification, and question reveal endpoints."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.db import get_db
from app.schemas import (
    ExplanationOut,
    QuizAnswerRequest,
    QuizAnswerResponse,
    QuizSessionRequest,
    QuizSessionResponse,
    RevealOut,
)
from app.services.auth_service import OptionalUserDep
from app.services.explain_service import get_or_generate_explanation
from app.services.quiz_service import (
    create_quiz_session,
    grade_quiz_answer,
    reveal_question,
)
from app.services.rate_limit import explain_ip_limiter, extract_client_ip

router = APIRouter(tags=["quiz"])


@router.post("/quiz/session", response_model=QuizSessionResponse)
def start_quiz_session(
    payload: QuizSessionRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    user: OptionalUserDep,
) -> QuizSessionResponse:
    return create_quiz_session(conn, payload, user=user)


@router.post("/quiz/answer", response_model=QuizAnswerResponse)
def check_quiz_answer(
    payload: QuizAnswerRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    user: OptionalUserDep,
) -> QuizAnswerResponse:
    try:
        return grade_quiz_answer(
            conn,
            payload.question_id,
            payload.selected_option_id,
            user=user,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/questions/{qid}/reveal", response_model=RevealOut)
def get_question_reveal(
    qid: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    salt: Annotated[str | None, Query(max_length=32)] = None,
) -> RevealOut:
    try:
        return reveal_question(conn, qid, salt=salt)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/questions/{qid}/explain", response_model=ExplanationOut)
def explain_question(
    qid: int,
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    user: OptionalUserDep,
) -> ExplanationOut:
    explain_ip_limiter.check_or_raise(extract_client_ip(request))
    return get_or_generate_explanation(conn, qid=qid, user=user)
