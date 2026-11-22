/** Fetch wrapper for KROK Trainer API v1. */

async function requestJson(url, options = {}) {
  const resp = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const err = await resp.json();
      if (err && err.detail) detail = String(err.detail);
    } catch {
      // ignore non-json error body
    }
    throw new Error(detail);
  }
  return resp.json();
}

export const api = {
  getHealth: () => requestJson("/api/v1/health"),
  getAuthStatus: () => requestJson("/api/v1/auth/status"),
  telegramLogin: (tgUser) =>
    requestJson("/api/v1/auth/telegram", { method: "POST", body: JSON.stringify(tgUser) }),
  logout: () => requestJson("/api/v1/auth/logout", { method: "POST" }),
  getSubjects: () => requestJson("/api/v1/subjects"),
  searchQuestions: ({ q, subjectId, moduleNo, sourceTag, limit = 30 }) => {
    const params = new URLSearchParams({ q, limit: String(limit) });
    if (subjectId != null) params.set("subject_id", String(subjectId));
    if (moduleNo != null) params.set("module_no", String(moduleNo));
    if (sourceTag) params.set("source_tag", sourceTag);
    return requestJson(`/api/v1/search?${params.toString()}`);
  },
  startQuizSession: (payload) =>
    requestJson("/api/v1/quiz/session", { method: "POST", body: JSON.stringify(payload) }),
  submitQuizAnswer: (questionId, selectedOptionId) =>
    requestJson("/api/v1/quiz/answer", {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, selected_option_id: selectedOptionId }),
    }),
  revealQuestion: (questionId, salt = null) => {
    const q = salt ? `?salt=${encodeURIComponent(salt)}` : "";
    return requestJson(`/api/v1/questions/${questionId}/reveal${q}`);
  },
  explainQuestion: (questionId) =>
    requestJson(`/api/v1/questions/${questionId}/explain`, { method: "POST" }),
  startExam: (payload) =>
    requestJson("/api/v1/exam/start", { method: "POST", body: JSON.stringify(payload) }),
  submitExam: (payload) =>
    requestJson("/api/v1/exam/submit", { method: "POST", body: JSON.stringify(payload) }),
  getMyStats: () => requestJson("/api/v1/stats/me"),
  syncGuestProgress: (payload) =>
    requestJson("/api/v1/stats/merge-guest", { method: "POST", body: JSON.stringify(payload) }),
  rateFlashcard: (questionId, quality) =>
    requestJson("/api/v1/flashcards/rate", {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, quality }),
    }),
  toggleBookmark: (questionId, bookmarked) =>
    requestJson(`/api/v1/questions/${questionId}/bookmark`, {
      method: "POST",
      body: JSON.stringify({ bookmarked }),
    }),
};
