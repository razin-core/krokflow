"""Pydantic v2 request and response schemas for KROK Trainer API v1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    verified_questions: int
    needs_review_questions: int
    subjects_count: int
    topics_count: int
    cached_explanations: int = 0
    telegram_auth_enabled: bool = False


class UserOut(BaseModel):
    id: int
    tg_id: int
    username: str
    display_name: str
    photo_url: str
    role: str


class AuthStatusOut(BaseModel):
    enabled: bool
    bot_username: str
    authenticated: bool
    user: UserOut | None = None


class TelegramAuthRequest(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class AuthResponseOut(BaseModel):
    authenticated: bool
    user: UserOut | None = None


class TopicOut(BaseModel):
    id: int
    module_no: int
    title_uk: str
    question_count: int
    attempted_count: int = 0
    progress_pct: float = 0.0
    accuracy_pct: float = 0.0
    due_count: int = 0


class ModuleOut(BaseModel):
    module_no: int
    title_uk: str
    question_count: int
    attempted_count: int = 0
    progress_pct: float = 0.0
    accuracy_pct: float = 0.0
    due_count: int = 0
    topics: list[TopicOut]


class SourceTagCount(BaseModel):
    tag: str
    count: int


class SubjectOut(BaseModel):
    id: int
    slug: str
    title_uk: str
    icon: str
    total_questions: int
    kkr_questions: int
    attempted_count: int = 0
    progress_pct: float = 0.0
    accuracy_pct: float = 0.0
    due_count: int = 0
    source_tags: list[SourceTagCount]
    modules: list[ModuleOut]


class SubjectsResponse(BaseModel):
    subjects: list[SubjectOut]


class OptionOut(BaseModel):
    option_id: str
    text: str


class ExplanationOut(BaseModel):
    markers: list[str]
    anchor_uk: str
    explanation_uk: str
    distractors_uk: str
    model_id: str = ""


class QuestionOut(BaseModel):
    id: int
    subject_id: int
    subject_title: str
    module_no: int
    topic_id: int | None
    topic_title: str | None
    stem: str
    options: list[OptionOut]
    source_tags: list[str]
    shuffle_salt: str
    bookmarked: bool = False
    markers: list[str] = Field(default_factory=list)


class SearchItemOut(QuestionOut):
    matched_in_options: bool = False


class SearchResponse(BaseModel):
    query: str
    query_terms: list[str]
    elapsed_ms: float
    total: int
    items: list[SearchItemOut]


class RevealOut(BaseModel):
    question_id: int
    correct_text: str
    correct_option_id: str | None = None
    explanation: ExplanationOut | None = None


class QuizSessionRequest(BaseModel):
    mode: Literal["train", "hints", "flashcards", "mistakes", "smart_mix", "weak_topics", "bookmarks"] = "train"
    subject_id: int | None = None
    module_no: int | None = None
    topic_id: int | None = None
    topic_ids: list[int] | None = None
    question_ids: list[int] | None = None
    source_tag: str | None = None
    source_tags: list[str] | None = None
    limit: int = Field(default=20, ge=1, le=150)
    hints_enabled: bool = False


class QuizSessionResponse(BaseModel):
    session_id: str
    mode: str
    hints_enabled: bool = False
    total_questions: int
    questions: list[QuestionOut]


class QuizAnswerRequest(BaseModel):
    question_id: int
    selected_option_id: str


class QuizAnswerResponse(BaseModel):
    question_id: int
    is_correct: bool
    selected_option_id: str
    correct_option_id: str
    correct_text: str
    explanation: ExplanationOut | None = None
    sm2_saved: bool = False
    next_review_ts: int | None = None


class FlashcardRateRequest(BaseModel):
    question_id: int
    quality: Literal[1, 3, 5]


class FlashcardRateResponse(BaseModel):
    question_id: int
    saved: bool
    interval_days: float
    reps: int
    ease_factor: float
    next_review_ts: int


class BookmarkRequest(BaseModel):
    bookmarked: bool | None = None


class BookmarkResponse(BaseModel):
    question_id: int
    bookmarked: bool


class BookmarksListResponse(BaseModel):
    total: int
    items: list[QuestionOut]


class ExamStartRequest(BaseModel):
    subject_id: int | None = None
    module_no: int | None = None
    topic_id: int | None = None
    topic_ids: list[int] | None = None
    source_tag: str | None = None
    source_tags: list[str] | None = None
    question_count: int = Field(default=150, ge=5, le=150)


class ExamStartResponse(BaseModel):
    exam_id: str
    started_ts: int
    duration_sec: int
    pass_threshold_pct: int = 64
    total_questions: int
    questions: list[QuestionOut]


class ExamAnswerItem(BaseModel):
    question_id: int
    selected_option_id: str | None = None


class ExamSubmitRequest(BaseModel):
    exam_id: str
    duration_sec: int = Field(ge=0, le=36000)
    answers: list[ExamAnswerItem]
    subject_id: int | None = None
    mode: Literal["exam_150", "subject_mock", "weak_blitz"] = "exam_150"


class TopicBreakdownItem(BaseModel):
    topic_id: int | None
    module_no: int
    title_uk: str
    total: int
    correct: int
    accuracy_pct: float
    band: Literal["red", "amber", "green"]


class ExamReviewItem(BaseModel):
    question_id: int
    stem: str
    selected_text: str | None
    correct_text: str
    is_correct: bool
    topic_title: str | None
    source_tags: list[str]


class ExamSubmitResponse(BaseModel):
    exam_id: str
    total_questions: int
    answered_count: int
    correct_count: int
    score_pct: float
    passed: bool
    pass_threshold_pct: int = 64
    duration_sec: int
    saved_to_profile: bool = False
    breakdown: list[TopicBreakdownItem]
    weakest_topic_ids: list[int]
    review_items: list[ExamReviewItem]


class GuestAttemptItem(BaseModel):
    question_id: int
    is_correct: bool
    quality: int | None = Field(default=None, ge=0, le=5)
    ts: int | None = None


class GuestSyncRequest(BaseModel):
    attempts: list[GuestAttemptItem] = Field(default_factory=list)
    bookmarks: list[int] = Field(default_factory=list)


class GuestSyncResponse(BaseModel):
    merged_attempts: int
    merged_bookmarks: int


class ResetStatsRequest(BaseModel):
    keep_bookmarks: bool = True


class ResetStatsResponse(BaseModel):
    reset: bool = True
    deleted_progress_rows: int
    reset_bookmarked_rows: int
    deleted_exam_sessions: int


ReportReason = Literal["wrong_key", "text_error", "duplicate", "other"]


class QuestionReportRequest(BaseModel):
    reason: ReportReason
    comment: str = Field(default="", max_length=500)


class QuestionReportResponse(BaseModel):
    id: int
    question_id: int
    reason: ReportReason
    status: str
    already_reported: bool = False


class TopicProgressStatOut(BaseModel):
    topic_id: int
    module_no: int
    subject_title: str
    title_uk: str
    total_questions: int
    attempted_questions: int
    progress_pct: float
    accuracy_pct: float
    due_count: int
    band: Literal["red", "amber", "green"]


class WeakTopicOut(BaseModel):
    topic_id: int
    module_no: int
    title_uk: str
    accuracy_pct: float
    wrong_cnt: int


class ExamHistoryItemOut(BaseModel):
    id: int
    mode: str
    total_q: int
    correct_q: int
    score_pct: float
    duration_sec: int
    finished_ts: int


class UserStatsSummaryOut(BaseModel):
    total_verified: int
    attempted_count: int
    total_correct: int
    total_wrong: int
    overall_accuracy_pct: float
    due_count: int
    mistakes_count: int
    bookmarked_count: int


class UserStatsOut(BaseModel):
    user: UserOut
    summary: UserStatsSummaryOut
    topic_map: list[TopicProgressStatOut]
    weakest_topics: list[WeakTopicOut]
    exam_history: list[ExamHistoryItemOut]
    bookmarked_questions: list[dict]
