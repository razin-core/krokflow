/** Main KrokFlow SPA controller covering all MVP & Phase 2 screens. */

import { api } from "./api.js?v=2.2.1";
import { appendHighlightedText, clear, el, setupDialogLightDismiss } from "./dom.js?v=2.2.1";
import {
  clearGuestBuffer,
  hasPendingGuestSync,
  loadGuestBuffer,
  recordGuestAttempt,
  state,
  toggleGuestBookmark,
} from "./state.js?v=2.2.1";
import { initThemeToggle } from "./theme.js?v=2.2.1";

const LETTERS = ["A", "B", "C", "D", "E"];
const mainEl = document.getElementById("app-main");
const announcerEl = document.getElementById("live-announcer");
const examNavDialog = document.getElementById("exam-nav-dialog");
const examConfirmDialog = document.getElementById("exam-confirm-dialog");
const infoDialog = document.getElementById("info-dialog");
const authDialog = document.getElementById("auth-dialog");

let searchTimer = null;

function announce(msg) {
  if (!announcerEl) return;
  announcerEl.textContent = "";
  requestAnimationFrame(() => {
    announcerEl.textContent = msg;
  });
}

function setDocumentTitle(prefix) {
  document.title = `${prefix} · KrokFlow`;
}

function formatDuration(sec) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function showInfoDialog(title, paragraphsOrNodes) {
  const titleEl = document.getElementById("info-dialog-title");
  const bodyEl = document.getElementById("info-dialog-body");
  titleEl.textContent = title;
  clear(bodyEl);
  for (const item of paragraphsOrNodes) {
    if (typeof item === "string") {
      bodyEl.appendChild(el("p", { text: item }));
    } else {
      bodyEl.appendChild(item);
    }
  }
  infoDialog.showModal();
}

function showShortcutsModal() {
  const list = el("ul", { className: "kbd-list" }, [
    el("li", { className: "kbd-row" }, [el("span", { text: "Фокус у пошук бази" }), el("span", {}, [el("kbd", { text: "Ctrl" }), " / ", el("kbd", { text: "⌘" }), " + ", el("kbd", { text: "K" })])]),
    el("li", { className: "kbd-row" }, [el("span", { text: "Вибір варіанта відповіді" }), el("span", {}, [el("kbd", { text: "1–5" }), " або ", el("kbd", { text: "A–E" })])]),
    el("li", { className: "kbd-row" }, [el("span", { text: "Закреслити дистрактор (UWorld)" }), el("span", {}, [el("kbd", { text: "X" }), " потім ", el("kbd", { text: "1–5" })])]),
    el("li", { className: "kbd-row" }, [el("span", { text: "Підсвітити маркери КРОК (після відповіді)" }), el("span", {}, [el("kbd", { text: "H" })])]),
    el("li", { className: "kbd-row" }, [el("span", { text: "Наступне питання / перевернути картку" }), el("span", {}, [el("kbd", { text: "Enter" }), " / ", el("kbd", { text: "Space" })])]),
    el("li", { className: "kbd-row" }, [el("span", { text: "Самооцінка флешкартки" }), el("span", {}, [el("kbd", { text: "1" }), " ", el("kbd", { text: "2" }), " ", el("kbd", { text: "3" })])]),
  ]);
  showInfoDialog("Клавіатурні скорочення (ПК)", [list]);
}

function isQuestionBookmarked(q) {
  if (state.auth.authenticated) return Boolean(q.bookmarked);
  const buf = loadGuestBuffer();
  return buf.bookmarks.includes(Number(q.id));
}

function updateAuthHeaderPill() {
  const pill = document.getElementById("guest-pill-btn");
  const footerText = document.getElementById("site-footer-text");
  if (!pill) return;
  clear(pill);

  if (state.auth.authenticated && state.auth.user) {
    const u = state.auth.user;
    pill.classList.add("is-auth");
    pill.appendChild(el("span", { className: "guest-dot", "aria-hidden": "true" }));
    if (u.photo_url) {
      pill.appendChild(el("img", { className: "auth-avatar", src: u.photo_url, alt: "" }));
    }
    const label = u.username ? `@${u.username}` : u.display_name;
    const due = state.stats?.summary?.due_count || 0;
    pill.appendChild(el("span", { text: due > 0 ? `${label} · ${due}` : label }));
    if (footerText) {
      footerText.textContent = `KrokFlow v2.0 · Профіль ${label} · SM-2 хмарна синхронізація`;
    }
  } else {
    pill.classList.remove("is-auth");
    pill.appendChild(el("span", { className: "guest-dot", "aria-hidden": "true" }));
    pill.appendChild(el("span", { text: "Увійти · Telegram" }));
    if (footerText) {
      footerText.textContent = "KrokFlow v2.0 · База КРОК-1 · Гість (прогрес синхронізується після входу)";
    }
  }
}

async function refreshCatalogAndStats() {
  const tasks = [api.getSubjects()];
  if (state.auth.authenticated) {
    tasks.push(api.getMyStats());
  }
  const [catalog, stats] = await Promise.all(tasks);
  state.subjects = catalog.subjects;
  if (state.auth.authenticated && stats) {
    state.stats = stats;
  } else if (!state.auth.authenticated) {
    state.stats = null;
  }
  updateAuthHeaderPill();
}

async function syncGuestIfPending() {
  if (!state.auth.authenticated || !hasPendingGuestSync()) return;
  const buf = loadGuestBuffer();
  const attempts = Object.values(buf.attempts || {});
  const bookmarks = buf.bookmarks || [];
  if (!attempts.length && !bookmarks.length) return;
  try {
    const res = await api.syncGuestProgress({ attempts, bookmarks });
    clearGuestBuffer();
    announce(`Перенесено ${res.merged_attempts} відповідей та ${res.merged_bookmarks} закладок`);
  } catch {
    // Keep guest buffer intact for retry if network failed.
  }
}

window.onTelegramAuth = async (tgUser) => {
  try {
    const res = await api.telegramLogin(tgUser);
    state.auth.authenticated = true;
    state.auth.user = res.user;
    await syncGuestIfPending();
    await refreshCatalogAndStats();
    authDialog?.close();
    render();
    announce(`Вітаємо, ${res.user.display_name}! Профіль синхронізовано.`);
  } catch (err) {
    showInfoDialog("Помилка входу через Telegram", [err.message]);
  }
};

async function handleLogout() {
  try {
    await api.logout();
  } catch {
    // Ignore transient errors
  }
  state.auth.authenticated = false;
  state.auth.user = null;
  state.stats = null;
  if (state.screen === "profile") state.screen = "dashboard";
  await refreshCatalogAndStats();
  authDialog?.close();
  render();
  announce("Ви вийшли з профілю Telegram");
}

function openAuthDialog(contextHint = null) {
  if (state.auth.authenticated && !contextHint) {
    openProfile();
    return;
  }
  const titleEl = document.getElementById("auth-dialog-title");
  const bodyEl = document.getElementById("auth-dialog-body");
  if (!titleEl || !bodyEl || !authDialog) return;
  clear(bodyEl);

  if (state.auth.authenticated && state.auth.user) {
    titleEl.textContent = "Профіль Telegram";
    bodyEl.appendChild(el("p", { text: `Ви авторизовані як ${state.auth.user.display_name}${state.auth.user.username ? ` (@${state.auth.user.username})` : ""}.` }));
    bodyEl.appendChild(
      el("div", { className: "dialog-actions" }, [
        el("button", { type: "button", className: "btn btn-secondary", text: "Вийти", onClick: handleLogout }),
        el("button", { type: "button", className: "btn btn-primary", text: "Відкрити аналітику", onClick: () => { authDialog.close(); openProfile(); } }),
      ])
    );
    authDialog.showModal();
    return;
  }

  titleEl.textContent = "Вхід через Telegram";
  if (contextHint) {
    bodyEl.appendChild(el("p", { style: "margin:0", text: contextHint }));
  }
  bodyEl.appendChild(
    el("p", {
      className: "muted",
      style: "margin:0",
      text: "Авторизація без пароля зберігає ваш інтервальний графік SM-2, чергу помилок, закладки та історію іспитів 150 питань. Гостьовий прогрес із цього браузера перенесеться автоматично.",
    })
  );

  if (hasPendingGuestSync()) {
    const buf = loadGuestBuffer();
    const attCnt = Object.keys(buf.attempts).length;
    bodyEl.appendChild(
      el("div", {
        className: "badge badge-accent",
        text: `Буфер браузера: ${attCnt} відповідей і ${buf.bookmarks.length} закладок готові до переносу`,
      })
    );
  }

  if (state.auth.enabled && state.auth.botUsername) {
    const slot = el("div", { className: "tg-widget-slot" });
    const script = document.createElement("script");
    script.async = true;
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.dataset.telegramLogin = state.auth.botUsername;
    script.dataset.size = "large";
    script.dataset.radius = "12";
    script.dataset.onauth = "onTelegramAuth(user)";
    script.dataset.requestAccess = "write";
    slot.appendChild(script);
    bodyEl.appendChild(slot);
  } else {
    bodyEl.appendChild(
      el("div", { className: "explain-box" }, [
        el("strong", { text: "Telegram Login Widget очікує токен у .env" }),
        el("span", { text: "Адміністратору: додайте TELEGRAM_LOGIN_BOT_TOKEN та TELEGRAM_LOGIN_BOT_USERNAME у /home/ubuntu/krok_trainer/.env (після /setdomain krokflow.pp.ua у @BotFather)." }),
      ])
    );
  }

  authDialog.showModal();
}

async function handleBookmarkToggle(q, rerenderFn) {
  const nextState = !isQuestionBookmarked(q);
  if (!state.auth.authenticated) {
    const saved = toggleGuestBookmark(q.id);
    q.bookmarked = saved;
    rerenderFn();
    announce(saved ? "Додано в закладки браузера" : "Прибрано із закладок");
    return;
  }
  try {
    const res = await api.toggleBookmark(q.id, nextState);
    q.bookmarked = res.bookmarked;
    rerenderFn();
    announce(res.bookmarked ? "Збережено у закладки" : "Прибрано із закладок");
  } catch (err) {
    showInfoDialog("Помилка закладки", [err.message]);
  }
}

async function handleRequestAiExplanation(q, targetAnswerOrReveal, rerenderFn) {
  if (!state.auth.authenticated) {
    openAuthDialog("Онлайн AI-розбір доступний після входу через Telegram. Визначені клінічні маркери та «Якір КРОК» уже працюють безкоштовно.");
    return;
  }
  if (state.quiz?.explainingIds) state.quiz.explainingIds.add(q.id);
  rerenderFn();
  try {
    const exp = await api.explainQuestion(q.id);
    targetAnswerOrReveal.explanation = exp;
    if (exp.markers?.length) q.markers = exp.markers;
    announce("Розбір КРОК оновлено");
  } catch (err) {
    showInfoDialog("Пояснення КРОК", [err.message]);
  } finally {
    if (state.quiz?.explainingIds) state.quiz.explainingIds.delete(q.id);
    rerenderFn();
  }
}

// ---------- Navigation & Session Launchers ----------

function goDashboard() {
  stopExamTimer();
  state.screen = "dashboard";
  setDocumentTitle("Дашборд");
  render();
  if (state.auth.authenticated) {
    refreshCatalogAndStats().then(() => {
      if (state.screen === "dashboard") render();
    }).catch(() => {});
  }
}

function openProfile() {
  stopExamTimer();
  state.screen = "profile";
  setDocumentTitle("Профіль та аналітика");
  render();
  if (state.auth.authenticated) {
    refreshCatalogAndStats().then(() => {
      if (state.screen === "profile") render();
    }).catch(() => {});
  }
}

function openModeSelector(scope) {
  stopExamTimer();
  state.selection = {
    subjectId: scope.subjectId ?? null,
    subjectTitle: scope.subjectTitle ?? "Мікробіологія",
    moduleNo: scope.moduleNo ?? null,
    topicId: scope.topicId ?? null,
    topicIds: scope.topicIds ?? null,
    sourceTag: scope.sourceTag ?? null,
    limit: scope.limit ?? 20,
    hintsEnabled: Boolean(scope.hintsEnabled && state.auth.authenticated),
    title: scope.title ?? scope.subjectTitle ?? "Мікробіологія",
  };
  state.screen = "mode";
  setDocumentTitle(state.selection.title);
  render();
}

async function startTraining({
  mode = "train",
  subjectId = state.selection.subjectId,
  moduleNo = state.selection.moduleNo,
  topicId = state.selection.topicId,
  topicIds = state.selection.topicIds,
  sourceTag = state.selection.sourceTag,
  limit = state.selection.limit,
  hintsEnabled = Boolean(state.selection.hintsEnabled && state.auth.authenticated),
  title = state.selection.title,
} = {}) {
  try {
    const resp = await api.startQuizSession({
      mode,
      subject_id: subjectId,
      module_no: moduleNo,
      topic_id: topicId,
      topic_ids: topicIds,
      source_tag: sourceTag,
      limit,
      hints_enabled: Boolean(hintsEnabled || mode === "hints"),
    });
    if (!resp.questions.length) {
      const msg =
        mode === "mistakes"
          ? "У вас зараз немає активних помилок або прострочених повторень SM-2!"
          : "За цими фільтрами не знайдено верифікованих питань. Спробуйте скинути фільтр джерела або теми.";
      showInfoDialog("Порожня вибірка", [msg]);
      return;
    }
    state.quiz = {
      sessionId: resp.session_id,
      title,
      questions: resp.questions,
      idx: 0,
      answers: new Map(),
      struck: new Map(),
      hintsEnabled: Boolean(resp.hints_enabled),
      showMarkers: Boolean(resp.hints_enabled),
      explainingIds: new Set(),
      xMode: false,
      finished: false,
    };
    state.screen = "quiz";
    setDocumentTitle(`Тренування · ${title}`);
    render();
    announce(`Почато тренування: ${resp.questions.length} питань`);
  } catch (err) {
    if (err.message.includes("Telegram") || err.message.includes("Увійдіть")) {
      openAuthDialog(err.message);
      return;
    }
    showInfoDialog("Помилка запуску", [err.message]);
  }
}

async function startFlashcards() {
  try {
    const resp = await api.startQuizSession({
      mode: "flashcards",
      subject_id: state.selection.subjectId,
      module_no: state.selection.moduleNo,
      topic_id: state.selection.topicId,
      topic_ids: state.selection.topicIds,
      source_tag: state.selection.sourceTag,
      limit: state.selection.limit,
      hints_enabled: Boolean(state.selection.hintsEnabled && state.auth.authenticated),
    });
    if (!resp.questions.length) {
      showInfoDialog("Порожня вибірка", ["За цими фільтрами не знайдено верифікованих питань."]);
      return;
    }
    state.cards = {
      title: state.selection.title,
      queue: [...resp.questions],
      idx: 0,
      flipped: false,
      reveals: new Map(),
      hintsEnabled: Boolean(resp.hints_enabled),
      showMarkers: Boolean(resp.hints_enabled),
      ratings: { again: 0, hard: 0, good: 0 },
      finished: false,
    };
    state.screen = "flashcards";
    setDocumentTitle(`Флешкартки · ${state.selection.title}`);
    render();
    announce(`Флешкартки готові: ${resp.questions.length} карток`);
  } catch (err) {
    showInfoDialog("Помилка запуску", [err.message]);
  }
}

async function startExamSimulator({
  subjectId = null,
  moduleNo = null,
  sourceTag = null,
  questionCount = 150,
  title = "Симулятор іспиту КРОК-1",
} = {}) {
  try {
    const resp = await api.startExam({
      subject_id: subjectId,
      module_no: moduleNo,
      source_tag: sourceTag,
      question_count: questionCount,
    });
    if (!resp.questions.length) {
      showInfoDialog("Порожня вибірка", ["Недостатньо питань для старту симуляції іспиту."]);
      return;
    }
    stopExamTimer();
    state.exam = {
      examId: resp.exam_id,
      title,
      questions: resp.questions,
      idx: 0,
      selected: new Map(),
      flagged: new Set(),
      struck: new Map(),
      remainingSec: resp.duration_sec,
      totalDurationSec: resp.duration_sec,
      passThreshold: resp.pass_threshold_pct,
      startedMs: Date.now(),
      timerId: null,
      submitting: false,
      results: null,
      reviewFilter: "wrong",
    };
    state.screen = "exam";
    setDocumentTitle("Іспит КРОК-1");
    startExamTimer();
    render();
    announce(`Симулятор іспиту запущено: ${resp.total_questions} питань`);
  } catch (err) {
    showInfoDialog("Помилка запуску іспиту", [err.message]);
  }
}

function startExamTimer() {
  stopExamTimer();
  if (!state.exam) return;
  state.exam.timerId = setInterval(() => {
    if (!state.exam || state.screen !== "exam") {
      stopExamTimer();
      return;
    }
    state.exam.remainingSec = Math.max(0, state.exam.remainingSec - 1);
    const pill = document.getElementById("exam-timer-pill");
    if (pill) {
      pill.textContent = `⏱ ${formatDuration(state.exam.remainingSec)}`;
      pill.classList.toggle("is-low", state.exam.remainingSec <= 300);
    }
    if (state.exam.remainingSec === 0) {
      stopExamTimer();
      finalizeExam();
    }
  }, 1000);
}

function stopExamTimer() {
  if (state.exam && state.exam.timerId) {
    clearInterval(state.exam.timerId);
    state.exam.timerId = null;
  }
}

async function finalizeExam() {
  if (!state.exam || state.exam.submitting) return;
  state.exam.submitting = true;
  stopExamTimer();
  const elapsedSec = Math.max(1, Math.round((Date.now() - state.exam.startedMs) / 1000));
  const answers = state.exam.questions.map((q) => ({
    question_id: q.id,
    selected_option_id: state.exam.selected.get(q.id) || null,
  }));
  try {
    const res = await api.submitExam({
      exam_id: state.exam.examId,
      duration_sec: elapsedSec,
      answers,
    });
    state.exam.results = res;
    state.screen = "exam-results";
    setDocumentTitle(`Результат ${res.score_pct}%`);
    if (state.auth.authenticated) {
      refreshCatalogAndStats().catch(() => {});
    } else if (Array.isArray(res.review)) {
      for (const item of res.review) {
        if (item.selected_option_id) {
          recordGuestAttempt(item.question_id, item.is_correct);
        }
      }
    }
    render();
    announce(`Іспит завершено. Результат ${res.score_pct}%`);
  } catch (err) {
    state.exam.submitting = false;
    showInfoDialog("Помилка перевірки іспиту", [err.message]);
  }
}

// ---------- Screen 1: Dashboard ----------

function renderDashboard() {
  const root = el("div", { className: "stack-lg" });

  // Search box + instant FTS5 results
  const searchWrap = el("section", { className: "stack-sm" });
  const searchLabel = el("label", {
    for: "search-input",
    className: "visually-hidden",
    text: "Миттєвий пошук по базі тестів КРОК-1",
  });
  const searchInput = el("input", {
    id: "search-input",
    type: "search",
    className: "search-input",
    placeholder: "Пошук КРОК-1 за симптомом, збудником, реакцією…",
    value: state.searchQuery,
    autocomplete: "off",
    onInput: (e) => {
      state.searchQuery = e.target.value;
      clearTimeout(searchTimer);
      const q = state.searchQuery.trim();
      if (!q) {
        state.searchResponse = null;
        state.searchLoading = false;
        renderSearchResultsRegion();
        return;
      }
      state.searchLoading = true;
      searchTimer = setTimeout(async () => {
        try {
          const res = await api.searchQuestions({ q, limit: 30 });
          if (state.searchQuery.trim() === q) {
            state.searchResponse = res;
            state.searchLoading = false;
            renderSearchResultsRegion();
            announce(`Знайдено ${res.total} питань за ${res.elapsed_ms} мс`);
          }
        } catch (err) {
          state.searchLoading = false;
          state.searchResponse = { query: q, query_terms: [], elapsed_ms: 0, total: 0, items: [], error: err.message };
          renderSearchResultsRegion();
        }
      }, 140);
    },
  });

  const kbdHint = state.searchQuery ? null : el("span", { className: "search-kbd", text: "⌘K" });
  const clearBtn = state.searchQuery
    ? el("button", {
        type: "button",
        className: "search-clear-btn",
        "aria-label": "Очистити пошук",
        text: "✕",
        onClick: () => {
          state.searchQuery = "";
          state.searchResponse = null;
          render();
          document.getElementById("search-input")?.focus();
        },
      })
    : null;

  const searchBox = el("div", { className: "search-box" }, [
    el("span", { className: "search-icon", "aria-hidden": "true", text: "🔍" }),
    searchLabel,
    searchInput,
    kbdHint,
    clearBtn,
  ]);
  searchWrap.appendChild(searchBox);

  // Quick-jump subject/module pills (naurok.ua pattern)
  const subj = state.subjects[0];
  if (subj) {
    const pills = el("div", { className: "chips-row" });
    pills.appendChild(
      el(
        "button",
        {
          type: "button",
          className: "chip active",
          onClick: () => openModeSelector({ subjectId: subj.id, subjectTitle: subj.title_uk, title: subj.title_uk }),
        },
        [el("span", { text: `${subj.icon} ${subj.title_uk}` }), el("span", { className: "chip-count", text: subj.total_questions })]
      )
    );
    for (const mod of subj.modules) {
      if (mod.module_no === 4) continue; // KKR shown in dedicated pill below
      const shortLabel = mod.title_uk.replace(/^Модуль\s+\d+\s*·\s*/, "М" + mod.module_no + " · ");
      pills.appendChild(
        el(
          "button",
          {
            type: "button",
            className: "chip",
            onClick: () =>
              openModeSelector({
                subjectId: subj.id,
                subjectTitle: subj.title_uk,
                moduleNo: mod.module_no,
                title: mod.title_uk,
              }),
          },
          [el("span", { text: shortLabel }), el("span", { className: "chip-count", text: mod.question_count })]
        )
      );
    }
    if (subj.kkr_questions > 0) {
      pills.appendChild(
        el(
          "button",
          {
            type: "button",
            className: "chip",
            onClick: () =>
              openModeSelector({
                subjectId: subj.id,
                subjectTitle: subj.title_uk,
                sourceTag: "ККР",
                title: "ККР · Мікробіологія",
              }),
          },
          [el("span", { text: "🎯 Тільки ККР" }), el("span", { className: "chip-count", text: subj.kkr_questions })]
        )
      );
    }
    searchWrap.appendChild(pills);
  }

  const resultsRegion = el("div", { id: "search-results-region", className: "stack-sm" });
  searchWrap.appendChild(resultsRegion);
  root.appendChild(searchWrap);

  // Hero Quick-Start Card
  const verifiedCnt = state.health?.verified_questions ?? subj?.total_questions ?? 0;
  const reviewCnt = state.health?.needs_review_questions ?? 0;
  const hero = el("section", { className: "card hero-card" }, [
    el("div", { className: "row-between" }, [
      el("div", {}, [
        el("h1", { text: "KrokFlow · КРОК-1 / ЄДКІ" }),
        el("p", {
          className: "muted",
          style: "margin:0",
          text: "Чиста клінічна база з миттєвим FTS5-пошуком, Fisher-Yates перемішуванням, SM-2 та маркерами КРОК.",
        }),
      ]),
    ]),
    el("div", { className: "stat-badges" }, [
      el("span", { className: "badge badge-accent", text: `✓ ${verifiedCnt} верифіковано` }),
      el("span", { className: "badge badge-amber", text: `🛡️ Карантин PDF: ${reviewCnt}` }),
      el("span", { className: "badge", text: "🔀 A–E перемішуються щоразу" }),
    ]),
    state.auth.authenticated && state.stats?.summary
      ? el("div", { className: "kpi-grid" }, [
          el("div", { className: "kpi-card" }, [
            el("span", { className: "kpi-value", text: `${state.stats.summary.due_count}` }),
            el("span", { className: "kpi-label", text: "Повторити сьогодні (SM-2)" }),
          ]),
          el("div", { className: "kpi-card" }, [
            el("span", { className: "kpi-value", text: `${state.stats.summary.mistakes_count}` }),
            el("span", { className: "kpi-label", text: "Активні помилки" }),
          ]),
          el("div", { className: "kpi-card" }, [
            el("span", { className: "kpi-value", text: `${state.stats.summary.overall_accuracy_pct}%` }),
            el("span", { className: "kpi-label", text: "Загальна точність" }),
          ]),
          el("div", { className: "kpi-card" }, [
            el("span", { className: "kpi-value", text: `${state.stats.summary.bookmarked_count}` }),
            el("span", { className: "kpi-label", text: "Збережені закладки" }),
          ]),
        ])
      : null,
    el("div", { className: "hero-actions" }, [
      el("button", {
        type: "button",
        id: "hero-smart-btn",
        className: "btn btn-primary",
        text: "▶ Розумна сесія (20 питань)",
        onClick: () => startTraining({ mode: "smart_mix", limit: 20, title: "Розумна сесія · Мікс" }),
      }),
      el("button", {
        type: "button",
        id: "hero-exam-btn",
        className: "btn btn-secondary",
        text: "⏱ Симулятор іспиту (150)",
        onClick: () => startExamSimulator({ questionCount: 150, title: "Симулятор КРОК-1 (150)" }),
      }),
      el("button", {
        type: "button",
        id: "hero-mistakes-btn",
        className: "btn btn-secondary",
        text: state.stats?.summary?.due_count ? `🧠 Помилки / SM-2 (${state.stats.summary.due_count})` : "🧠 Помилки / SM-2",
        onClick: () =>
          state.auth.authenticated
            ? startTraining({ mode: "mistakes", limit: 25, title: "Помилки та повторення SM-2" })
            : openAuthDialog("Персональна черга помилок і повторень SM-2 працює після входу через Telegram."),
      }),
      el("button", {
        type: "button",
        id: "hero-weak-btn",
        className: "btn btn-secondary",
        text: "🔥 Закрити 3 слабкі теми",
        onClick: () =>
          state.auth.authenticated
            ? startTraining({ mode: "weak_topics", limit: 20, title: "Закрити 3 найслабші теми" })
            : openAuthDialog("Відпрацювання 3 найслабших тем за рейтингом SM-2 доступне після входу через Telegram."),
      }),
    ]),
  ]);
  root.appendChild(hero);

  const renderProgressPill = (obj) => {
    if (!state.auth.authenticated || (!obj.attempted_count && !obj.due_count)) return null;
    return el("span", { className: "mini-progress-wrap" }, [
      el("span", { className: "mini-progress-track" }, [
        el("span", { className: "mini-progress-fill", style: `width:${Math.min(100, obj.progress_pct || 0)}%` }),
      ]),
      el("span", {
        className: "muted",
        style: "font-size:12px",
        text: `${obj.progress_pct || 0}% (${obj.accuracy_pct || 0}%)`,
      }),
    ]);
  };

  // Subject & Collapsible Modules Catalog
  if (subj) {
    const subjCard = el("section", { className: "card subject-card" }, [
      el("div", { className: "row-between" }, [
        el("div", {}, [
          el("h2", { text: `${subj.icon} ${subj.title_uk}` }),
          el("p", {
            className: "muted",
            style: "margin:4px 0 0;font-size:13.5px",
            text: `${subj.total_questions} питань · ${subj.modules.length} модулі · дедуплікація по ККР`,
          }),
          renderProgressPill(subj),
        ]),
        el("button", {
          type: "button",
          className: "btn btn-primary btn-sm",
          text: "Обрати режим →",
          onClick: () => openModeSelector({ subjectId: subj.id, subjectTitle: subj.title_uk, title: subj.title_uk }),
        }),
      ]),
    ]);

    const modsWrap = el("div", { className: "stack-sm" });
    for (const mod of subj.modules) {
      const isExpanded = state.expandedModules.has(mod.module_no);
      const group = el("div", { className: "module-group" });
      const modMeta = el("div", { className: "question-actions" }, [
        renderProgressPill(mod),
        el("span", { className: "badge", text: `${mod.question_count} тестів` }),
      ]);
      const header = el(
        "button",
        {
          type: "button",
          className: "module-header",
          "aria-expanded": String(isExpanded),
          onClick: () => {
            if (state.expandedModules.has(mod.module_no)) {
              state.expandedModules.delete(mod.module_no);
            } else {
              state.expandedModules.add(mod.module_no);
            }
            render();
          },
        },
        [
          el("span", { text: `${isExpanded ? "▾" : "▸"} ${mod.title_uk}` }),
          modMeta,
        ]
      );
      group.appendChild(header);

      if (isExpanded) {
        const list = el("div", { className: "topics-list" });
        list.appendChild(
          el(
            "button",
            {
              type: "button",
              className: "topic-row",
              style: "font-weight:650",
              onClick: () =>
                openModeSelector({
                  subjectId: subj.id,
                  subjectTitle: subj.title_uk,
                  moduleNo: mod.module_no,
                  title: mod.title_uk,
                }),
            },
            [el("span", { text: `Усі питання: ${mod.title_uk}` }), el("span", { className: "muted", text: `${mod.question_count} →` })]
          )
        );
        for (const topic of mod.topics) {
          list.appendChild(
            el(
              "button",
              {
                type: "button",
                className: "topic-row",
                onClick: () =>
                  openModeSelector({
                    subjectId: subj.id,
                    subjectTitle: subj.title_uk,
                    moduleNo: mod.module_no,
                    topicId: topic.id,
                    title: topic.title_uk,
                  }),
              },
              [
                el("span", { text: topic.title_uk }),
                el("span", { className: "question-actions" }, [
                  renderProgressPill(topic),
                  el("span", { className: "muted", text: `${topic.question_count} →` }),
                ]),
              ]
            )
          );
        }
        group.appendChild(list);
      }
      modsWrap.appendChild(group);
    }
    subjCard.appendChild(modsWrap);
    root.appendChild(subjCard);
  }

  mainEl.appendChild(root);
  renderSearchResultsRegion();
}

function renderSearchResultsRegion() {
  const region = document.getElementById("search-results-region");
  if (!region) return;
  clear(region);

  const q = state.searchQuery.trim();
  if (!q) return;

  if (state.searchLoading) {
    region.appendChild(el("div", { className: "card muted", text: "Пошук у FTS5…" }));
    return;
  }

  const res = state.searchResponse;
  if (!res) return;

  if (res.error) {
    region.appendChild(el("div", { className: "card", text: `Помилка пошуку: ${res.error}` }));
    return;
  }

  region.appendChild(
    el("div", { className: "row-between" }, [
      el("span", { className: "muted", style: "font-size:13.5px", text: `Результати FTS5 для «${res.query}»: ${res.total}` }),
      el("span", { className: "badge badge-accent", text: `⚡ ${res.elapsed_ms} мс` }),
    ])
  );

  if (!res.items.length) {
    region.appendChild(
      el("div", { className: "card muted", text: "Збігів не знайдено. Спробуйте корінь слова (наприклад: стафілокок, дифтері, трепонем, РЗК)." })
    );
    return;
  }

  for (const item of res.items) {
    const stemEl = el("p", { className: "search-stem" });
    appendHighlightedText(stemEl, item.stem, res.query_terms);

    const tagsRow = el("div", { className: "chips-row" });
    if (item.topic_title) {
      tagsRow.appendChild(el("span", { className: "badge", text: item.topic_title }));
    }
    for (const tag of item.source_tags) {
      tagsRow.appendChild(el("span", { className: "badge badge-accent", text: tag }));
    }

    const isBookmarked = isQuestionBookmarked(item);
    const toolbar = el("div", { className: "question-toolbar" }, [
      tagsRow,
      el("button", {
        type: "button",
        className: "bookmark-btn",
        "aria-pressed": String(isBookmarked),
        "aria-label": isBookmarked ? "Прибрати із закладок" : "Додати в закладки",
        text: isBookmarked ? "🔖" : "☆",
        onClick: () => handleBookmarkToggle(item, renderSearchResultsRegion),
      }),
    ]);

    const revealed = state.revealedSearchIds.get(item.id);
    const cardChildren = [toolbar, stemEl];

    if (item.matched_in_options) {
      const optPreview = el("div", { className: "muted", style: "font-size:13.5px" }, [
        "Збіг у варіантах: ",
      ]);
      const joined = item.options.map((o) => o.text).join(" · ");
      appendHighlightedText(optPreview, joined, res.query_terms);
      cardChildren.push(optPreview);
    }

    if (revealed) {
      cardChildren.push(
        el("div", { className: "spoiler-answer", text: `✓ Правильна відповідь: ${revealed.correct_text}` })
      );
      if (revealed.explanation?.anchor_uk) {
        cardChildren.push(
          el("div", { className: "badge badge-amber", text: `✨ Якір КРОК: ${revealed.explanation.anchor_uk}` })
        );
      }
    } else {
      cardChildren.push(
        el("div", {}, [
          el("button", {
            type: "button",
            className: "btn btn-secondary btn-sm",
            text: "👁 Показати правильну відповідь",
            onClick: async () => {
              const rev = await api.revealQuestion(item.id, item.shuffle_salt);
              state.revealedSearchIds.set(item.id, rev);
              renderSearchResultsRegion();
            },
          }),
        ])
      );
    }

    region.appendChild(el("article", { className: "card search-result-card" }, cardChildren));
  }
}

// ---------- Screen 2: Mode Selector (naurok.ua pattern) ----------

function renderModeSelector() {
  const subj = state.subjects[0];
  const sel = state.selection;
  const root = el("div", { className: "stack-lg" });

  root.appendChild(
    el("div", { className: "row-between" }, [
      el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← Назад", onClick: goDashboard }),
      el("span", { className: "badge badge-accent", text: subj ? `${subj.total_questions} тестів у базі` : "" }),
    ])
  );

  root.appendChild(
    el("div", {}, [
      el("h1", { text: sel.title }),
      el("p", { className: "muted", style: "margin:0", text: "Оберіть фільтри джерела, кількість питань та формат тренування." }),
    ])
  );

  // Filters card
  const filterCard = el("section", { className: "card stack-md" });
  const sourceRow = el("div", { className: "stack-sm" }, [
    el("span", { style: "font-weight:650;font-size:14px", text: "Фільтр джерела" }),
  ]);
  const sourceChips = el("div", { className: "chips-row" });
  const tagChoices = [{ label: "Усі джерела", value: null }];
  if (subj?.source_tags?.length) {
    for (const st of subj.source_tags) {
      const lbl = st.tag === "ККР" ? `🎯 Тільки ККР (${st.count})` : `${st.tag} (${st.count})`;
      tagChoices.push({ label: lbl, value: st.tag });
    }
  } else {
    tagChoices.push(
      { label: "🎯 Тільки ККР", value: "ККР" },
      { label: "Загальна мікробіологія", value: "Загальна мікробіологія" },
      { label: "Вірусологія", value: "Вірусологія" },
      { label: "Спеціальна бактеріологія", value: "Спеціальна бактеріологія" },
    );
  }
  for (const ch of tagChoices) {
    sourceChips.appendChild(
      el("button", {
        type: "button",
        className: `chip ${sel.sourceTag === ch.value ? "active" : ""}`,
        text: ch.label,
        onClick: () => {
          sel.sourceTag = ch.value;
          render();
        },
      })
    );
  }
  sourceRow.appendChild(sourceChips);
  filterCard.appendChild(sourceRow);

  // Topic dropdown if subject loaded
  if (subj) {
    const topicLabel = el("label", {
      for: "mode-topic-select",
      style: "font-weight:650;font-size:14px",
      text: "Модуль / Тема",
    });
    const topicSelect = el("select", {
      id: "mode-topic-select",
      className: "select-control",
      onChange: (e) => {
        const val = e.target.value;
        if (val === "all") {
          sel.moduleNo = null;
          sel.topicId = null;
          sel.title = subj.title_uk;
        } else if (val.startsWith("m:")) {
          sel.moduleNo = Number(val.slice(2));
          sel.topicId = null;
          const m = subj.modules.find((x) => x.module_no === sel.moduleNo);
          sel.title = m ? m.title_uk : subj.title_uk;
        } else if (val.startsWith("t:")) {
          sel.topicId = Number(val.slice(2));
          sel.moduleNo = null;
          for (const m of subj.modules) {
            const t = m.topics.find((x) => x.id === sel.topicId);
            if (t) sel.title = t.title_uk;
          }
        }
        render();
      },
    });
    topicSelect.appendChild(el("option", { value: "all", text: `Уся дисципліна (${subj.total_questions})`, selected: sel.moduleNo === null && sel.topicId === null }));
    for (const mod of subj.modules) {
      topicSelect.appendChild(
        el("option", {
          value: `m:${mod.module_no}`,
          text: `${mod.title_uk} (${mod.question_count})`,
          selected: sel.moduleNo === mod.module_no && sel.topicId === null,
        })
      );
      for (const topic of mod.topics) {
        topicSelect.appendChild(
          el("option", {
            value: `t:${topic.id}`,
            text: `  ↳ ${topic.title_uk} (${topic.question_count})`,
            selected: sel.topicId === topic.id,
          })
        );
      }
    }
    filterCard.appendChild(el("div", { className: "stack-sm" }, [topicLabel, topicSelect]));
  }

  // Question count pills
  const countChips = el("div", { className: "chips-row" });
  for (const cnt of [10, 20, 30, 50, 150]) {
    countChips.appendChild(
      el("button", {
        type: "button",
        className: `chip ${sel.limit === cnt ? "active" : ""}`,
        text: cnt === 150 ? "Усі (до 150)" : `${cnt} питань`,
        onClick: () => {
          sel.limit = cnt;
          render();
        },
      })
    );
  }
  filterCard.appendChild(
    el("div", { className: "stack-sm" }, [
      el("span", { style: "font-weight:650;font-size:14px", text: "Розмір вибірки" }),
      countChips,
    ])
  );

  filterCard.appendChild(
    el("div", { className: "stack-sm" }, [
      el("span", { style: "font-weight:650;font-size:14px", text: "Підказки при формуванні тесту" }),
      el("div", { className: "chips-row" }, [
        el("button", {
          type: "button",
          id: "mode-hints-toggle-chip",
          className: `chip ${sel.hintsEnabled && state.auth.authenticated ? "active" : ""}`,
          text: !state.auth.authenticated
            ? "🔒 Маркери КРОК до відповіді (для авторизованих)"
            : sel.hintsEnabled
              ? "💡 Маркери КРОК до відповіді: УВІМК"
              : "💡 Маркери КРОК до відповіді: ВИМК",
          onClick: () => {
            if (!state.auth.authenticated) {
              openAuthDialog("Формування тесту з підказками (підсвітка маркерів КРОК до відповіді) доступне зареєстрованим користувачам через Telegram.");
              return;
            }
            sel.hintsEnabled = !sel.hintsEnabled;
            render();
          },
        }),
      ]),
    ])
  );
  root.appendChild(filterCard);

  // Mode cards
  const modes = el("section", { className: "mode-grid" }, [
    el("button", {
      type: "button",
      id: "mode-train-btn",
      className: "mode-card",
      onClick: () => startTraining({ mode: "train" }),
    }, [
      el("span", { className: "mode-icon", "aria-hidden": "true", text: "🎯" }),
      el("div", { className: "mode-body" }, [
        el("div", { className: "mode-title", text: "Тренування" }),
        el("div", {
          className: "mode-desc",
          text: sel.hintsEnabled && state.auth.authenticated
            ? "Обрані тема і джерело + підсвітка маркерів КРОК одразу до відповіді"
            : "Миттєвий вердикт після відповіді, перемішані A–E та закреслення дистракторів",
        }),
      ]),
      el("span", { className: "mode-arrow", "aria-hidden": "true", text: "→" }),
    ]),

    el("button", {
      type: "button",
      id: "mode-hints-btn",
      className: `mode-card ${state.auth.authenticated ? "" : "is-muted"}`,
      onClick: () =>
        state.auth.authenticated
          ? startTraining({
              mode: "hints",
              hintsEnabled: true,
              title: `З підказками · ${sel.title}`,
            })
          : openAuthDialog("Режим з підказками (маркери КРОК до відповіді по вибраній темі та джерелах) доступний після входу через Telegram."),
    }, [
      el("span", { className: "mode-icon is-amber", "aria-hidden": "true", text: "💡" }),
      el("div", { className: "mode-body" }, [
        el("div", { className: "mode-title", text: "Режим з підказками" }),
        el("div", {
          className: "mode-desc",
          text: state.auth.authenticated
            ? "Підсвітка ключових клінічних маркерів КРОК до відповіді (AMBOSS Highlight)"
            : "Увійдіть через Telegram, щоб формувати тести з підказками до відповіді",
        }),
      ]),
      el("span", {
        className: state.auth.authenticated ? "badge badge-amber" : "badge",
        text: state.auth.authenticated ? "Підказки →" : "Telegram",
      }),
    ]),

    el("button", {
      type: "button",
      id: "mode-flashcards-btn",
      className: "mode-card",
      onClick: startFlashcards,
    }, [
      el("span", { className: "mode-icon is-green", "aria-hidden": "true", text: "🃏" }),
      el("div", { className: "mode-body" }, [
        el("div", { className: "mode-title", text: "Флешкартки (Active Recall)" }),
        el("div", { className: "mode-desc", text: "Картки для швидкого повтору: умова спереду, ключ ззаду, самооцінка" }),
      ]),
      el("span", { className: "mode-arrow", "aria-hidden": "true", text: "→" }),
    ]),

    el("button", {
      type: "button",
      id: "mode-exam-btn",
      className: "mode-card",
      onClick: () =>
        startExamSimulator({
          subjectId: sel.subjectId,
          moduleNo: sel.moduleNo,
          sourceTag: sel.sourceTag,
          questionCount: Math.max(sel.limit, 150),
          title: `Іспит · ${sel.title}`,
        }),
    }, [
      el("span", { className: "mode-icon is-amber", "aria-hidden": "true", text: "⏱" }),
      el("div", { className: "mode-body" }, [
        el("div", { className: "mode-title", text: "Симулятор іспиту КРОК-1" }),
        el("div", { className: "mode-desc", text: "До 150 питань, таймер, навігатор, поріг 64% та карта слабких тем" }),
      ]),
      el("span", { className: "mode-arrow", "aria-hidden": "true", text: "→" }),
    ]),

    el("button", {
      type: "button",
      id: "mode-mistakes-btn",
      className: `mode-card ${state.auth.authenticated ? "" : "is-muted"}`,
      onClick: () =>
        state.auth.authenticated
          ? startTraining({ mode: "mistakes", title: "Помилки та повтори SM-2" })
          : openAuthDialog("Робота над помилками та черга повторень SM-2 працюють після входу через Telegram."),
    }, [
      el("span", { className: "mode-icon", "aria-hidden": "true", text: "🧠" }),
      el("div", { className: "mode-body" }, [
        el("div", { className: "mode-title", text: "Робота над помилками / SM-2" }),
        el("div", {
          className: "mode-desc",
          text: state.auth.authenticated
            ? "Прострочені повтори SM-2 та тести, у яких були помилки"
            : "Увійдіть через Telegram, щоб відкрити персональну чергу SM-2",
        }),
      ]),
      el("span", {
        className: state.auth.authenticated ? "badge badge-accent" : "badge",
        text: state.auth.authenticated ? "SM-2 →" : "Telegram",
      }),
    ]),
  ]);
  root.appendChild(modes);

  mainEl.appendChild(root);
}

// ---------- Screen 3: Training Quiz ----------

async function handleQuizAnswer(optionId) {
  const qz = state.quiz;
  if (!qz) return;
  const q = qz.questions[qz.idx];
  if (!q || qz.answers.has(q.id)) return;
  try {
    const res = await api.submitQuizAnswer(q.id, optionId);
    qz.answers.set(q.id, res);
    if (!state.auth.authenticated) {
      recordGuestAttempt(q.id, res.is_correct);
    }
    render();
    announce(res.is_correct ? "Правильно" : `Помилка. Правильна відповідь: ${res.correct_text}`);
  } catch (err) {
    showInfoDialog("Помилка перевірки", [err.message]);
  }
}

function toggleStrike(map, qid, optionId) {
  let set = map.get(qid);
  if (!set) {
    set = new Set();
    map.set(qid, set);
  }
  if (set.has(optionId)) {
    set.delete(optionId);
  } else {
    set.add(optionId);
  }
}

function renderQuiz() {
  const qz = state.quiz;
  if (!qz) return;

  if (qz.finished) {
    renderQuizSummary();
    return;
  }

  const q = qz.questions[qz.idx];
  const ans = qz.answers.get(q.id);
  const struckSet = qz.struck.get(q.id) || new Set();
  const total = qz.questions.length;
  const answeredCnt = qz.answers.size;
  let correctCnt = 0;
  for (const a of qz.answers.values()) {
    if (a.is_correct) correctCnt++;
  }
  const accPct = answeredCnt ? Math.round((correctCnt / answeredCnt) * 100) : 0;

  const root = el("div", { className: "stack-md" });

  // Header & Progress bar
  const hdr = el("div", { className: "session-header" }, [
    el("div", { className: "row-between" }, [
      el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← Вийти", onClick: goDashboard }),
      el("div", { className: "stat-badges" }, [
        qz.hintsEnabled ? el("span", { className: "badge badge-amber", text: "💡 Підказки" }) : null,
        el("span", { className: "badge badge-accent", text: `${qz.idx + 1} / ${total}` }),
        el("span", { className: "badge", text: `Точність: ${accPct}%` }),
      ]),
    ]),
    el("div", { className: "progress-track", role: "progressbar", "aria-valuenow": qz.idx + 1, "aria-valuemin": 1, "aria-valuemax": total }, [
      el("div", { className: "progress-fill", style: `width:${Math.round(((qz.idx + 1) / total) * 100)}%` }),
    ]),
  ]);
  root.appendChild(hdr);

  // Question Stem Card with KROK Markers (unlocked pre-answer in Hints Mode, else post-answer) & Bookmark
  const metaTags = el("div", { className: "chips-row" });
  if (q.topic_title) metaTags.appendChild(el("span", { className: "badge", text: q.topic_title }));
  for (const tag of q.source_tags) metaTags.appendChild(el("span", { className: "badge badge-accent", text: tag }));

  const answered = Boolean(ans);
  const markers = (ans?.explanation?.markers?.length ? ans.explanation.markers : q.markers) || [];
  const canShowMarkers = (answered || qz.hintsEnabled) && markers.length > 0;
  const markersOn = canShowMarkers && qz.showMarkers;
  const isBookmarked = isQuestionBookmarked(q);

  const toolbar = el("div", { className: "question-toolbar" }, [
    metaTags,
    el("div", { className: "question-actions" }, [
      el("button", {
        type: "button",
        id: "quiz-markers-btn",
        className: "marker-toggle-btn",
        disabled: !canShowMarkers,
        "aria-pressed": String(Boolean(markersOn)),
        title: canShowMarkers
          ? "Підсвітити клінічні маркери КРОК (H)"
          : answered
            ? "Для цього питання маркери ще не розмічені"
            : "Доступно після відповіді (або увімкніть «Режим з підказками»)",
        text: answered || qz.hintsEnabled ? "✨ Маркери КРОК" : "⏳ Після відповіді",
        onClick: () => {
          if (!canShowMarkers) return;
          qz.showMarkers = !qz.showMarkers;
          render();
        },
      }),
      el("button", {
        type: "button",
        id: "quiz-bookmark-btn",
        className: "bookmark-btn",
        "aria-pressed": String(isBookmarked),
        "aria-label": isBookmarked ? "Прибрати із закладок" : "Додати в закладки",
        text: isBookmarked ? "🔖" : "☆",
        onClick: () => handleBookmarkToggle(q, render),
      }),
    ]),
  ]);

  const stemHeading = el("h1", { className: "question-stem" });
  if (markersOn) {
    appendHighlightedText(stemHeading, q.stem, markers, "krok-marker");
  } else {
    stemHeading.textContent = q.stem;
  }

  root.appendChild(
    el("section", { className: "card stack-sm" }, [
      toolbar,
      stemHeading,
    ])
  );

  // Shuffled A-E Options + UWorld Strikethrough
  const optsList = el("div", { className: "options-list" });
  q.options.forEach((opt, i) => {
    const letter = LETTERS[i] || String(i + 1);
    const isStruck = struckSet.has(opt.option_id);
    let stateClass = "";
    if (ans) {
      if (opt.option_id === ans.correct_option_id) {
        stateClass = "is-correct";
      } else if (opt.option_id === ans.selected_option_id && !ans.is_correct) {
        stateClass = isStruck ? "is-wrong is-struck" : "is-wrong";
      } else if (isStruck) {
        stateClass = "is-struck";
      }
    } else if (isStruck) {
      stateClass = "is-struck";
    }

    const optBtn = el(
      "button",
      {
        type: "button",
        className: `option-btn ${stateClass}`,
        disabled: Boolean(ans),
        onClick: () => handleQuizAnswer(opt.option_id),
      },
      [
        el("span", { className: "option-letter", text: letter }),
        el("span", { className: "option-text", text: opt.text }),
      ]
    );

    const strikeBtn = el("button", {
      type: "button",
      className: "strike-btn",
      "aria-pressed": String(isStruck),
      "aria-label": `Закреслити варіант ${letter}`,
      text: "—",
      disabled: Boolean(ans),
      onClick: () => {
        toggleStrike(qz.struck, q.id, opt.option_id);
        render();
      },
    });

    optsList.appendChild(el("div", { className: "option-row" }, [optBtn, strikeBtn]));
  });
  root.appendChild(optsList);

  // Bottom Verdict Sheet
  if (ans) {
    const verdictChildren = [
      el("div", { className: "row-between" }, [
        el("strong", {
          style: `font-size:16px;color:${ans.is_correct ? "var(--state-correct)" : "var(--state-wrong)"}`,
          text: ans.is_correct ? "✓ Правильно!" : "✕ Помилка",
        }),
        el("button", {
          type: "button",
          id: "quiz-next-btn",
          className: "btn btn-primary btn-sm",
          text: qz.idx + 1 < total ? "Далі →" : "Завершити сесію →",
          onClick: () => {
            if (qz.idx + 1 < total) {
              qz.idx++;
            } else {
              qz.finished = true;
            }
            render();
          },
        }),
      ]),
      el("div", { text: `Правильна відповідь: ${ans.correct_text}` }),
    ];

    const exp = ans.explanation;
    const isExplaining = qz.explainingIds?.has(q.id);
    if (exp) {
      const expNodes = [
        el("div", { className: "row-between" }, [
          el("span", { className: "badge badge-amber", text: `✨ Якір КРОК: ${exp.anchor_uk}` }),
          exp.model_id
            ? el("span", { className: "muted", style: "font-size:11.5px", text: exp.model_id })
            : null,
        ]),
      ];
      if (exp.explanation_uk) {
        expNodes.push(el("div", { text: exp.explanation_uk }));
      }
      if (exp.distractors_uk) {
        expNodes.push(el("div", { className: "muted", style: "font-size:13px", text: `Чому інші не підходять: ${exp.distractors_uk}` }));
      }
      if (exp.model_id === "trigger-index-v1") {
        expNodes.push(
          el("div", {}, [
            el("button", {
              type: "button",
              id: "quiz-ai-explain-btn",
              className: "btn btn-secondary btn-sm",
              disabled: isExplaining,
              text: isExplaining ? "Генерація AI-розбору…" : "🤖 Поглиблений AI-розбір",
              onClick: () => handleRequestAiExplanation(q, ans, render),
            }),
          ])
        );
      }
      verdictChildren.push(el("div", { className: "explain-box" }, expNodes));
    } else {
      verdictChildren.push(
        el("div", {}, [
          el("button", {
            type: "button",
            id: "quiz-ai-explain-btn",
            className: "btn btn-secondary btn-sm",
            disabled: isExplaining,
            text: isExplaining ? "Генерація AI-розбору…" : "🤖 Згенерувати розбір КРОК",
            onClick: () => handleRequestAiExplanation(q, ans, render),
          }),
        ])
      );
    }

    root.appendChild(
      el("section", { className: `verdict-sheet ${ans.is_correct ? "is-correct" : "is-wrong"}` }, verdictChildren)
    );
  } else {
    root.appendChild(
      el("p", {
        className: "muted",
        style: "margin:0;font-size:12.5px",
        text: "Хоткеї ПК: 1–5 або A–E — відповідь · X потім 1–5 — закреслити варіант",
      })
    );
  }

  mainEl.appendChild(root);
}

function renderQuizSummary() {
  const qz = state.quiz;
  const total = qz.questions.length;
  let correctCnt = 0;
  const missed = [];
  for (const q of qz.questions) {
    const a = qz.answers.get(q.id);
    if (a && a.is_correct) {
      correctCnt++;
    } else {
      missed.push({ q, a });
    }
  }
  const pct = total ? Math.round((correctCnt / total) * 100) : 0;

  const root = el("div", { className: "stack-lg" }, [
    el("section", { className: "card stack-md" }, [
      el("h1", { text: `Сесію завершено: ${pct}%` }),
      el("p", {
        className: "muted",
        style: "margin:0",
        text: `Правильно ${correctCnt} із ${total} питань (${qz.title}).`,
      }),
      el("div", { className: "hero-actions" }, [
        missed.length
          ? el("button", {
              type: "button",
              className: "btn btn-amber",
              text: `🔁 Повторити помилки (${missed.length})`,
              onClick: () => {
                state.quiz = {
                  sessionId: `${qz.sessionId}-retry`,
                  title: `Повтор помилок · ${qz.title}`,
                  questions: missed.map((m) => m.q),
                  idx: 0,
                  answers: new Map(),
                  struck: new Map(),
                  hintsEnabled: Boolean(qz.hintsEnabled),
                  showMarkers: Boolean(qz.hintsEnabled),
                  explainingIds: new Set(),
                  xMode: false,
                  finished: false,
                };
                render();
              },
            })
          : null,
        el("button", { type: "button", className: "btn btn-primary", text: "Нова сесія", onClick: () => openModeSelector(state.selection) }),
        el("button", { type: "button", className: "btn btn-secondary", text: "На головну", onClick: goDashboard }),
      ]),
    ]),
  ]);

  if (missed.length) {
    const revWrap = el("section", { className: "stack-sm" }, [el("h2", { text: "Питання з помилками" })]);
    for (const { q, a } of missed) {
      revWrap.appendChild(
        el("article", { className: "card stack-sm" }, [
          el("p", { style: "margin:0;font-weight:550", text: q.stem }),
          el("div", { className: "spoiler-answer", text: a ? `✓ ${a.correct_text}` : "Без відповіді" }),
        ])
      );
    }
    root.appendChild(revWrap);
  }

  mainEl.appendChild(root);
}

// ---------- Screen 4: Flashcards (Active Recall) ----------

async function flipCurrentFlashcard() {
  const fc = state.cards;
  if (!fc || fc.finished) return;
  const q = fc.queue[fc.idx];
  if (!q) return;

  if (!fc.reveals.has(q.id)) {
    try {
      const rev = await api.revealQuestion(q.id);
      fc.reveals.set(q.id, rev);
    } catch (err) {
      showInfoDialog("Помилка картки", [err.message]);
      return;
    }
  }
  fc.flipped = !fc.flipped;
  render();
}

function rateFlashcard(rating) {
  const fc = state.cards;
  if (!fc || !fc.flipped) return;
  const q = fc.queue[fc.idx];
  fc.ratings[rating]++;
  const qualityMap = { again: 1, hard: 3, good: 5 };
  if (state.auth.authenticated) {
    api.rateFlashcard(q.id, qualityMap[rating] ?? 3).catch(() => {});
  } else {
    recordGuestAttempt(q.id, rating !== "again");
  }
  if (rating === "again") {
    // Re-queue card later in the active recall deck.
    fc.queue.push(q);
  }
  fc.flipped = false;
  if (fc.idx + 1 < fc.queue.length) {
    fc.idx++;
  } else {
    fc.finished = true;
    if (state.auth.authenticated) refreshCatalogAndStats().catch(() => {});
  }
  render();
}

function renderFlashcards() {
  const fc = state.cards;
  if (!fc) return;

  if (fc.finished) {
    const root = el("div", { className: "stack-lg" }, [
      el("section", { className: "card stack-md" }, [
        el("h1", { text: "Колоду флешкарток пройдено!" }),
        el("div", { className: "stat-badges" }, [
          el("span", { className: "badge badge-green", text: `Впевнено: ${fc.ratings.good}` }),
          el("span", { className: "badge badge-amber", text: `Важко: ${fc.ratings.hard}` }),
          el("span", { className: "badge badge-red", text: `Повторено «Не знаю»: ${fc.ratings.again}` }),
        ]),
        el("div", { className: "hero-actions" }, [
          el("button", { type: "button", className: "btn btn-primary", text: "Повторити колоду", onClick: startFlashcards }),
          el("button", { type: "button", className: "btn btn-secondary", text: "На головну", onClick: goDashboard }),
        ]),
      ]),
    ]);
    mainEl.appendChild(root);
    return;
  }

  const q = fc.queue[fc.idx];
  const rev = fc.reveals.get(q.id);
  const total = fc.queue.length;
  const root = el("div", { className: "stack-md" });

  root.appendChild(
    el("div", { className: "session-header" }, [
      el("div", { className: "row-between" }, [
        el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← Вийти", onClick: goDashboard }),
        el("span", { className: "badge badge-accent", text: `Картка ${fc.idx + 1} / ${total}` }),
      ]),
      el("div", { className: "progress-track" }, [
        el("div", { className: "progress-fill", style: `width:${Math.round(((fc.idx + 1) / total) * 100)}%` }),
      ]),
    ])
  );

  const tags = el("div", { className: "chips-row" });
  if (q.topic_title) tags.appendChild(el("span", { className: "badge", text: q.topic_title }));
  for (const t of q.source_tags) tags.appendChild(el("span", { className: "badge badge-accent", text: t }));

  const markers = (rev?.explanation?.markers?.length ? rev.explanation.markers : q.markers) || [];
  const canShowCardMarkers = (fc.flipped || fc.hintsEnabled) && markers.length > 0;
  const markersOn = canShowCardMarkers && fc.showMarkers;
  const isBookmarked = isQuestionBookmarked(q);

  const toolbar = el("div", { className: "question-toolbar" }, [
    tags,
    el("div", { className: "question-actions" }, [
      el("button", {
        type: "button",
        className: "marker-toggle-btn",
        disabled: !canShowCardMarkers,
        "aria-pressed": String(Boolean(markersOn)),
        text: fc.flipped || fc.hintsEnabled ? "✨ Маркери КРОК" : "⏳ Після перевороту",
        onClick: (e) => {
          e.stopPropagation();
          if (!canShowCardMarkers) return;
          fc.showMarkers = !fc.showMarkers;
          render();
        },
      }),
      el("button", {
        type: "button",
        className: "bookmark-btn",
        "aria-pressed": String(isBookmarked),
        "aria-label": isBookmarked ? "Прибрати із закладок" : "Додати в закладки",
        text: isBookmarked ? "🔖" : "☆",
        onClick: (e) => {
          e.stopPropagation();
          handleBookmarkToggle(q, render);
        },
      }),
    ]),
  ]);

  const stemEl = el("h1", { className: "question-stem" });
  if (markersOn) {
    appendHighlightedText(stemEl, q.stem, markers, "krok-marker");
  } else {
    stemEl.textContent = q.stem;
  }

  const cardBody = [toolbar, stemEl];
  if (fc.flipped && rev) {
    cardBody.push(el("div", { className: "flashcard-answer-box", text: `✓ ${rev.correct_text}` }));
    if (rev.explanation) {
      cardBody.push(
        el("div", { className: "explain-box" }, [
          el("span", { className: "badge badge-amber", text: `✨ ${rev.explanation.anchor_uk}` }),
          rev.explanation.explanation_uk ? el("div", { text: rev.explanation.explanation_uk }) : null,
        ])
      );
    }
  } else {
    cardBody.push(
      el("div", { className: "muted", style: "font-size:13.5px", text: "Натисніть на картку або Space, щоб відкрити відповідь" })
    );
  }

  root.appendChild(
    el(
      "button",
      {
        type: "button",
        id: "flashcard-surface-btn",
        className: `flashcard-btn ${fc.flipped ? "is-flipped" : ""}`,
        onClick: flipCurrentFlashcard,
      },
      cardBody
    )
  );

  if (fc.flipped) {
    root.appendChild(
      el("div", { className: "rate-grid" }, [
        el("button", { type: "button", className: "btn btn-secondary", text: "1 · Не знаю", onClick: () => rateFlashcard("again") }),
        el("button", { type: "button", className: "btn btn-amber", text: "2 · Важко", onClick: () => rateFlashcard("hard") }),
        el("button", { type: "button", className: "btn btn-primary", text: "3 · Впевнено", onClick: () => rateFlashcard("good") }),
      ])
    );
  }

  mainEl.appendChild(root);
}

// ---------- Screen 5: Exam Simulator & Weak-Spots Map ----------

function openExamNavigator() {
  const ex = state.exam;
  if (!ex) return;
  const grid = document.getElementById("exam-nav-grid");
  clear(grid);
  ex.questions.forEach((q, idx) => {
    const isAnswered = ex.selected.has(q.id);
    const isFlagged = ex.flagged.has(q.id);
    const cls = ["nav-cell"];
    if (isFlagged) cls.push("is-flagged");
    else if (isAnswered) cls.push("is-answered");
    if (idx === ex.idx) cls.push("is-current");

    grid.appendChild(
      el("button", {
        type: "button",
        className: cls.join(" "),
        text: String(idx + 1),
        "aria-label": `Питання ${idx + 1}${isAnswered ? ", є відповідь" : ""}${isFlagged ? ", під прапорцем" : ""}`,
        onClick: () => {
          ex.idx = idx;
          examNavDialog.close();
          render();
        },
      })
    );
  });
  examNavDialog.showModal();
}

function openExamConfirm() {
  const ex = state.exam;
  if (!ex) return;
  const total = ex.questions.length;
  const answered = ex.selected.size;
  const unanswered = total - answered;
  const summary = document.getElementById("exam-confirm-summary");
  summary.textContent =
    unanswered > 0
      ? `Ви відповіли на ${answered} із ${total} питань. Без відповіді залишилось: ${unanswered}. Завершити та підрахувати бал (поріг 64%)?`
      : `Ви відповіли на всі ${total} питань. Завершити та перевірити роботу?`;
  examConfirmDialog.showModal();
}

function renderExamRunner() {
  const ex = state.exam;
  if (!ex) return;
  const q = ex.questions[ex.idx];
  const total = ex.questions.length;
  const selectedId = ex.selected.get(q.id);
  const isFlagged = ex.flagged.has(q.id);
  const struckSet = ex.struck.get(q.id) || new Set();

  const root = el("div", { className: "stack-md" });

  root.appendChild(
    el("div", { className: "session-header" }, [
      el("div", { className: "row-between" }, [
        el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← Вийти", onClick: goDashboard }),
        el("span", {
          id: "exam-timer-pill",
          className: `timer-pill ${ex.remainingSec <= 300 ? "is-low" : ""}`,
          text: `⏱ ${formatDuration(ex.remainingSec)}`,
        }),
        el("div", { className: "topbar-actions" }, [
          el("button", {
            type: "button",
            id: "exam-nav-open-btn",
            className: "btn btn-secondary btn-sm",
            text: `Сітка ${ex.idx + 1}/${total}`,
            onClick: openExamNavigator,
          }),
          el("button", {
            type: "button",
            id: "exam-finish-btn",
            className: "btn btn-primary btn-sm",
            text: "Здати",
            onClick: openExamConfirm,
          }),
        ]),
      ]),
      el("div", { className: "progress-track" }, [
        el("div", { className: "progress-fill", style: `width:${Math.round((ex.selected.size / total) * 100)}%` }),
      ]),
    ])
  );

  root.appendChild(
    el("section", { className: "card stack-sm" }, [
      el("div", { className: "row-between" }, [
        el("span", { className: "badge badge-accent", text: `Питання ${ex.idx + 1} з ${total}` }),
        el("button", {
          type: "button",
          className: `btn btn-sm ${isFlagged ? "btn-amber" : "btn-ghost"}`,
          "aria-pressed": String(isFlagged),
          text: isFlagged ? "🚩 Відкладено" : "⚑ Відкласти",
          onClick: () => {
            if (isFlagged) ex.flagged.delete(q.id);
            else ex.flagged.add(q.id);
            render();
          },
        }),
      ]),
      el("h1", { className: "question-stem", text: q.stem }),
    ])
  );

  const optsList = el("div", { className: "options-list" });
  q.options.forEach((opt, i) => {
    const letter = LETTERS[i] || String(i + 1);
    const isSel = selectedId === opt.option_id;
    const isStruck = struckSet.has(opt.option_id);
    const optBtn = el(
      "button",
      {
        type: "button",
        className: `option-btn ${isSel ? "is-selected" : isStruck ? "is-struck" : ""}`,
        onClick: () => {
          ex.selected.set(q.id, opt.option_id);
          render();
        },
      },
      [
        el("span", { className: "option-letter", text: letter }),
        el("span", { className: "option-text", text: opt.text }),
      ]
    );
    const strikeBtn = el("button", {
      type: "button",
      className: "strike-btn",
      "aria-pressed": String(isStruck),
      "aria-label": `Закреслити варіант ${letter}`,
      text: "—",
      onClick: () => {
        toggleStrike(ex.struck, q.id, opt.option_id);
        render();
      },
    });
    optsList.appendChild(el("div", { className: "option-row" }, [optBtn, strikeBtn]));
  });
  root.appendChild(optsList);

  root.appendChild(
    el("div", { className: "row-between" }, [
      el("button", {
        type: "button",
        className: "btn btn-secondary",
        disabled: ex.idx === 0,
        text: "← Попереднє",
        onClick: () => {
          if (ex.idx > 0) {
            ex.idx--;
            render();
          }
        },
      }),
      el("button", {
        type: "button",
        className: "btn btn-primary",
        text: ex.idx + 1 < total ? "Наступне →" : "Завершити іспит →",
        onClick: () => {
          if (ex.idx + 1 < total) {
            ex.idx++;
            render();
          } else {
            openExamConfirm();
          }
        },
      }),
    ])
  );

  mainEl.appendChild(root);
}

function renderExamResults() {
  const ex = state.exam;
  const res = ex?.results;
  if (!res) return;

  const root = el("div", { className: "stack-lg" });

  root.appendChild(
    el("section", { className: "card stack-md" }, [
      el("div", { className: "row-between" }, [
        el("h1", { text: `Результат іспиту: ${res.score_pct}%` }),
        el("span", {
          className: `badge ${res.passed ? "badge-green" : "badge-red"}`,
          text: res.passed ? "✓ СКЛАДЕНО (≥ 64%)" : "✕ НЕ СКЛАДЕНО (< 64%)",
        }),
      ]),
      el("p", {
        className: "muted",
        style: "margin:0",
        text: `Правильно ${res.correct_count} із ${res.total_questions} питань · Відповідей надано: ${res.answered_count} · Час: ${formatDuration(res.duration_sec)}.`,
      }),
      el("div", { className: "hero-actions" }, [
        res.weakest_topic_ids.length
          ? el("button", {
              type: "button",
              id: "close-weakest-btn",
              className: "btn btn-amber",
              text: `🔥 Закрити ${res.weakest_topic_ids.length} найслабші теми`,
              onClick: () =>
                startTraining({
                  mode: "train",
                  topicIds: res.weakest_topic_ids,
                  limit: 20,
                  title: "Закриття слабких тем",
                }),
            })
          : null,
        el("button", { type: "button", className: "btn btn-primary", text: "Новий іспит", onClick: () => startExamSimulator() }),
        el("button", { type: "button", className: "btn btn-secondary", text: "На головну", onClick: goDashboard }),
      ]),
    ])
  );

  // Weak-Spots Heatmap Breakdown
  if (res.breakdown.length) {
    const mapCard = el("section", { className: "card stack-sm" }, [
      el("h2", { text: "Карта слабких місць по темах" }),
      el("p", { className: "muted", style: "margin:0;font-size:13px", text: "Червоний < 64% · Жовтий 64–80% · Зелений > 80%" }),
    ]);
    for (const row of res.breakdown) {
      mapCard.appendChild(
        el("div", { className: "heatmap-row" }, [
          el("div", { className: "row-between" }, [
            el("span", { style: "font-size:14px;font-weight:600", text: row.title_uk }),
            el("span", { className: `badge badge-${row.band === "amber" ? "amber" : row.band}`, text: `${row.correct}/${row.total} (${row.accuracy_pct}%)` }),
          ]),
          el("div", { className: "heatmap-bar" }, [
            el("div", { className: `heatmap-fill ${row.band}`, style: `width:${Math.max(3, row.accuracy_pct)}%` }),
          ]),
        ])
      );
    }
    root.appendChild(mapCard);
  }

  // Review list filter
  const wrongItems = res.review_items.filter((i) => !i.is_correct);
  const shown = ex.reviewFilter === "wrong" ? wrongItems : res.review_items;
  const revSection = el("section", { className: "stack-sm" }, [
    el("div", { className: "row-between" }, [
      el("h2", { text: "Розбір відповідей" }),
      el("div", { className: "chips-row" }, [
        el("button", {
          type: "button",
          className: `chip ${ex.reviewFilter === "wrong" ? "active" : ""}`,
          text: `Помилки (${wrongItems.length})`,
          onClick: () => {
            ex.reviewFilter = "wrong";
            render();
          },
        }),
        el("button", {
          type: "button",
          className: `chip ${ex.reviewFilter === "all" ? "active" : ""}`,
          text: `Усі (${res.review_items.length})`,
          onClick: () => {
            ex.reviewFilter = "all";
            render();
          },
        }),
      ]),
    ]),
  ]);

  if (!shown.length) {
    revSection.appendChild(el("div", { className: "card muted", text: "Помилок немає — бездоганний результат!" }));
  } else {
    for (const item of shown) {
      revSection.appendChild(
        el("article", { className: "card stack-sm" }, [
          el("div", { className: "row-between" }, [
            el("span", { className: "badge", text: item.topic_title || "КРОК-1" }),
            el("span", { className: `badge ${item.is_correct ? "badge-green" : "badge-red"}`, text: item.is_correct ? "✓ Вірно" : "✕ Помилка" }),
          ]),
          el("p", { style: "margin:0;font-weight:550", text: item.stem }),
          item.selected_text && !item.is_correct
            ? el("div", { style: "color:var(--state-wrong);font-size:14px", text: `Ваша відповідь: ${item.selected_text}` })
            : null,
          el("div", { className: "spoiler-answer", text: `✓ Правильно: ${item.correct_text}` }),
        ])
      );
    }
  }
  root.appendChild(revSection);

  mainEl.appendChild(root);
}

// ---------- Screen 6: Profile, SM-2 Weak Topics, Bookmarks & Exam History ----------

function renderProfile() {
  if (!state.auth.authenticated || !state.auth.user) {
    goDashboard();
    return;
  }
  const u = state.auth.user;
  const st = state.stats;
  const root = el("div", { className: "stack-lg" });

  root.appendChild(
    el("div", { className: "row-between" }, [
      el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← На головну", onClick: goDashboard }),
      el("button", { type: "button", id: "profile-logout-btn", className: "btn btn-secondary btn-sm", text: "Вийти з акаунта", onClick: handleLogout }),
    ])
  );

  root.appendChild(
    el("section", { className: "card stack-md" }, [
      el("div", { className: "row-between" }, [
        el("div", {}, [
          el("h1", { text: `${u.display_name}${u.username ? ` · @${u.username}` : ""}` }),
          el("p", { className: "muted", style: "margin:0", text: `Роль: ${u.role} · Telegram ID: ${u.tg_id}` }),
        ]),
        el("span", { className: "badge badge-green", text: "● Синхронізовано" }),
      ]),
      st?.summary
        ? el("div", { className: "kpi-grid" }, [
            el("div", { className: "kpi-card" }, [
              el("span", { className: "kpi-value", text: `${st.summary.attempted_count}/${st.summary.total_verified}` }),
              el("span", { className: "kpi-label", text: "Опрацьовано питань" }),
            ]),
            el("div", { className: "kpi-card" }, [
              el("span", { className: "kpi-value", text: `${st.summary.overall_accuracy_pct}%` }),
              el("span", { className: "kpi-label", text: "Точність SM-2" }),
            ]),
            el("div", { className: "kpi-card" }, [
              el("span", { className: "kpi-value", text: `${st.summary.due_count}` }),
              el("span", { className: "kpi-label", text: "На повтор сьогодні" }),
            ]),
            el("div", { className: "kpi-card" }, [
              el("span", { className: "kpi-value", text: `${st.summary.bookmarked_count}` }),
              el("span", { className: "kpi-label", text: "Закладки" }),
            ]),
          ])
        : el("div", { className: "muted", text: "Завантаження аналітики…" }),
      el("div", { className: "hero-actions" }, [
        el("button", {
          type: "button",
          className: "btn btn-primary",
          text: "🧠 Робота над помилками / SM-2",
          onClick: () => startTraining({ mode: "mistakes", limit: 25, title: "Помилки та повтори SM-2" }),
        }),
        el("button", {
          type: "button",
          className: "btn btn-secondary",
          text: "🔥 Закрити 3 слабкі теми",
          onClick: () => startTraining({ mode: "weak_topics", limit: 20, title: "Закрити 3 найслабші теми" }),
        }),
      ]),
    ])
  );

  if (st?.weakest_topics?.length) {
    const weakCard = el("section", { className: "card stack-sm" }, [
      el("h2", { text: "Карта слабких тем" }),
    ]);
    for (const wt of st.weakest_topics) {
      weakCard.appendChild(
        el("div", { className: "row-between", style: "padding:8px 0;border-bottom:1px solid var(--border-subtle)" }, [
          el("div", {}, [
            el("div", { style: "font-weight:600;font-size:14.5px", text: wt.title_uk }),
            el("div", { className: "muted", style: "font-size:12.5px", text: `Модуль ${wt.module_no} · ${wt.wrong_cnt} помилок · точність ${wt.accuracy_pct}%` }),
          ]),
          el("button", {
            type: "button",
            className: "btn btn-secondary btn-sm",
            text: "Тренувати →",
            onClick: () =>
              startTraining({
                mode: "smart_mix",
                moduleNo: wt.module_no,
                topicId: wt.topic_id,
                limit: 20,
                title: wt.title_uk,
              }),
          }),
        ])
      );
    }
    root.appendChild(weakCard);
  }

  if (st?.bookmarked_questions?.length) {
    const bmCard = el("section", { className: "card stack-sm" }, [
      el("h2", { text: `Збережені закладки (${st.bookmarked_questions.length})` }),
    ]);
    for (const bm of st.bookmarked_questions) {
      bmCard.appendChild(
        el("div", { className: "stack-sm", style: "padding:10px 0;border-bottom:1px solid var(--border-subtle)" }, [
          el("div", { className: "row-between" }, [
            el("span", { className: "badge", text: bm.topic_title || "Тест КРОК-1" }),
            el("button", {
              type: "button",
              className: "bookmark-btn",
              "aria-pressed": "true",
              text: "🔖",
              onClick: async () => {
                await handleBookmarkToggle({ id: bm.question_id, bookmarked: true }, () => {});
                await refreshCatalogAndStats();
                render();
              },
            }),
          ]),
          el("p", { style: "margin:0;font-size:14.5px", text: bm.stem }),
        ])
      );
    }
    root.appendChild(bmCard);
  }

  if (st?.exam_history?.length) {
    const histCard = el("section", { className: "card stack-sm" }, [
      el("h2", { text: "Історія симуляторів іспиту" }),
    ]);
    for (const ex of st.exam_history) {
      const passed = ex.score_pct >= 64;
      histCard.appendChild(
        el("div", { className: "row-between", style: "padding:6px 0;border-bottom:1px solid var(--border-subtle)" }, [
          el("span", { text: `${ex.correct_q} / ${ex.total_q} · ${formatDuration(ex.duration_sec)}` }),
          el("span", {
            className: `badge ${passed ? "badge-green" : "badge-red"}`,
            text: `${ex.score_pct}% · ${passed ? "Складено" : "Не складено"}`,
          }),
        ])
      );
    }
    root.appendChild(histCard);
  }

  mainEl.appendChild(root);
}

// ---------- Root Render & Global Keyboard Shortcuts ----------

function render() {
  clear(mainEl);
  updateAuthHeaderPill();
  if (state.screen === "dashboard") renderDashboard();
  else if (state.screen === "mode") renderModeSelector();
  else if (state.screen === "quiz") renderQuiz();
  else if (state.screen === "flashcards") renderFlashcards();
  else if (state.screen === "exam") renderExamRunner();
  else if (state.screen === "exam-results") renderExamResults();
  else if (state.screen === "profile") renderProfile();
}

function setupGlobalEvents() {
  document.getElementById("brand-home-btn")?.addEventListener("click", goDashboard);
  document.getElementById("shortcuts-btn")?.addEventListener("click", showShortcutsModal);
  document.getElementById("guest-pill-btn")?.addEventListener("click", () => {
    if (state.auth.authenticated) openProfile();
    else openAuthDialog();
  });

  examConfirmDialog?.addEventListener("close", () => {
    if (examConfirmDialog.returnValue === "confirm") {
      finalizeExam();
    }
  });

  document.addEventListener("keydown", (e) => {
    const activeDialog = document.querySelector("dialog[open]");
    if (activeDialog) return;

    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (state.screen !== "dashboard") goDashboard();
      requestAnimationFrame(() => document.getElementById("search-input")?.focus());
      return;
    }

    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    const k = e.key.toLowerCase();

    if (state.screen === "quiz" && state.quiz && !state.quiz.finished) {
      const qz = state.quiz;
      const q = qz.questions[qz.idx];
      if (!q) return;

      if (k === "h" && (qz.answers.has(q.id) || qz.hintsEnabled)) {
        qz.showMarkers = !qz.showMarkers;
        render();
        return;
      }

      if (k === "x" && !qz.answers.has(q.id)) {
        qz.xMode = true;
        announce("Натисніть 1–5 щоб закреслити варіант");
        return;
      }

      const mapKey = { "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, a: 0, b: 1, c: 2, d: 3, e: 4 };
      if (k in mapKey && mapKey[k] < q.options.length) {
        const opt = q.options[mapKey[k]];
        if (qz.xMode && !qz.answers.has(q.id)) {
          qz.xMode = false;
          toggleStrike(qz.struck, q.id, opt.option_id);
          render();
        } else if (!qz.answers.has(q.id)) {
          handleQuizAnswer(opt.option_id);
        }
        return;
      }

      if ((e.key === "Enter" || e.key === " ") && qz.answers.has(q.id)) {
        e.preventDefault();
        if (qz.idx + 1 < qz.questions.length) qz.idx++;
        else qz.finished = true;
        render();
      }
      return;
    }

    if (state.screen === "flashcards" && state.cards && !state.cards.finished) {
      const fc = state.cards;
      if (k === "h" && (fc.flipped || fc.hintsEnabled)) {
        fc.showMarkers = !fc.showMarkers;
        render();
        return;
      }
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        flipCurrentFlashcard();
      } else if (fc.flipped && k === "1") {
        rateFlashcard("again");
      } else if (fc.flipped && k === "2") {
        rateFlashcard("hard");
      } else if (fc.flipped && k === "3") {
        rateFlashcard("good");
      }
      return;
    }

    if (state.screen === "exam" && state.exam) {
      const ex = state.exam;
      const q = ex.questions[ex.idx];
      if (!q) return;
      const mapKey = { "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, a: 0, b: 1, c: 2, d: 3, e: 4 };
      if (k in mapKey && mapKey[k] < q.options.length) {
        ex.selected.set(q.id, q.options[mapKey[k]].option_id);
        render();
      } else if (e.key === "ArrowRight" && ex.idx + 1 < ex.questions.length) {
        ex.idx++;
        render();
      } else if (e.key === "ArrowLeft" && ex.idx > 0) {
        ex.idx--;
        render();
      }
    }
  });
}

async function bootstrap() {
  initThemeToggle(document.getElementById("theme-toggle-btn"));
  setupDialogLightDismiss();
  setupGlobalEvents();

  mainEl.appendChild(el("div", { className: "card muted", text: "Завантаження бази КРОК-1…" }));
  try {
    const [health, authStatus] = await Promise.all([api.getHealth(), api.getAuthStatus()]);
    state.health = health;
    state.auth = {
      enabled: Boolean(authStatus.enabled),
      botUsername: authStatus.bot_username || null,
      authenticated: Boolean(authStatus.authenticated),
      user: authStatus.user || null,
    };
    if (state.auth.authenticated) {
      await syncGuestIfPending();
    }
    await refreshCatalogAndStats();
    if (state.subjects[0]) {
      state.selection.subjectId = state.subjects[0].id;
      state.selection.subjectTitle = state.subjects[0].title_uk;
      state.selection.title = state.subjects[0].title_uk;
    }
    render();
  } catch (err) {
    clear(mainEl);
    mainEl.appendChild(el("div", { className: "card", text: `Не вдалося завантажити дані: ${err.message}` }));
  }
}

bootstrap();
