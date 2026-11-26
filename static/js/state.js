/** Centralized client-side state + guest localStorage buffer for seamless Auth transition. */

const GUEST_BUFFER_KEY = "krok-guest-buffer";

export function loadGuestBuffer() {
  try {
    const raw = localStorage.getItem(GUEST_BUFFER_KEY);
    if (!raw) return { attempts: {}, bookmarks: [] };
    const parsed = JSON.parse(raw);
    return {
      attempts: parsed && typeof parsed.attempts === "object" && parsed.attempts ? parsed.attempts : {},
      bookmarks: Array.isArray(parsed?.bookmarks) ? parsed.bookmarks.map(Number).filter(Boolean) : [],
    };
  } catch {
    return { attempts: {}, bookmarks: [] };
  }
}

export function saveGuestBuffer(buf) {
  try {
    localStorage.setItem(GUEST_BUFFER_KEY, JSON.stringify(buf));
  } catch {
    // Ignore storage quota errors
  }
}

export function clearGuestBuffer() {
  try {
    localStorage.removeItem(GUEST_BUFFER_KEY);
  } catch {
    // Ignore
  }
}

export function clearGuestAttemptsOnly() {
  const buf = loadGuestBuffer();
  buf.attempts = {};
  saveGuestBuffer(buf);
}

export function recordGuestAttempt(questionId, isCorrect, quality = null) {
  const buf = loadGuestBuffer();
  const key = String(questionId);
  buf.attempts[key] = {
    question_id: Number(questionId),
    is_correct: Boolean(isCorrect),
    quality: quality ?? (isCorrect ? 4 : 1),
    ts: Math.floor(Date.now() / 1000),
  };
  saveGuestBuffer(buf);
}

export function toggleGuestBookmark(questionId) {
  const qid = Number(questionId);
  const buf = loadGuestBuffer();
  const idx = buf.bookmarks.indexOf(qid);
  let bookmarked;
  if (idx >= 0) {
    buf.bookmarks.splice(idx, 1);
    bookmarked = false;
  } else {
    buf.bookmarks.push(qid);
    bookmarked = true;
  }
  saveGuestBuffer(buf);
  return bookmarked;
}

export function hasPendingGuestSync() {
  const buf = loadGuestBuffer();
  return Object.keys(buf.attempts).length > 0 || buf.bookmarks.length > 0;
}

export const state = {
  screen: "dashboard", // 'dashboard' | 'mode' | 'quiz' | 'flashcards' | 'exam' | 'exam-results' | 'profile' | 'bookmarks'
  health: null,
  auth: {
    enabled: false,
    botUsername: null,
    authenticated: false,
    user: null,
  },
  stats: null,
  subjects: [],
  expandedModules: new Set([1]),

  // Bookmarks screen state
  bookmarks: null,
  bookmarksLoading: false,
  revealedBookmarkIds: new Map(),

  // Dashboard search state
  searchQuery: "",
  searchResponse: null,
  searchLoading: false,
  revealedSearchIds: new Map(), // qid -> RevealOut

  // Cascading selector state (Dashboard + Mode Selector)
  cascade: {
    subjectId: null, // null = all subjects, or numeric subject id
    sourceKind: "all", // 'all' | 'thematic' | 'booklets' | 'kkr' | 'exam_bank' | 'm5'
    itemKey: "all", // 'all' | 't:<topicId>' | 'tag:<sourceTag>' | 'multi'
    itemKeys: [], // selected keys when 1+ items checked via checkboxes
    totalTimeSec: null,
    questionTimeSec: null,
  },

  // Mode selection scope (Screen 2)
  selection: {
    subjectId: null,
    subjectTitle: "Усі предмети",
    moduleNo: null,
    topicId: null,
    topicIds: null,
    sourceTag: null,
    sourceTags: null,
    sourceKind: "all",
    limit: 20,
    totalTimeSec: null,
    questionTimeSec: null,
    hintsEnabled: false,
    title: "Усі предмети КРОК-1",
  },

  // Screen 3: Quiz Training state
  quiz: null, // { sessionId, title, questions, idx, answers, struck, showMarkers, xMode, finished }

  // Screen 4: Flashcards state
  cards: null, // { title, queue, idx, flipped, reveals, showMarkers, ratings, finished }

  // Screen 5: Exam simulator state
  exam: null, // { examId, title, questions, idx, selected, flagged, struck, remainingSec, startedMs, timerId, results, reviewFilter }
};
