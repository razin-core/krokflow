"""Catalog and FTS5 search endpoints."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.db import get_db
from app.schemas import SearchResponse, SubjectsResponse
from app.services.auth_service import OptionalUserDep
from app.services.catalog_service import list_subjects
from app.services.search_service import search_questions

router = APIRouter(tags=["catalog"])


@router.get("/subjects", response_model=SubjectsResponse)
def get_subjects(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    user: OptionalUserDep,
) -> SubjectsResponse:
    return list_subjects(conn, user=user)


@router.get("/search", response_model=SearchResponse)
def search(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    user: OptionalUserDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    subject_id: Annotated[int | None, Query(ge=1)] = None,
    module_no: Annotated[int | None, Query(ge=1, le=20)] = None,
    source_tag: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 30,
) -> SearchResponse:
    return search_questions(
        conn,
        user=user,
        q=q,
        subject_id=subject_id,
        module_no=module_no,
        source_tag=source_tag,
        limit=limit,
    )
