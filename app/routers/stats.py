"""Authenticated student analytics, SM-2 progress sync, and bookmarks endpoints."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.db import get_db
from app.schemas import (
    BookmarkRequest,
    BookmarkResponse,
    FlashcardRateRequest,
    FlashcardRateResponse,
    GuestSyncRequest,
    GuestSyncResponse,
    UserStatsOut,
)
from app.services.auth_service import CurrentUserDep
from app.services.sm2_service import (
    get_user_stats,
    merge_guest_progress,
    record_question_progress,
    set_bookmark,
)

router = APIRouter(tags=["stats"])


@router.get("/stats/me", response_model=UserStatsOut)
def get_my_stats(
    user: CurrentUserDep,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> UserStatsOut:
    return get_user_stats(conn, user)


@router.post("/stats/merge-guest", response_model=GuestSyncResponse)
def sync_guest_progress(
    payload: GuestSyncRequest,
    user: CurrentUserDep,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> GuestSyncResponse:
    res = merge_guest_progress(
        conn,
        user_id=user.id,
        attempts=payload.attempts,
        bookmarks=payload.bookmarks,
    )
    return GuestSyncResponse(**res)


@router.post("/flashcards/rate", response_model=FlashcardRateResponse)
def rate_flashcard_sm2(
    payload: FlashcardRateRequest,
    user: CurrentUserDep,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> FlashcardRateResponse:
    exists = conn.execute(
        "SELECT 1 FROM questions WHERE id = ? AND status = 'verified'",
        (payload.question_id,),
    ).fetchone()
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Питання не знайдено")

    res = record_question_progress(
        conn,
        user_id=user.id,
        question_id=payload.question_id,
        is_correct=(payload.quality >= 3),
        quality=payload.quality,
    )
    return FlashcardRateResponse(
        question_id=payload.question_id,
        saved=True,
        interval_days=float(res["interval_days"]),
        reps=int(res["reps"]),
        ease_factor=float(res["ease_factor"]),
        next_review_ts=int(res["next_review_ts"]),
    )


@router.post("/questions/{qid}/bookmark", response_model=BookmarkResponse)
def toggle_question_bookmark(
    qid: int,
    user: CurrentUserDep,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    payload: BookmarkRequest | None = None,
) -> BookmarkResponse:
    try:
        state = set_bookmark(
            conn,
            user_id=user.id,
            question_id=qid,
            bookmarked=(payload.bookmarked if payload is not None else None),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return BookmarkResponse(question_id=qid, bookmarked=state)
