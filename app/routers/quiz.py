"""Quiz session, answer verification, and question reveal endpoints."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from app.config import get_settings
from app.db import get_db
from app.schemas import (
    BookmarksListResponse,
    QuestionReportRequest,
    QuestionReportResponse,
    QuizAnswerRequest,
    QuizAnswerResponse,
    QuizSessionRequest,
    QuizSessionResponse,
    RevealOut,
)
from app.services.auth_service import OptionalUserDep
from app.services.quiz_service import (
    create_quiz_session,
    grade_quiz_answer,
    list_bookmarked_questions,
    reveal_question,
    submit_question_report,
)
from app.services.notify_service import send_report_telegram_alert
from app.services.rate_limit import extract_client_ip, report_ip_limiter

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


@router.get("/bookmarks", response_model=BookmarksListResponse)
def get_bookmarks_list(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    user: OptionalUserDep,
    ids: Annotated[str | None, Query(max_length=1500)] = None,
) -> BookmarksListResponse:
    parsed_ids: list[int] | None = None
    if ids:
        parsed_ids = []
        for token in ids.split(","):
            token = token.strip()
            if token.isdigit():
                parsed_ids.append(int(token))
    return list_bookmarked_questions(conn, user=user, ids=parsed_ids)


@router.post("/questions/{qid}/report", response_model=QuestionReportResponse)
def report_question_issue(
    qid: int,
    payload: QuestionReportRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    user: OptionalUserDep,
) -> QuestionReportResponse:
    report_ip_limiter.check_or_raise(extract_client_ip(request))
    try:
        result = submit_question_report(
            conn,
            question_id=qid,
            reason=payload.reason,
            comment=payload.comment,
            user=user,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not result.already_reported:
        settings = get_settings()
        if settings.telegram_bot_token and settings.admin_telegram_id:
            reporter = (
                f"@{user.username}"
                if (user and user.username)
                else (user.display_name if user else "guest")
            )
            background_tasks.add_task(
                send_report_telegram_alert,
                bot_token=settings.telegram_bot_token,
                chat_id=settings.admin_telegram_id,
                report_id=result.id,
                question_id=result.question_id,
                reason=result.reason,
                comment=payload.comment,
                reporter=reporter,
            )

    return result
