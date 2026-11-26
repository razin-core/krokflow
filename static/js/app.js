/** Main KrokFlow SPA controller covering all MVP & Phase 2 screens. */

import { api } from "./api.js?v=2.8.0";
import {
  createCascadeSelector,
  resolveCascadeScope,
  syncCascadeFromSelection,
} from "./cascade_selector.js?v=2.8.0";
import {
  appendHighlightedText,
  clear,
  createCloseIconSvg,
  el,
  pluralUk,
  setupDialogLightDismiss,
} from "./dom.js?v=2.8.0";
import {
  clearGuestAttemptsOnly,
  clearGuestBuffer,
  hasPendingGuestSync,
  loadGuestBuffer,
  recordGuestAttempt,
  state,
  toggleGuestBookmark,
} from "./state.js?v=2.8.0";
import { initThemeToggle } from "./theme.js?v=2.8.0";

const LETTERS = ["A", "B", "C", "D", "E"];
const mainEl = document.getElementById("app-main");
const announcerEl = document.getElementById("live-announcer");
const examNavDialog = document.getElementById("exam-nav-dialog");
const examConfirmDialog = document.getElementById("exam-confirm-dialog");
const infoDialog = document.getElementById("info-dialog");
const authDialog = document.getElementById("auth-dialog");
const resetStatsDialog = document.getElementById("reset-stats-dialog");
const reportQuestionDialog = document.getElementById("report-question-dialog");

let reportingQuestion = null;
const reportedQuestionIds = new Set();

function buildReportTriggerButton(q, { id = null } = {}) {
  const sent = reportedQuestionIds.has(q.id);
  const attrs = {
    type: "button",
    className: "btn btn-secondary btn-sm report-trigger-btn",
    text: sent ? "✓ Скаргу надіслано" : "⚑ Поскаржитись на помилку",
    onClick: () => openReportDialog(q),
  };
  if (id) attrs.id = id;
  return el("button", attrs);
}

function openReportDialog(q) {
  if (!reportQuestionDialog || !q) return;
  reportingQuestion = q;
  const form = document.getElementById("report-question-form");
  const ctxEl = document.getElementById("report-dialog-context");
  const commentEl = document.getElementById("report-comment-input");
  const statusEl = document.getElementById("report-form-status");
  const submitBtn = document.getElementById("report-submit-btn");

  form?.reset();
  commentEl?.removeAttribute("aria-invalid");
  if (statusEl) {
    statusEl.textContent = "";
    statusEl.className = "report-form-status";
  }
  if (submitBtn) submitBtn.disabled = false;
  if (ctxEl) {
    const snippet = q.stem.length > 120 ? `${q.stem.slice(0, 120)}…` : q.stem;
    ctxEl.textContent = `Питання #${q.id}: ${snippet}`;
  }
  reportQuestionDialog.showModal();
}

let searchTimer = null;
const TOTAL_TIME_PRESETS = [300, 600, 900, 1800, 3600];
const QUESTION_TIME_PRESETS = [15, 30, 45, 60, 90];
const customTimerOpen = { total: false, question: false };

function sanitizeTimerSec(raw, { min = 5, max = 14400 } = {}) {
  if (raw === null || raw === undefined || raw === "") return null;
  const n = Math.trunc(Number(raw));
  if (!Number.isFinite(n) || n <= 0) return null;
  return Math.min(max, Math.max(min, n));
}

function buildTimerConfigControls({ idPrefix, totalTimeSec, questionTimeSec, onChange }) {
  let curTotal = sanitizeTimerSec(totalTimeSec, { min: 5, max: 14400 });
  let curQ = sanitizeTimerSec(questionTimeSec, { min: 5, max: 600 });
  const isCustomTotal =
    customTimerOpen.total || (curTotal != null && !TOTAL_TIME_PRESETS.includes(curTotal));
  const isCustomQ =
    customTimerOpen.question || (curQ != null && !QUESTION_TIME_PRESETS.includes(curQ));

  const grid = el("div", { className: "timer-config-grid" });

  // 1. Total test time (minutes)
  const totalSelId = `${idPrefix}-total-time-select`;
  const totalCustomId = `${idPrefix}-total-time-custom`;
  const totalSel = el("select", {
    id: totalSelId,
    name: "total_time_sec",
    className: "brand-select",
    onChange: (e) => {
      const val = e.target.value;
      if (val === "custom") {
        customTimerOpen.total = true;
        const nextVal = curTotal ?? 1200;
        onChange({ totalTimeSec: nextVal, questionTimeSec: curQ });
        requestAnimationFrame(() => {
          const inp = document.getElementById(totalCustomId);
          inp?.focus();
          inp?.select?.();
        });
        return;
      }
      customTimerOpen.total = false;
      onChange({ totalTimeSec: val ? Number(val) : null, questionTimeSec: curQ });
    },
  });
  const totalChoices = [
    { value: "", label: "Без обмеження" },
    { value: "300", label: "5 хв" },
    { value: "600", label: "10 хв" },
    { value: "900", label: "15 хв" },
    { value: "1800", label: "30 хв" },
    { value: "3600", label: "60 хв" },
    { value: "custom", label: "Свій час (хв)…" },
  ];
  const activeTotalOpt = isCustomTotal ? "custom" : curTotal != null ? String(curTotal) : "";
  for (const ch of totalChoices) {
    totalSel.appendChild(
      el("option", { value: ch.value, text: ch.label, selected: activeTotalOpt === ch.value })
    );
  }

  const totalRowChildren = [totalSel];
  if (isCustomTotal) {
    const commitTotalCustom = (rawStr, silent = false) => {
      const cleaned = rawStr.trim();
      if (!cleaned) {
        if (curTotal !== null || !silent) {
          curTotal = null;
          onChange({ totalTimeSec: null, questionTimeSec: curQ, silent });
        }
        return;
      }
      const mins = Math.trunc(Number(cleaned));
      if (!Number.isFinite(mins) || mins <= 0) return;
      const clampedSec = Math.min(240, Math.max(1, mins)) * 60;
      if (clampedSec !== curTotal || !silent) {
        curTotal = clampedSec;
        onChange({ totalTimeSec: curTotal, questionTimeSec: curQ, silent });
      }
    };
    const defaultMins = curTotal != null ? Math.max(1, Math.round(curTotal / 60)) : 20;
    const totalInput = el("input", {
      id: totalCustomId,
      name: "total_time_custom_min",
      type: "text",
      inputmode: "numeric",
      pattern: "[0-9]*",
      className: "timer-custom-input",
      "aria-label": "Загальний час тесту у хвилинах",
      value: String(defaultMins),
      onInput: (e) => commitTotalCustom(e.target.value, true),
      onKeydown: (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commitTotalCustom(e.target.value, false);
        }
      },
    });
    totalRowChildren.push(
      el("span", { className: "timer-custom-wrap" }, [totalInput, el("span", { className: "muted", text: "хв" })])
    );
  }

  grid.appendChild(
    el("div", { className: "cascade-field" }, [
      el("label", { for: totalSelId, className: "cascade-label", text: "⏱ Загальний час тесту" }),
      el("div", { className: "timer-field-row" }, totalRowChildren),
    ])
  );

  // 2. Per-question time (seconds)
  const qSelId = `${idPrefix}-question-time-select`;
  const qCustomId = `${idPrefix}-question-time-custom`;
  const qSel = el("select", {
    id: qSelId,
    name: "question_time_sec",
    className: "brand-select",
    onChange: (e) => {
      const val = e.target.value;
      if (val === "custom") {
        customTimerOpen.question = true;
        const nextVal = curQ ?? 25;
        onChange({ totalTimeSec: curTotal, questionTimeSec: nextVal });
        requestAnimationFrame(() => {
          const inp = document.getElementById(qCustomId);
          inp?.focus();
          inp?.select?.();
        });
        return;
      }
      customTimerOpen.question = false;
      onChange({ totalTimeSec: curTotal, questionTimeSec: val ? Number(val) : null });
    },
  });
  const qChoices = [
    { value: "", label: "Без обмеження" },
    { value: "15", label: "15 сек" },
    { value: "30", label: "30 сек" },
    { value: "45", label: "45 сек" },
    { value: "60", label: "60 сек" },
    { value: "90", label: "90 сек" },
    { value: "custom", label: "Свій час (сек)…" },
  ];
  const activeQOpt = isCustomQ ? "custom" : curQ != null ? String(curQ) : "";
  for (const ch of qChoices) {
    qSel.appendChild(
      el("option", { value: ch.value, text: ch.label, selected: activeQOpt === ch.value })
    );
  }

  const qRowChildren = [qSel];
  if (isCustomQ) {
    const commitQCustom = (rawStr, silent = false) => {
      const cleaned = rawStr.trim();
      if (!cleaned) {
        if (curQ !== null || !silent) {
          curQ = null;
          onChange({ totalTimeSec: curTotal, questionTimeSec: null, silent });
        }
        return;
      }
      const secs = Math.trunc(Number(cleaned));
      if (!Number.isFinite(secs) || secs <= 0) return;
      const clampedSec = Math.min(600, Math.max(5, secs));
      if (clampedSec !== curQ || !silent) {
        curQ = clampedSec;
        onChange({ totalTimeSec: curTotal, questionTimeSec: curQ, silent });
      }
    };
    const qInput = el("input", {
      id: qCustomId,
      name: "question_time_custom_sec",
      type: "text",
      inputmode: "numeric",
      pattern: "[0-9]*",
      className: "timer-custom-input",
      "aria-label": "Час на одне питання в секундах",
      value: String(curQ ?? 25),
      onInput: (e) => commitQCustom(e.target.value, true),
      onKeydown: (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commitQCustom(e.target.value, false);
        }
      },
    });
    qRowChildren.push(
      el("span", { className: "timer-custom-wrap" }, [qInput, el("span", { className: "muted", text: "с" })])
    );
  }

  grid.appendChild(
    el("div", { className: "cascade-field" }, [
      el("label", { for: qSelId, className: "cascade-label", text: "⏳ Час на 1 питання" }),
      el("div", { className: "timer-field-row" }, qRowChildren),
    ])
  );

  return grid;
}

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

function showDatabaseInfoModal() {
  const totalAll = state.subjects.reduce((acc, s) => acc + Number(s.total_questions || 0), 0);
  const verifiedCnt = state.health?.verified_questions ?? totalAll;
  const reviewCnt = state.health?.needs_review_questions ?? 0;
  const breakdown = state.subjects
    .map((s) => `${s.icon} ${s.title_uk}: ${s.total_questions}`)
    .join(" · ");
  const paragraphs = [
    `У тренажері зараз ${verifiedCnt} ${pluralUk(verifiedCnt, ["верифіковане питання", "верифіковані питання", "верифікованих питань"])} по ${state.subjects.length} ${pluralUk(state.subjects.length, ["предмету", "предметах", "предметах"])} КРОК-1 / ЄДКІ${breakdown ? ` (${breakdown})` : ""}.`,
    reviewCnt > 0
      ? `Ще ${reviewCnt} ${pluralUk(reviewCnt, ["питання", "питання", "питань"])} без надійно витягнутого ключа відповідей тимчасово приховано з активних тестів і симулятора іспиту, щоб не викривляти статистику.`
      : "Усі активні тести в базі мають перевірений ключ відповіді.",
    "Повтори між тематичними базами, буклетами КРОК та екзаменаційними банками дедупліковано в єдині картки зі збереженням тегів усіх джерел.",
    "Миттєвий пошук індексує умову клінічного кейса та правильну відповідь по всіх предметах, а в режимах тренування й іспиту варіанти A–E щоразу перемішуються незалежно.",
  ];
  showInfoDialog("Про базу тестів KrokFlow", paragraphs);
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
    announce(
      `Перенесено ${res.merged_attempts} ${pluralUk(res.merged_attempts, ["відповідь", "відповіді", "відповідей"])} та ${res.merged_bookmarks} ${pluralUk(res.merged_bookmarks, ["закладку", "закладки", "закладок"])}`
    );
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
  if (state.screen === "profile") {
    state.screen = "dashboard";
    pushRoute("/", { replace: true });
  }
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
        text: `Буфер браузера: ${attCnt} ${pluralUk(attCnt, ["відповідь", "відповіді", "відповідей"])} і ${buf.bookmarks.length} ${pluralUk(buf.bookmarks.length, ["закладка", "закладки", "закладок"])} готові до переносу`,
      })
    );
  }

  if (state.auth.enabled && state.auth.botUsername) {
    const slot = el("div", { className: "tg-widget-slot" });
    const loadingEl = el("div", { className: "tg-loading" }, [
      el("span", { className: "spinner", "aria-hidden": "true" }),
      el("span", { text: "Завантаження Telegram…" }),
    ]);
    slot.appendChild(loadingEl);

    const removeLoader = () => {
      if (loadingEl.isConnected) loadingEl.remove();
    };
    const fallbackTimer = setTimeout(removeLoader, 6000);
    const observer = new MutationObserver(() => {
      const iframe = slot.querySelector("iframe");
      if (iframe) {
        observer.disconnect();
        iframe.addEventListener(
          "load",
          () => {
            clearTimeout(fallbackTimer);
            removeLoader();
          },
          { once: true }
        );
      }
    });
    observer.observe(slot, { childList: true, subtree: true });
    authDialog.addEventListener(
      "close",
      () => {
        observer.disconnect();
        clearTimeout(fallbackTimer);
      },
      { once: true }
    );

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

function syncBookmarkCountBadges() {
  const cnt = getBookmarkedCount();
  const chipCntEl = document.querySelector("#dash-bookmarks-chip .chip-count");
  if (chipCntEl) chipCntEl.textContent = String(cnt);
  const kpiValEl = document.querySelector("#hero-bookmarks-kpi .kpi-value");
  if (kpiValEl) kpiValEl.textContent = String(cnt);
}

async function handleBookmarkToggle(q, rerenderFn) {
  const wasBookmarked = isQuestionBookmarked(q);
  const nextState = !wasBookmarked;
  if (!state.auth.authenticated) {
    const saved = toggleGuestBookmark(q.id);
    q.bookmarked = saved;
    syncBookmarkCountBadges();
    rerenderFn();
    announce(saved ? "Додано в закладки браузера" : "Прибрано із закладок");
    return;
  }
  try {
    const res = await api.toggleBookmark(q.id, nextState);
    q.bookmarked = res.bookmarked;
    if (state.stats?.summary && res.bookmarked !== wasBookmarked) {
      state.stats.summary.bookmarked_count = Math.max(
        0,
        Number(state.stats.summary.bookmarked_count || 0) + (res.bookmarked ? 1 : -1)
      );
    }
    syncBookmarkCountBadges();
    rerenderFn();
    announce(res.bookmarked ? "Збережено у закладки" : "Прибрано із закладок");
  } catch (err) {
    showInfoDialog("Помилка закладки", [err.message]);
  }
}

function getBookmarkedCount() {
  if (state.auth.authenticated && state.stats?.summary) {
    return Number(state.stats.summary.bookmarked_count || 0);
  }
  const buf = loadGuestBuffer();
  return buf.bookmarks.length;
}

async function loadBookmarksData() {
  state.bookmarksLoading = true;
  if (state.screen === "bookmarks") render();
  try {
    const ids = state.auth.authenticated ? [] : loadGuestBuffer().bookmarks;
    const res = !state.auth.authenticated && !ids.length
      ? { total: 0, items: [] }
      : await api.getBookmarks(ids);
    state.bookmarks = res;
  } catch (err) {
    state.bookmarks = { total: 0, items: [], error: err.message };
  } finally {
    state.bookmarksLoading = false;
    if (state.screen === "bookmarks") render();
  }
}

async function openBookmarks(opts = {}) {
  const pushUrl = opts && typeof opts === "object" && "pushUrl" in opts ? opts.pushUrl : true;
  stopQuizTimers();
  stopExamTimer();
  state.screen = "bookmarks";
  setDocumentTitle("Закладки");
  if (pushUrl) pushRoute("/bookmarks");
  await loadBookmarksData();
}

// ---------- Navigation, History API Routing & Session Launchers ----------

function pushRoute(path, { replace = false } = {}) {
  try {
    const target = path.startsWith("/") ? path : `/${path}`;
    const current = window.location.pathname + window.location.search;
    if (current === target) return;
    if (replace) window.history.replaceState(null, "", target);
    else window.history.pushState(null, "", target);
  } catch {
    // Ignore History API restrictions outside normal browser navigation.
  }
}

function buildDashboardFilterUrl(cascade = state.cascade) {
  const params = new URLSearchParams();
  if (cascade.subjectId != null) params.set("subject", String(cascade.subjectId));
  if (cascade.sourceKind && cascade.sourceKind !== "all") params.set("kind", cascade.sourceKind);
  if (Array.isArray(cascade.itemKeys) && cascade.itemKeys.length > 1) {
    params.set("items", cascade.itemKeys.join(","));
  } else if (cascade.itemKeys?.length === 1) {
    params.set("item", cascade.itemKeys[0]);
  } else if (cascade.itemKey && cascade.itemKey !== "all" && cascade.itemKey !== "multi") {
    params.set("item", cascade.itemKey);
  }
  if (cascade.totalTimeSec > 0) params.set("t_total", String(cascade.totalTimeSec));
  if (cascade.questionTimeSec > 0) params.set("t_q", String(cascade.questionTimeSec));
  const qs = params.toString();
  return qs ? `/?${qs}` : "/";
}

function buildModeSelectorPath(sel = state.selection) {
  let base = "/";
  if (sel.topicId != null) base = `/topic/${sel.topicId}`;
  else if (sel.moduleNo != null) base = `/module/${sel.moduleNo}`;
  else if (sel.subjectId != null) base = `/subject/${sel.subjectId}`;
  else base = "/subject/0";
  const params = new URLSearchParams();
  if (sel.moduleNo != null && sel.subjectId != null && base.startsWith("/module/")) {
    params.set("subject", String(sel.subjectId));
  }
  if (Array.isArray(sel.topicIds) && sel.topicIds.length) {
    params.set("topics", sel.topicIds.join(","));
  }
  if (sel.sourceKind && sel.sourceKind !== "all") {
    params.set("kind", sel.sourceKind);
  }
  if (sel.sourceTag) params.set("source", sel.sourceTag);
  if (Array.isArray(sel.sourceTags) && sel.sourceTags.length) {
    params.set("tags", sel.sourceTags.join(","));
  }
  if (sel.limit && sel.limit !== 20) params.set("limit", String(sel.limit));
  if (sel.hintsEnabled && state.auth.authenticated) params.set("hints", "1");
  if (sel.totalTimeSec > 0) params.set("t_total", String(sel.totalTimeSec));
  if (sel.questionTimeSec > 0) params.set("t_q", String(sel.questionTimeSec));
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

function buildSessionQuery({
  subjectId,
  moduleNo,
  topicId,
  topicIds,
  sourceTag,
  sourceTags,
  limit,
  hintsEnabled,
  totalTimeSec,
  questionTimeSec,
} = {}) {
  const params = new URLSearchParams();
  if (subjectId != null) params.set("subject", String(subjectId));
  if (moduleNo != null) params.set("module", String(moduleNo));
  if (topicId != null) params.set("topic", String(topicId));
  if (Array.isArray(topicIds) && topicIds.length) params.set("topics", topicIds.join(","));
  if (sourceTag) params.set("source", sourceTag);
  if (Array.isArray(sourceTags) && sourceTags.length) params.set("tags", sourceTags.join(","));
  if (limit && limit !== 20) params.set("limit", String(limit));
  if (hintsEnabled) params.set("hints", "1");
  if (totalTimeSec > 0) params.set("t_total", String(totalTimeSec));
  if (questionTimeSec > 0) params.set("t_q", String(questionTimeSec));
  return params.toString();
}

function goDashboard(opts = {}) {
  const pushUrl = opts && typeof opts === "object" && "pushUrl" in opts ? opts.pushUrl : true;
  stopQuizTimers();
  stopExamTimer();
  state.screen = "dashboard";
  setDocumentTitle("Дашборд");
  if (pushUrl) {
    const q = state.searchQuery.trim();
    pushRoute(q ? `/search?q=${encodeURIComponent(q)}` : buildDashboardFilterUrl(state.cascade));
  }
  render();
  if (state.auth.authenticated) {
    refreshCatalogAndStats().then(() => {
      if (state.screen === "dashboard") render();
    }).catch(() => {});
  }
}

function openProfile(opts = {}) {
  const pushUrl = opts && typeof opts === "object" && "pushUrl" in opts ? opts.pushUrl : true;
  stopQuizTimers();
  stopExamTimer();
  state.screen = "profile";
  setDocumentTitle("Профіль та аналітика");
  if (pushUrl) pushRoute("/profile");
  render();
  if (state.auth.authenticated) {
    refreshCatalogAndStats().then(() => {
      if (state.screen === "profile") render();
    }).catch(() => {});
  }
}

function openModeSelector(scope, opts = {}) {
  const pushUrl = opts && typeof opts === "object" && "pushUrl" in opts ? opts.pushUrl : true;
  stopQuizTimers();
  stopExamTimer();
  const totalTimeSec =
    scope.totalTimeSec !== undefined ? sanitizeTimerSec(scope.totalTimeSec, { min: 5, max: 14400 }) : state.cascade.totalTimeSec;
  const questionTimeSec =
    scope.questionTimeSec !== undefined ? sanitizeTimerSec(scope.questionTimeSec, { min: 5, max: 600 }) : state.cascade.questionTimeSec;
  state.selection = {
    subjectId: scope.subjectId ?? null,
    subjectTitle: scope.subjectTitle ?? "Усі предмети",
    moduleNo: scope.moduleNo ?? null,
    topicId: scope.topicId ?? null,
    topicIds: scope.topicIds ?? null,
    sourceTag: scope.sourceTag ?? null,
    sourceTags: scope.sourceTags ?? null,
    sourceKind: scope.sourceKind ?? "all",
    limit: scope.limit ?? 20,
    totalTimeSec: totalTimeSec ?? null,
    questionTimeSec: questionTimeSec ?? null,
    hintsEnabled: Boolean(scope.hintsEnabled && state.auth.authenticated),
    title: scope.title ?? scope.subjectTitle ?? "Усі предмети КРОК-1",
  };
  state.cascade.totalTimeSec = state.selection.totalTimeSec;
  state.cascade.questionTimeSec = state.selection.questionTimeSec;
  syncCascadeFromSelection(state.subjects, state.selection, state.cascade);
  state.screen = "mode";
  setDocumentTitle(state.selection.title);
  if (pushUrl) pushRoute(buildModeSelectorPath(state.selection));
  render();
}

async function startTraining(
  {
    mode = "train",
    subjectId = state.selection.subjectId,
    moduleNo = state.selection.moduleNo,
    topicId = state.selection.topicId,
    topicIds = state.selection.topicIds,
    questionIds = null,
    sourceTag = state.selection.sourceTag,
    sourceTags = state.selection.sourceTags,
    limit = state.selection.limit,
    hintsEnabled = Boolean(state.selection.hintsEnabled && state.auth.authenticated),
    totalTimeSec = state.selection.totalTimeSec,
    questionTimeSec = state.selection.questionTimeSec,
    title = state.selection.title,
  } = {},
  { pushUrl = true } = {}
) {
  try {
    const cleanTotalSec = sanitizeTimerSec(totalTimeSec, { min: 5, max: 14400 });
    const cleanQSec = sanitizeTimerSec(questionTimeSec, { min: 5, max: 600 });
    const guestQuestionIds =
      mode === "bookmarks" && !state.auth.authenticated && (!questionIds || !questionIds.length)
        ? loadGuestBuffer().bookmarks
        : questionIds;
    const resp = await api.startQuizSession({
      mode,
      subject_id: subjectId,
      module_no: moduleNo,
      topic_id: topicId,
      topic_ids: topicIds,
      question_ids: guestQuestionIds,
      source_tag: sourceTag,
      source_tags: sourceTags,
      limit,
      hints_enabled: Boolean(hintsEnabled || mode === "hints"),
    });
    if (!resp.questions.length) {
      if (!document.querySelector(".hero-card") && state.screen === "dashboard") render();
      const msg =
        mode === "mistakes"
          ? "У вас зараз немає активних помилок або прострочених повторень SM-2!"
          : mode === "bookmarks"
            ? "Поки що немає збережених закладок для тренування."
            : "За цими фільтрами не знайдено верифікованих питань. Спробуйте скинути фільтр джерела або теми.";
      showInfoDialog("Порожня вибірка", [msg]);
      return;
    }
    stopQuizTimers();
    stopExamTimer();
    state.quiz = {
      sessionId: resp.session_id,
      title,
      questions: resp.questions,
      idx: 0,
      answers: new Map(),
      struck: new Map(),
      summaryReveals: new Map(),
      hintsEnabled: Boolean(resp.hints_enabled),
      showMarkers: Boolean(resp.hints_enabled),
      totalTimeSec: cleanTotalSec,
      totalRemainingSec: cleanTotalSec,
      questionTimeSec: cleanQSec,
      questionRemainingSec: cleanQSec,
      timerId: null,
      timedOutReason: null,
      xMode: false,
      finished: false,
    };
    state.screen = "quiz";
    setDocumentTitle(`Тренування · ${title}`);
    if (pushUrl) {
      const qs = buildSessionQuery({
        subjectId,
        moduleNo,
        topicId,
        topicIds,
        sourceTag,
        sourceTags,
        limit,
        hintsEnabled: Boolean(resp.hints_enabled),
        totalTimeSec: cleanTotalSec,
        questionTimeSec: cleanQSec,
      });
      pushRoute(qs ? `/mode/${encodeURIComponent(mode)}?${qs}` : `/mode/${encodeURIComponent(mode)}`);
    }
    render();
    startQuizTimers();
    announce(`Почато тренування: ${resp.questions.length} ${pluralUk(resp.questions.length, ["питання", "питання", "питань"])}`);
  } catch (err) {
    if (!document.querySelector(".hero-card") && state.screen === "dashboard") render();
    if (err.message.includes("Telegram") || err.message.includes("Увійдіть")) {
      openAuthDialog(err.message);
      return;
    }
    showInfoDialog("Помилка запуску", [err.message]);
  }
}

async function startFlashcards(opts = {}) {
  const pushUrl = opts && typeof opts === "object" && "pushUrl" in opts ? opts.pushUrl : true;
  stopQuizTimers();
  stopExamTimer();
  try {
    const resp = await api.startQuizSession({
      mode: "flashcards",
      subject_id: state.selection.subjectId,
      module_no: state.selection.moduleNo,
      topic_id: state.selection.topicId,
      topic_ids: state.selection.topicIds,
      source_tag: state.selection.sourceTag,
      source_tags: state.selection.sourceTags,
      limit: state.selection.limit,
      hints_enabled: Boolean(state.selection.hintsEnabled && state.auth.authenticated),
    });
    if (!resp.questions.length) {
      if (!document.querySelector(".hero-card") && state.screen === "dashboard") render();
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
    if (pushUrl) {
      const qs = buildSessionQuery({
        subjectId: state.selection.subjectId,
        moduleNo: state.selection.moduleNo,
        topicId: state.selection.topicId,
        topicIds: state.selection.topicIds,
        sourceTag: state.selection.sourceTag,
        sourceTags: state.selection.sourceTags,
        limit: state.selection.limit,
        hintsEnabled: Boolean(resp.hints_enabled),
      });
      pushRoute(qs ? `/flashcards?${qs}` : "/flashcards");
    }
    render();
    announce(`Флешкартки готові: ${resp.questions.length} ${pluralUk(resp.questions.length, ["картка", "картки", "карток"])}`);
  } catch (err) {
    if (!document.querySelector(".hero-card") && state.screen === "dashboard") render();
    showInfoDialog("Помилка запуску", [err.message]);
  }
}

async function startExamSimulator(
  {
    subjectId = null,
    moduleNo = null,
    topicId = null,
    topicIds = null,
    sourceTag = null,
    sourceTags = null,
    questionCount = 150,
    totalTimeSec = null,
    questionTimeSec = null,
    title = "Симулятор іспиту КРОК-1",
  } = {},
  { pushUrl = true } = {}
) {
  try {
    const cleanTotalSec = sanitizeTimerSec(totalTimeSec, { min: 5, max: 14400 });
    const cleanQSec = sanitizeTimerSec(questionTimeSec, { min: 5, max: 600 });
    const resp = await api.startExam({
      subject_id: subjectId,
      module_no: moduleNo,
      topic_id: topicId,
      topic_ids: topicIds,
      source_tag: sourceTag,
      source_tags: sourceTags,
      question_count: questionCount,
    });
    if (!resp.questions.length) {
      if (!document.querySelector(".hero-card") && state.screen === "dashboard") render();
      showInfoDialog("Порожня вибірка", ["Недостатньо питань для старту симуляції іспиту."]);
      return;
    }
    stopQuizTimers();
    stopExamTimer();
    const initialDuration = cleanTotalSec ?? resp.duration_sec;
    state.exam = {
      examId: resp.exam_id,
      title,
      questions: resp.questions,
      idx: 0,
      selected: new Map(),
      flagged: new Set(),
      struck: new Map(),
      timedOutIds: new Set(),
      totalTimeSec: cleanTotalSec,
      remainingSec: initialDuration,
      totalDurationSec: initialDuration,
      questionTimeSec: cleanQSec,
      questionRemainingSec: cleanQSec,
      passThreshold: resp.pass_threshold_pct,
      startedMs: Date.now(),
      timerId: null,
      submitting: false,
      results: null,
      reviewFilter: "wrong",
    };
    state.screen = "exam";
    setDocumentTitle("Іспит КРОК-1");
    if (pushUrl) {
      const qs = buildSessionQuery({
        subjectId,
        moduleNo,
        topicId,
        topicIds,
        sourceTag,
        sourceTags,
        limit: questionCount !== 150 ? questionCount : null,
        totalTimeSec: cleanTotalSec,
        questionTimeSec: cleanQSec,
      });
      pushRoute(qs ? `/exam?${qs}` : "/exam");
    }
    startExamTimer();
    render();
    announce(`Симулятор іспиту запущено: ${resp.total_questions} ${pluralUk(resp.total_questions, ["питання", "питання", "питань"])}`);
  } catch (err) {
    if (!document.querySelector(".hero-card") && state.screen === "dashboard") render();
    showInfoDialog("Помилка запуску іспиту", [err.message]);
  }
}

async function applyRouteFromLocation() {
  stopQuizTimers();
  stopExamTimer();
  const path = window.location.pathname || "/";
  const params = new URLSearchParams(window.location.search);
  const subj = state.subjects[0] || null;
  const sourceTag = params.get("source") || null;
  const sourceTagsRaw = params.get("tags");
  const sourceTags = sourceTagsRaw ? sourceTagsRaw.split(",").map((s) => s.trim()).filter(Boolean) : null;
  const topicIdsRaw = params.get("topics");
  const parsedTopicIds = topicIdsRaw ? topicIdsRaw.split(",").map(Number).filter(Boolean) : null;
  const limitParam = Number(params.get("limit") || 0);
  const limit = limitParam > 0 ? limitParam : 20;
  const hintsRequested = params.get("hints") === "1";
  const sourceKind = params.get("kind") || null;
  const totalTimeSec = sanitizeTimerSec(params.get("t_total"), { min: 5, max: 14400 });
  const questionTimeSec = sanitizeTimerSec(params.get("t_q"), { min: 5, max: 600 });

  const modMatch = path.match(/^\/module\/(\d+)\/?$/);
  if (modMatch) {
    const moduleNo = Number(modMatch[1]);
    const requestedSubjId = params.has("subject") ? Number(params.get("subject")) : null;
    const targetSubj =
      (requestedSubjId != null ? state.subjects.find((s) => s.id === requestedSubjId) : null) ||
      state.subjects.find((s) => s.modules.some((m) => m.module_no === moduleNo)) ||
      subj;
    const mod = targetSubj?.modules.find((m) => m.module_no === moduleNo);
    if (targetSubj && mod) {
      openModeSelector(
        {
          subjectId: targetSubj.id,
          subjectTitle: targetSubj.title_uk,
          moduleNo: mod.module_no,
          topicIds: parsedTopicIds,
          sourceTag,
          sourceTags,
          sourceKind,
          limit,
          totalTimeSec,
          questionTimeSec,
          hintsEnabled: hintsRequested,
          title: mod.title_uk,
        },
        { pushUrl: false }
      );
      return;
    }
  }

  const topicMatch = path.match(/^\/topic\/(\d+)\/?$/);
  if (topicMatch) {
    const topicId = Number(topicMatch[1]);
    for (const s of state.subjects) {
      for (const mod of s.modules) {
        const topic = mod.topics.find((t) => t.id === topicId);
        if (topic) {
          openModeSelector(
            {
              subjectId: s.id,
              subjectTitle: s.title_uk,
              moduleNo: mod.module_no,
              topicId: topic.id,
              topicIds: parsedTopicIds,
              sourceTag,
              sourceTags,
              sourceKind,
              limit,
              totalTimeSec,
              questionTimeSec,
              hintsEnabled: hintsRequested,
              title: topic.title_uk,
            },
            { pushUrl: false }
          );
          return;
        }
      }
    }
  }

  const subjMatch = path.match(/^\/subject\/(\d+)\/?$/);
  if (subjMatch) {
    const sid = Number(subjMatch[1]);
    if (sid === 0) {
      openModeSelector(
        {
          subjectId: null,
          subjectTitle: "Усі предмети",
          topicIds: parsedTopicIds,
          sourceTag,
          sourceTags,
          sourceKind,
          limit,
          totalTimeSec,
          questionTimeSec,
          hintsEnabled: hintsRequested,
          title: parsedTopicIds?.length
            ? `Обрано ${parsedTopicIds.length} ${pluralUk(parsedTopicIds.length, ["тему", "теми", "тем"])}`
            : sourceTag
              ? `Усі предмети · ${sourceTag}`
              : "Усі предмети КРОК-1",
        },
        { pushUrl: false }
      );
      return;
    }
    const targetSubj = state.subjects.find((s) => s.id === sid) || subj;
    if (targetSubj) {
      openModeSelector(
        {
          subjectId: targetSubj.id,
          subjectTitle: targetSubj.title_uk,
          topicIds: parsedTopicIds,
          sourceTag,
          sourceTags,
          sourceKind,
          limit,
          totalTimeSec,
          questionTimeSec,
          hintsEnabled: hintsRequested,
          title: parsedTopicIds?.length
            ? `Обрано ${parsedTopicIds.length} ${pluralUk(parsedTopicIds.length, ["тему", "теми", "тем"])}`
            : sourceTag
              ? `${targetSubj.title_uk} · ${sourceTag}`
              : targetSubj.title_uk,
        },
        { pushUrl: false }
      );
      return;
    }
  }

  const modeMatch = path.match(/^\/mode\/([a-z0-9_-]+)\/?$/i);
  if (modeMatch) {
    const mode = modeMatch[1];
    const subjectId = params.has("subject") ? Number(params.get("subject")) : null;
    const moduleNo = params.has("module") ? Number(params.get("module")) : null;
    const topicId = params.has("topic") ? Number(params.get("topic")) : null;
    const topicIds = parsedTopicIds;
    const targetSubj = subjectId != null ? state.subjects.find((s) => s.id === subjectId) : subj;
    let title = subjectId != null ? (targetSubj?.title_uk ?? "КРОК-1") : "Обрані теми КРОК-1";
    if (topicIds?.length) {
      title = `Обрано ${topicIds.length} ${pluralUk(topicIds.length, ["тему", "теми", "тем"])}`;
    } else if (topicId != null && targetSubj) {
      for (const m of targetSubj.modules) {
        const t = m.topics.find((x) => x.id === topicId);
        if (t) {
          title = t.title_uk;
          break;
        }
      }
    } else if (moduleNo != null && targetSubj) {
      const m = targetSubj.modules.find((x) => x.module_no === moduleNo);
      if (m) title = m.title_uk;
    } else if (mode === "smart_mix") {
      title = "Розумна сесія · Мікс";
    } else if (mode === "mistakes") {
      title = "Помилки та повтори SM-2";
    } else if (mode === "weak_topics") {
      title = "Закрити 3 найслабші теми";
    }
    state.selection = {
      ...state.selection,
      subjectId,
      moduleNo,
      topicId,
      topicIds,
      sourceTag,
      sourceTags,
      limit,
      totalTimeSec,
      questionTimeSec,
      hintsEnabled: Boolean(hintsRequested && state.auth.authenticated),
      title,
    };
    await startTraining(
      {
        mode,
        subjectId,
        moduleNo,
        topicId,
        topicIds,
        sourceTag,
        sourceTags,
        limit,
        totalTimeSec,
        questionTimeSec,
        hintsEnabled: hintsRequested,
        title,
      },
      { pushUrl: false }
    );
    return;
  }

  if (path === "/flashcards") {
    const subjectId = params.has("subject") ? Number(params.get("subject")) : null;
    const moduleNo = params.has("module") ? Number(params.get("module")) : null;
    const topicId = params.has("topic") ? Number(params.get("topic")) : null;
    const topicIds = parsedTopicIds;
    state.selection = {
      ...state.selection,
      subjectId,
      moduleNo,
      topicId,
      topicIds,
      sourceTag,
      sourceTags,
      limit,
      hintsEnabled: Boolean(hintsRequested && state.auth.authenticated),
    };
    await startFlashcards({ pushUrl: false });
    return;
  }

  if (path === "/exam") {
    const subjectId = params.has("subject") ? Number(params.get("subject")) : null;
    const moduleNo = params.has("module") ? Number(params.get("module")) : null;
    const topicId = params.has("topic") ? Number(params.get("topic")) : null;
    const questionCount = limitParam > 0 ? limitParam : 150;
    await startExamSimulator(
      {
        subjectId,
        moduleNo,
        topicId,
        topicIds: parsedTopicIds,
        sourceTag,
        sourceTags,
        questionCount,
        totalTimeSec,
        questionTimeSec,
        title: `Симулятор КРОК-1 (${questionCount})`,
      },
      { pushUrl: false }
    );
    return;
  }

  if (path === "/profile") {
    if (state.auth.authenticated) {
      openProfile({ pushUrl: false });
      return;
    }
    goDashboard({ pushUrl: false });
    openAuthDialog("Увійдіть через Telegram, щоб відкрити профіль та аналітику.");
    return;
  }

  if (path === "/bookmarks") {
    await openBookmarks({ pushUrl: false });
    return;
  }

  if (path === "/search") {
    const q = (params.get("q") || "").trim();
    state.screen = "dashboard";
    state.searchQuery = q;
    setDocumentTitle(q ? `Пошук: ${q}` : "Дашборд");
    if (!q) {
      state.searchResponse = null;
      state.searchLoading = false;
      render();
      return;
    }
    state.searchLoading = true;
    render();
    try {
      const res = await api.searchQuestions({ q, limit: 30 });
      if (state.searchQuery.trim() === q) {
        state.searchResponse = res;
        state.searchLoading = false;
        renderSearchResultsRegion();
      }
    } catch (err) {
      state.searchLoading = false;
      state.searchResponse = { query: q, query_terms: [], elapsed_ms: 0, total: 0, items: [], error: err.message };
      renderSearchResultsRegion();
    }
    return;
  }

  state.searchQuery = "";
  state.searchResponse = null;
  state.searchLoading = false;
  if (params.has("subject") || params.has("kind") || params.has("item") || params.has("items") || params.has("t_total") || params.has("t_q")) {
    const rawSubj = params.get("subject");
    state.cascade.subjectId = rawSubj && Number(rawSubj) > 0 ? Number(rawSubj) : null;
    state.cascade.sourceKind = params.get("kind") || "all";
    const itemsParam = params.get("items");
    if (itemsParam) {
      state.cascade.itemKeys = itemsParam.split(",").map((s) => s.trim()).filter(Boolean);
      state.cascade.itemKey = state.cascade.itemKeys.length > 1 ? "multi" : (state.cascade.itemKeys[0] || "all");
    } else {
      const singleItem = params.get("item") || "all";
      state.cascade.itemKey = singleItem;
      state.cascade.itemKeys = singleItem !== "all" ? [singleItem] : [];
    }
    state.cascade.totalTimeSec = totalTimeSec;
    state.cascade.questionTimeSec = questionTimeSec;
  }
  goDashboard({ pushUrl: false });
}

function stopQuizTimers() {
  if (state.quiz && state.quiz.timerId) {
    clearInterval(state.quiz.timerId);
    state.quiz.timerId = null;
  }
}

function advanceQuizStep() {
  const qz = state.quiz;
  if (!qz) return;
  if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur();
  }
  if (qz.idx + 1 < qz.questions.length) {
    qz.idx++;
    if (qz.questionTimeSec != null) {
      qz.questionRemainingSec = qz.questionTimeSec;
    }
  } else {
    qz.finished = true;
    stopQuizTimers();
  }
  render();
}

function startQuizTimers() {
  stopQuizTimers();
  const qz = state.quiz;
  if (!qz || (qz.totalTimeSec == null && qz.questionTimeSec == null)) return;

  qz.timerId = setInterval(() => {
    const cur = state.quiz;
    if (!cur || state.screen !== "quiz" || cur.finished) {
      stopQuizTimers();
      return;
    }

    if (cur.totalRemainingSec != null) {
      cur.totalRemainingSec = Math.max(0, cur.totalRemainingSec - 1);
      const totalPill = document.getElementById("quiz-total-timer");
      if (totalPill) {
        totalPill.textContent = `⏱ ${formatDuration(cur.totalRemainingSec)}`;
        const lowThreshold = Math.min(60, Math.ceil((cur.totalTimeSec || 60) * 0.2));
        totalPill.classList.toggle("is-low", cur.totalRemainingSec <= lowThreshold);
      }
      if (cur.totalRemainingSec === 0) {
        cur.timedOutReason = "total";
        cur.finished = true;
        stopQuizTimers();
        announce("Загальний час тесту вичерпано. Сесію завершено.");
        render();
        return;
      }
    }

    if (cur.questionRemainingSec != null) {
      const q = cur.questions[cur.idx];
      if (q && !cur.answers.has(q.id)) {
        cur.questionRemainingSec = Math.max(0, cur.questionRemainingSec - 1);
        const qPill = document.getElementById("quiz-question-timer");
        if (qPill) {
          qPill.textContent = `⏳ ${formatDuration(cur.questionRemainingSec)}`;
          const qLow = Math.min(10, Math.ceil((cur.questionTimeSec || 15) * 0.25));
          qPill.classList.toggle("is-low", cur.questionRemainingSec <= qLow);
        }
        if (cur.questionRemainingSec === 0) {
          cur.answers.set(q.id, {
            question_id: q.id,
            is_correct: false,
            timed_out: true,
            selected_option_id: null,
            correct_option_id: null,
            correct_text: null,
          });
          if (!state.auth.authenticated) {
            recordGuestAttempt(q.id, false);
          }
          if (cur.idx + 1 < cur.questions.length) {
            cur.idx++;
            cur.questionRemainingSec = cur.questionTimeSec;
            announce("Час на питання вийшов — питання не зараховано.");
          } else {
            cur.finished = true;
            stopQuizTimers();
            announce("Час на останнє питання вийшов. Сесію завершено.");
          }
          render();
        }
      }
    }
  }, 1000);
}

function startExamTimer() {
  stopExamTimer();
  if (!state.exam) return;
  state.exam.timerId = setInterval(() => {
    const ex = state.exam;
    if (!ex || state.screen !== "exam") {
      stopExamTimer();
      return;
    }
    ex.remainingSec = Math.max(0, ex.remainingSec - 1);
    const pill = document.getElementById("exam-timer-pill");
    if (pill) {
      pill.textContent = `⏱ ${formatDuration(ex.remainingSec)}`;
      const lowLimit = ex.totalDurationSec ? Math.min(300, Math.ceil(ex.totalDurationSec * 0.2)) : 300;
      pill.classList.toggle("is-low", ex.remainingSec <= lowLimit);
    }
    if (ex.remainingSec === 0) {
      stopExamTimer();
      finalizeExam();
      return;
    }

    if (ex.questionRemainingSec != null) {
      const q = ex.questions[ex.idx];
      if (q && !ex.selected.has(q.id) && !ex.timedOutIds.has(q.id)) {
        ex.questionRemainingSec = Math.max(0, ex.questionRemainingSec - 1);
        const qPill = document.getElementById("exam-question-timer");
        if (qPill) {
          qPill.textContent = `⏳ ${formatDuration(ex.questionRemainingSec)}`;
          const qLow = Math.min(10, Math.ceil((ex.questionTimeSec || 15) * 0.25));
          qPill.classList.toggle("is-low", ex.questionRemainingSec <= qLow);
        }
        if (ex.questionRemainingSec === 0) {
          ex.timedOutIds.add(q.id);
          if (ex.idx + 1 < ex.questions.length) {
            ex.idx++;
            ex.questionRemainingSec = ex.questionTimeSec;
            announce("Час на питання вийшов — питання не зараховано.");
            render();
          } else {
            stopExamTimer();
            finalizeExam();
          }
        }
      }
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
  let kbdHint;
  let clearBtn;
  const searchInput = el("input", {
    id: "search-input",
    type: "search",
    className: "search-input",
    placeholder: "Пошук КРОК-1 за симптомом, збудником, реакцією…",
    value: state.searchQuery,
    autocomplete: "off",
    autocorrect: "off",
    autocapitalize: "none",
    spellcheck: "false",
    enterkeyhint: "search",
    onInput: (e) => {
      state.searchQuery = e.target.value;
      const hasInput = Boolean(state.searchQuery.length);
      if (kbdHint) kbdHint.hidden = hasInput;
      if (clearBtn) clearBtn.hidden = !hasInput;
      clearTimeout(searchTimer);
      const q = state.searchQuery.trim();
      if (!q) {
        state.searchResponse = null;
        state.searchLoading = false;
        setDocumentTitle("Дашборд");
        pushRoute("/", { replace: true });
        renderSearchResultsRegion();
        return;
      }
      state.searchLoading = true;
      renderSearchResultsRegion();
      searchTimer = setTimeout(async () => {
        pushRoute(`/search?q=${encodeURIComponent(q)}`, { replace: true });
        try {
          const res = await api.searchQuestions({ q, limit: 30 });
          if (state.searchQuery.trim() === q) {
            state.searchResponse = res;
            state.searchLoading = false;
            renderSearchResultsRegion();
            announce(`Знайдено ${res.total} ${pluralUk(res.total, ["питання", "питання", "питань"])} за ${res.elapsed_ms} мс`);
          }
        } catch (err) {
          if (state.searchQuery.trim() === q) {
            state.searchLoading = false;
            state.searchResponse = { query: q, query_terms: [], elapsed_ms: 0, total: 0, items: [], error: err.message };
            renderSearchResultsRegion();
          }
        }
      }, 160);
    },
  });

  const hasInitialQuery = Boolean(state.searchQuery.length);
  kbdHint = el("span", {
    id: "search-kbd-hint",
    className: "search-kbd",
    text: "⌘K",
    hidden: hasInitialQuery,
  });
  clearBtn = el(
    "button",
    {
      id: "search-clear-btn",
      type: "button",
      className: "search-clear-btn",
      "aria-label": "Очистити пошук",
      hidden: !hasInitialQuery,
      onClick: () => {
        clearTimeout(searchTimer);
        state.searchQuery = "";
        state.searchResponse = null;
        state.searchLoading = false;
        searchInput.value = "";
        kbdHint.hidden = false;
        clearBtn.hidden = true;
        setDocumentTitle("Дашборд");
        pushRoute("/", { replace: true });
        renderSearchResultsRegion();
        searchInput.focus();
      },
    },
    [createCloseIconSvg()]
  );

  const searchBox = el("div", { className: "search-box" }, [
    el("span", { className: "search-icon", "aria-hidden": "true", text: "🔍" }),
    searchLabel,
    searchInput,
    kbdHint,
    clearBtn,
  ]);
  searchWrap.appendChild(searchBox);

  // Compact quick-jump bar (Bookmarks + active subject filter indicator)
  const bmkCnt = getBookmarkedCount();
  const quickBar = el("div", { className: "chips-row" }, [
    el(
      "button",
      {
        type: "button",
        id: "dash-bookmarks-chip",
        className: "chip",
        onClick: () => openBookmarks(),
      },
      [el("span", { text: "🔖 Закладки" }), el("span", { className: "chip-count", text: bmkCnt })]
    ),
  ]);
  for (const s of state.subjects) {
    quickBar.appendChild(
      el(
        "button",
        {
          type: "button",
          className: `chip ${state.cascade.subjectId === s.id ? "active" : ""}`,
          onClick: () => {
            state.cascade.subjectId = state.cascade.subjectId === s.id ? null : s.id;
            state.cascade.sourceKind = "all";
            state.cascade.itemKey = "all";
            state.cascade.itemKeys = [];
            pushRoute(buildDashboardFilterUrl(state.cascade), { replace: true });
            render();
          },
        },
        [el("span", { text: `${s.icon} ${s.title_uk}` }), el("span", { className: "chip-count", text: s.total_questions })]
      )
    );
  }
  searchWrap.appendChild(quickBar);

  const resultsRegion = el("div", { id: "search-results-region", className: "stack-sm" });
  searchWrap.appendChild(resultsRegion);
  root.appendChild(searchWrap);

  // Hero Quick-Start Card
  const totalAllSubjects = state.subjects.reduce((acc, s) => acc + Number(s.total_questions || 0), 0);
  const verifiedCnt = state.health?.verified_questions ?? totalAllSubjects;
  const hero = el("section", { className: "card hero-card" }, [
    el("div", { className: "row-between" }, [
      el("div", {}, [
        el("h1", { text: "KrokFlow · КРОК-1 / ЄДКІ" }),
        el("p", {
          className: "muted",
          style: "margin:0",
          text: "Клінічна база тестів для підготовки до КРОК-1: миттєвий пошук по базі, інтервальні повтори SM-2 та підказки маркерів.",
        }),
      ]),
    ]),
    el("div", { className: "stat-badges" }, [
      el("span", { className: "badge badge-accent", text: `✓ ${verifiedCnt} верифіковано` }),
      el("button", {
        type: "button",
        id: "hero-db-info-btn",
        className: "badge badge-btn",
        text: "ℹ️ Про базу",
        onClick: showDatabaseInfoModal,
      }),
      el("span", { className: "badge", text: "🔀 Варіанти перемішуються щоразу" }),
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
          el("button", {
            type: "button",
            id: "hero-bookmarks-kpi",
            className: "kpi-card kpi-card-btn",
            onClick: () => openBookmarks(),
          }, [
            el("span", { className: "kpi-value", text: `${state.stats.summary.bookmarked_count}` }),
            el("span", { className: "kpi-label kpi-action-hint", text: "🔖 Збережені закладки →" }),
          ]),
        ])
      : null,
    el("div", { className: "hero-actions" }, [
      el("button", {
        type: "button",
        id: "hero-smart-btn",
        className: "btn btn-primary",
        text: "▶ Розумна сесія (20 питань)",
        onClick: () =>
          startTraining({
            mode: "smart_mix",
            subjectId: null,
            moduleNo: null,
            topicId: null,
            topicIds: null,
            sourceTag: null,
            sourceTags: null,
            totalTimeSec: null,
            questionTimeSec: null,
            limit: 20,
            title: "Розумна сесія · Мікс",
          }),
      }),
      el("button", {
        type: "button",
        id: "hero-exam-btn",
        className: "btn btn-secondary",
        text: "⏱ Симулятор іспиту (150)",
        onClick: () =>
          startExamSimulator({
            questionCount: 150,
            totalTimeSec: null,
            questionTimeSec: null,
            title: "Симулятор КРОК-1 (150)",
          }),
      }),
      el("button", {
        type: "button",
        id: "hero-mistakes-btn",
        className: "btn btn-secondary",
        onClick: () =>
          state.auth.authenticated
            ? startTraining({
                mode: "mistakes",
                subjectId: null,
                moduleNo: null,
                topicId: null,
                topicIds: null,
                sourceTag: null,
                sourceTags: null,
                totalTimeSec: null,
                questionTimeSec: null,
                limit: 25,
                title: "Помилки та повторення SM-2",
              })
            : openAuthDialog("Персональна черга помилок і повторень SM-2 працює після входу через Telegram."),
      }, state.auth.authenticated
        ? [state.stats?.summary?.due_count ? `🧠 Помилки / SM-2 (${state.stats.summary.due_count})` : "🧠 Помилки / SM-2"]
        : ["🔒 Помилки / SM-2", el("span", { className: "btn-lock-tag", text: "Telegram" })]),
      el("button", {
        type: "button",
        id: "hero-weak-btn",
        className: "btn btn-secondary",
        onClick: () =>
          state.auth.authenticated
            ? startTraining({
                mode: "weak_topics",
                subjectId: null,
                moduleNo: null,
                topicId: null,
                topicIds: null,
                sourceTag: null,
                sourceTags: null,
                totalTimeSec: null,
                questionTimeSec: null,
                limit: 20,
                title: "Закрити 3 найслабші теми",
              })
            : openAuthDialog("Відпрацювання 3 найслабших тем за рейтингом SM-2 доступне після входу через Telegram."),
      }, state.auth.authenticated
        ? ["🔥 Закрити 3 слабкі теми"]
        : ["🔒 Закрити 3 слабкі теми", el("span", { className: "btn-lock-tag", text: "Telegram" })]),
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

  // Cascading Subject -> Source/Type -> Topic/Year Selector Card
  if (state.subjects.length) {
    const cascadeUi = createCascadeSelector({
      idPrefix: "dash-cascade",
      subjects: state.subjects,
      cascade: state.cascade,
      onChange: () => {
        pushRoute(buildDashboardFilterUrl(state.cascade), { replace: true });
        render();
      },
    });
    const resolved = cascadeUi.resolved;
    const availableCount = Number(resolved.questionCount || 0);
    const effectiveCount = Math.min(20, availableCount);
    const isEmptyScope = availableCount <= 0;

    const cascadeCard = el("section", { id: "cascade-selector-card", className: "card cascade-card" }, [
      el("div", { className: "row-between" }, [
        el("div", {}, [
          el("h2", { style: "margin:0", text: "Конструктор тесту" }),
          el("p", {
            className: "muted",
            style: "margin:4px 0 0;font-size:13.5px",
            text: "Оберіть предмет, тип джерела та конкретну тему або рік буклету.",
          }),
        ]),
        el("span", {
          id: "cascade-count-badge",
          className: "badge badge-accent",
          text: `${availableCount} ${pluralUk(availableCount, ["питання", "питання", "питань"])}`,
        }),
      ]),
      cascadeUi.element,
      buildTimerConfigControls({
        idPrefix: "dash-cascade",
        totalTimeSec: state.cascade.totalTimeSec,
        questionTimeSec: state.cascade.questionTimeSec,
        onChange: ({ totalTimeSec, questionTimeSec, silent = false }) => {
          state.cascade.totalTimeSec = totalTimeSec;
          state.cascade.questionTimeSec = questionTimeSec;
          pushRoute(buildDashboardFilterUrl(state.cascade), { replace: true });
          if (!silent) render();
        },
      }),
      isEmptyScope
        ? el("p", {
            className: "muted",
            style: "margin:0;font-size:13.5px",
            text: "За обраними фільтрами немає доступних питань — змініть джерело або тему.",
          })
        : null,
      el("div", { className: "cascade-actions" }, [
        el("button", {
          type: "button",
          id: "cascade-open-mode-btn",
          className: "btn btn-primary",
          disabled: isEmptyScope,
          text: "🎯 Обрати режим →",
          onClick: () =>
            openModeSelector({
              ...resolved,
              limit: effectiveCount || 20,
              totalTimeSec: state.cascade.totalTimeSec,
              questionTimeSec: state.cascade.questionTimeSec,
            }),
        }),
        el("button", {
          type: "button",
          id: "cascade-quick-train-btn",
          className: "btn btn-secondary",
          disabled: isEmptyScope,
          text: isEmptyScope ? "▶ Немає питань за фільтром" : `▶ Тренування (${effectiveCount})`,
          onClick: () =>
            startTraining({
              ...resolved,
              mode: "train",
              limit: effectiveCount,
              totalTimeSec: state.cascade.totalTimeSec,
              questionTimeSec: state.cascade.questionTimeSec,
            }),
        }),
      ]),
    ]);
    root.appendChild(cascadeCard);

    // Compact 3-subject overview cards
    const subjGrid = el("section", { className: "subjects-overview-grid", "aria-label": "Дисципліни КРОК-1" });
    for (const s of state.subjects) {
      const topicsCnt = s.modules.reduce((acc, m) => acc + (m.topics?.length || 0), 0);
      subjGrid.appendChild(
        el(
          "button",
          {
            type: "button",
            className: `subject-mini-card ${state.cascade.subjectId === s.id ? "is-active" : ""}`,
            onClick: () => {
              state.cascade.subjectId = s.id;
              state.cascade.sourceKind = "all";
              state.cascade.itemKey = "all";
              state.cascade.itemKeys = [];
              pushRoute(buildDashboardFilterUrl(state.cascade), { replace: true });
              render();
              document.getElementById("cascade-selector-card")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
            },
          },
          [
            el("div", { className: "row-between" }, [
              el("strong", { text: `${s.icon} ${s.title_uk}` }),
              el("span", { className: "badge", text: `${s.total_questions}` }),
            ]),
            el("span", {
              className: "muted",
              style: "font-size:13px",
              text: `${topicsCnt} ${pluralUk(topicsCnt, ["розділ", "розділи", "розділів"])}`,
            }),
            renderProgressPill(s),
          ]
        )
      );
    }
    root.appendChild(subjGrid);
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
    region.appendChild(el("div", { className: "card muted", text: "Пошук у базі…" }));
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
      el("span", {
        className: "muted",
        style: "font-size:13.5px",
        text: `Результати для «${res.query}»: ${res.total} ${pluralUk(res.total, ["питання", "питання", "питань"])}`,
      }),
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
  const sel = state.selection;
  const root = el("div", { className: "stack-lg" });

  const cascadeUi = createCascadeSelector({
    idPrefix: "mode-cascade",
    subjects: state.subjects,
    cascade: state.cascade,
    onChange: (nextScope) => {
      sel.subjectId = nextScope.subjectId;
      sel.subjectTitle = nextScope.subjectTitle;
      sel.moduleNo = nextScope.moduleNo;
      sel.topicId = nextScope.topicId;
      sel.topicIds = nextScope.topicIds ?? null;
      sel.sourceTag = nextScope.sourceTag;
      sel.sourceTags = nextScope.sourceTags ?? null;
      sel.sourceKind = nextScope.sourceKind ?? "all";
      sel.title = nextScope.title;
      const nextMax = Math.min(Number(nextScope.questionCount || 0), 150);
      if (nextMax > 0 && sel.limit > nextMax) {
        sel.limit = nextMax;
      }
      setDocumentTitle(sel.title);
      pushRoute(buildModeSelectorPath(sel), { replace: true });
      render();
    },
  });
  const availableCount = Number(cascadeUi.resolved.questionCount || 0);
  const maxSelectable = Math.min(availableCount, 150);
  const isEmptyScope = availableCount <= 0;
  if (maxSelectable > 0 && sel.limit > maxSelectable) {
    sel.limit = maxSelectable;
  }

  root.appendChild(
    el("div", { className: "row-between" }, [
      el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← Назад", onClick: () => goDashboard() }),
      el("span", {
        className: "badge badge-accent",
        text: `${availableCount} ${pluralUk(availableCount, ["тест", "тести", "тестів"])} у вибірці`,
      }),
    ])
  );

  root.appendChild(
    el("div", {}, [
      el("h1", { text: sel.title }),
      el("p", { className: "muted", style: "margin:0", text: "Оберіть предмет, джерело, тему або рік буклету та формат тренування." }),
    ])
  );

  // Filters card with cascading dropdowns
  const filterCard = el("section", { className: "card stack-md" });
  filterCard.appendChild(cascadeUi.element);

  // Question count pills (clamped to availableCount so UI never promises 20 when only 10 exist)
  const countChips = el("div", { className: "chips-row", id: "mode-limit-chips" });
  if (maxSelectable > 0) {
    const presetCounts = [10, 20, 30, 50].filter((c) => c < maxSelectable);
    const allChoices = [...presetCounts, maxSelectable];
    for (const cnt of allChoices) {
      const isAllCap = cnt === maxSelectable;
      const label = isAllCap
        ? availableCount > 150
          ? "Усі (до 150)"
          : `Усі (${cnt})`
        : `${cnt} ${pluralUk(cnt, ["питання", "питання", "питань"])}`;
      countChips.appendChild(
        el("button", {
          type: "button",
          className: `chip ${sel.limit === cnt ? "active" : ""}`,
          text: label,
          onClick: () => {
            sel.limit = cnt;
            pushRoute(buildModeSelectorPath(sel), { replace: true });
            render();
          },
        })
      );
    }
  } else {
    countChips.appendChild(
      el("span", {
        className: "muted",
        style: "font-size:13.5px",
        text: "За обраними фільтрами немає доступних питань — змініть джерело або тему.",
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
    buildTimerConfigControls({
      idPrefix: "mode-cascade",
      totalTimeSec: sel.totalTimeSec,
      questionTimeSec: sel.questionTimeSec,
      onChange: ({ totalTimeSec, questionTimeSec, silent = false }) => {
        sel.totalTimeSec = totalTimeSec;
        sel.questionTimeSec = questionTimeSec;
        state.cascade.totalTimeSec = totalTimeSec;
        state.cascade.questionTimeSec = questionTimeSec;
        pushRoute(buildModeSelectorPath(sel), { replace: true });
        if (!silent) render();
      },
    })
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
            pushRoute(buildModeSelectorPath(sel), { replace: true });
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
      className: `mode-card ${isEmptyScope ? "is-muted" : ""}`,
      disabled: isEmptyScope,
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
      className: `mode-card ${state.auth.authenticated && !isEmptyScope ? "" : "is-muted"}`,
      disabled: isEmptyScope,
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
      className: `mode-card ${isEmptyScope ? "is-muted" : ""}`,
      disabled: isEmptyScope,
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
      className: `mode-card ${isEmptyScope ? "is-muted" : ""}`,
      disabled: isEmptyScope,
      onClick: () =>
        startExamSimulator({
          subjectId: sel.subjectId,
          moduleNo: sel.moduleNo,
          topicId: sel.topicId,
          topicIds: sel.topicIds,
          sourceTag: sel.sourceTag,
          sourceTags: sel.sourceTags,
          questionCount: Math.max(sel.limit, 150),
          totalTimeSec: sel.totalTimeSec,
          questionTimeSec: sel.questionTimeSec,
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
  const totalLow = qz.totalRemainingSec != null && qz.totalRemainingSec <= Math.min(60, Math.ceil((qz.totalTimeSec || 60) * 0.2));
  const qLow = qz.questionRemainingSec != null && qz.questionRemainingSec <= Math.min(10, Math.ceil((qz.questionTimeSec || 15) * 0.25));
  const qPaused = Boolean(ans);

  const hdr = el("div", { className: "session-header" }, [
    el("div", { className: "row-between" }, [
      el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← Вийти", onClick: goDashboard }),
      el("div", { className: "stat-badges quiz-timers-row" }, [
        qz.totalRemainingSec != null
          ? el("span", {
              id: "quiz-total-timer",
              className: `timer-pill ${totalLow ? "is-low" : ""}`,
              title: "Загальний час, що залишився на тест",
              text: `⏱ ${formatDuration(qz.totalRemainingSec)}`,
            })
          : null,
        qz.questionRemainingSec != null
          ? el("span", {
              id: "quiz-question-timer",
              className: `timer-pill ${!qPaused && qLow ? "is-low" : ""}`,
              title: qPaused ? "Таймер питання на паузі під час перегляду розбору" : "Час на поточне питання",
              text: `${qPaused ? "⏸" : "⏳"} ${formatDuration(qz.questionRemainingSec)}`,
            })
          : null,
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
          onClick: advanceQuizStep,
        }),
      ]),
      el("div", { text: `Правильна відповідь: ${ans.correct_text}` }),
    ];

    const exp = ans.explanation;
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
      verdictChildren.push(el("div", { className: "explain-box" }, expNodes));
    }

    verdictChildren.push(
      el("div", { className: "quiz-meta-footer" }, [
        buildReportTriggerButton(q, { id: "quiz-report-btn" }),
      ])
    );

    root.appendChild(
      el("section", { className: `verdict-sheet ${ans.is_correct ? "is-correct" : "is-wrong"}` }, verdictChildren)
    );
  } else {
    root.appendChild(
      el("div", { className: "quiz-meta-footer" }, [
        el("p", {
          className: "muted",
          style: "margin:0;font-size:12.5px",
          text: "Хоткеї ПК: 1–5 або A–E — відповідь · X потім 1–5 — закреслити варіант",
        }),
        buildReportTriggerButton(q, { id: "quiz-report-btn" }),
      ])
    );
  }

  mainEl.appendChild(root);
}

function renderQuizSummary() {
  const qz = state.quiz;
  stopQuizTimers();
  const total = qz.questions.length;
  let correctCnt = 0;
  let timedOutCnt = 0;
  const missed = [];
  for (const q of qz.questions) {
    const a = qz.answers.get(q.id);
    if (a && a.is_correct) {
      correctCnt++;
    } else {
      if (!a || a.timed_out) timedOutCnt++;
      missed.push({ q, a });
    }
  }
  const pct = total ? Math.round((correctCnt / total) * 100) : 0;
  const summaryNote =
    timedOutCnt > 0
      ? `Правильно ${correctCnt} із ${total} ${pluralUk(total, ["питання", "питань", "питань"])} · Не зараховано через час: ${timedOutCnt} (${qz.title}).`
      : `Правильно ${correctCnt} із ${total} ${pluralUk(total, ["питання", "питань", "питань"])} (${qz.title}).`;

  const root = el("div", { className: "stack-lg" }, [
    el("section", { className: "card stack-md" }, [
      qz.timedOutReason === "total"
        ? el("span", { id: "quiz-timeout-badge", className: "badge badge-red", text: "⏱ Загальний час тесту вичерпано" })
        : null,
      el("h1", { text: `Сесію завершено: ${pct}%` }),
      el("p", {
        className: "muted",
        style: "margin:0",
        text: summaryNote,
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
                  summaryReveals: new Map(),
                  hintsEnabled: Boolean(qz.hintsEnabled),
                  showMarkers: Boolean(qz.hintsEnabled),
                  totalTimeSec: qz.totalTimeSec ?? null,
                  totalRemainingSec: qz.totalTimeSec ?? null,
                  questionTimeSec: qz.questionTimeSec ?? null,
                  questionRemainingSec: qz.questionTimeSec ?? null,
                  timerId: null,
                  timedOutReason: null,
                  xMode: false,
                  finished: false,
                };
                render();
                startQuizTimers();
              },
            })
          : null,
        el("button", { type: "button", className: "btn btn-primary", text: "Нова сесія", onClick: () => openModeSelector(state.selection) }),
        el("button", { type: "button", className: "btn btn-secondary", text: "На головну", onClick: goDashboard }),
      ]),
    ]),
  ]);

  if (missed.length) {
    const revWrap = el("section", { className: "stack-sm" }, [el("h2", { text: "Питання з помилками та пропуски" })]);
    for (const { q, a } of missed) {
      const cardNodes = [];
      if (!a || a.timed_out) {
        cardNodes.push(
          el("span", { className: "badge badge-red", text: "⏱ Час вийшов — не зараховано" })
        );
      }
      cardNodes.push(el("p", { style: "margin:0;font-weight:550", text: q.stem }));
      const revealed = qz.summaryReveals?.get(q.id);
      if (a && a.correct_text) {
        cardNodes.push(el("div", { className: "spoiler-answer", text: `✓ ${a.correct_text}` }));
      } else if (revealed) {
        cardNodes.push(el("div", { className: "spoiler-answer", text: `✓ Правильна відповідь: ${revealed.correct_text}` }));
      } else {
        cardNodes.push(
          el("div", {}, [
            el("button", {
              type: "button",
              className: "btn btn-secondary btn-sm summary-reveal-btn",
              text: "👁 Показати правильну відповідь",
              onClick: async () => {
                const rev = await api.revealQuestion(q.id, q.shuffle_salt);
                if (!qz.summaryReveals) qz.summaryReveals = new Map();
                qz.summaryReveals.set(q.id, rev);
                render();
              },
            }),
          ])
        );
      }
      cardNodes.push(el("div", { className: "summary-card-footer" }, [buildReportTriggerButton(q)]));
      revWrap.appendChild(el("article", { className: "card stack-sm" }, cardNodes));
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
          if (ex.questionTimeSec != null) ex.questionRemainingSec = ex.questionTimeSec;
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
  const isTimedOutQ = Boolean(ex.timedOutIds?.has(q.id));
  const isFlagged = ex.flagged.has(q.id);
  const struckSet = ex.struck.get(q.id) || new Set();
  const lowTotalLimit = ex.totalDurationSec ? Math.min(300, Math.ceil(ex.totalDurationSec * 0.2)) : 300;
  const qLow = ex.questionRemainingSec != null && ex.questionRemainingSec <= Math.min(10, Math.ceil((ex.questionTimeSec || 15) * 0.25));

  const root = el("div", { className: "stack-md" });

  root.appendChild(
    el("div", { className: "session-header" }, [
      el("div", { className: "row-between" }, [
        el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← Вийти", onClick: goDashboard }),
        el("div", { className: "quiz-timers-row" }, [
          el("span", {
            id: "exam-timer-pill",
            className: `timer-pill ${ex.remainingSec <= lowTotalLimit ? "is-low" : ""}`,
            text: `⏱ ${formatDuration(ex.remainingSec)}`,
          }),
          ex.questionRemainingSec != null
            ? el("span", {
                id: "exam-question-timer",
                className: `timer-pill ${!selectedId && !isTimedOutQ && qLow ? "is-low" : ""}`,
                text: `${selectedId ? "⏸" : "⏳"} ${formatDuration(ex.questionRemainingSec)}`,
              })
            : null,
        ]),
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
        isTimedOutQ ? el("span", { className: "badge badge-red", text: "⏱ Час вийшов — не зараховано" }) : null,
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
        disabled: isTimedOutQ,
        onClick: () => {
          if (isTimedOutQ) return;
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
      disabled: isTimedOutQ,
      onClick: () => {
        if (isTimedOutQ) return;
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
            if (ex.questionTimeSec != null) ex.questionRemainingSec = ex.questionTimeSec;
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
            if (ex.questionTimeSec != null) ex.questionRemainingSec = ex.questionTimeSec;
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
        text: `Правильно ${res.correct_count} із ${res.total_questions} ${pluralUk(res.total_questions, ["питання", "питань", "питань"])} · Надано ${res.answered_count} ${pluralUk(res.answered_count, ["відповідь", "відповіді", "відповідей"])} · Час: ${formatDuration(res.duration_sec)}.`,
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
                  totalTimeSec: null,
                  questionTimeSec: null,
                  limit: 20,
                  title: "Закриття слабких тем",
                }),
            })
          : null,
        el("button", {
          type: "button",
          className: "btn btn-primary",
          text: "Новий іспит",
          onClick: () => startExamSimulator({ totalTimeSec: ex.totalTimeSec ?? null, questionTimeSec: ex.questionTimeSec ?? null }),
        }),
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
            el("button", {
              type: "button",
              id: "profile-bookmarks-kpi",
              className: "kpi-card kpi-card-btn",
              onClick: () => openBookmarks(),
            }, [
              el("span", { className: "kpi-value", text: `${st.summary.bookmarked_count}` }),
              el("span", { className: "kpi-label kpi-action-hint", text: "🔖 Закладки →" }),
            ]),
          ])
        : el("div", { className: "muted", text: "Завантаження аналітики…" }),
      el("div", { className: "hero-actions" }, [
        el("button", {
          type: "button",
          className: "btn btn-primary",
          text: "🧠 Робота над помилками / SM-2",
          onClick: () =>
            startTraining({
              mode: "mistakes",
              subjectId: null,
              moduleNo: null,
              topicId: null,
              topicIds: null,
              sourceTag: null,
              sourceTags: null,
              totalTimeSec: null,
              questionTimeSec: null,
              limit: 25,
              title: "Помилки та повтори SM-2",
            }),
        }),
        el("button", {
          type: "button",
          className: "btn btn-secondary",
          text: "🔥 Закрити 3 слабкі теми",
          onClick: () =>
            startTraining({
              mode: "weak_topics",
              subjectId: null,
              moduleNo: null,
              topicId: null,
              topicIds: null,
              sourceTag: null,
              sourceTags: null,
              totalTimeSec: null,
              questionTimeSec: null,
              limit: 20,
              title: "Закрити 3 найслабші теми",
            }),
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
        el("div", { className: "weak-topic-row" }, [
          el("div", { className: "weak-topic-info" }, [
            el("div", { style: "font-weight:600;font-size:14.5px", text: wt.title_uk }),
            el("div", { className: "muted", style: "font-size:12.5px", text: `Модуль ${wt.module_no} · ${wt.wrong_cnt} ${pluralUk(wt.wrong_cnt, ["помилка", "помилки", "помилок"])} · точність ${wt.accuracy_pct}%` }),
          ]),
          el("button", {
            type: "button",
            className: "btn btn-secondary btn-sm weak-topic-btn",
            text: "Тренувати →",
            onClick: () =>
              startTraining({
                mode: "smart_mix",
                moduleNo: wt.module_no,
                topicId: wt.topic_id,
                totalTimeSec: null,
                questionTimeSec: null,
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
      el("div", { className: "row-between" }, [
        el("h2", { text: `Збережені закладки (${st.bookmarked_questions.length})` }),
        el("button", {
          type: "button",
          className: "btn btn-ghost btn-sm",
          text: "Всі закладки →",
          onClick: () => openBookmarks(),
        }),
      ]),
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

  root.appendChild(
    el("section", { id: "profile-reset-card", className: "card stack-sm danger-zone-card" }, [
      el("h2", { style: "margin:0", text: "Керування прогресом" }),
      el("p", {
        className: "muted",
        style: "margin:0;font-size:13.5px",
        text: "Скиньте всю історію відповідей, точність по темах, повтори SM-2 та історію іспитів, щоб почати підготовку з чистого аркуша.",
      }),
      el("div", { className: "hero-actions" }, [
        el("button", {
          type: "button",
          id: "profile-reset-stats-btn",
          className: "btn btn-danger btn-sm",
          text: "🗑 Скинути результати та аналітику",
          onClick: () => {
            const cb = document.getElementById("reset-keep-bookmarks");
            if (cb) cb.checked = true;
            resetStatsDialog?.showModal();
          },
        }),
      ]),
    ])
  );

  mainEl.appendChild(root);
}

// ---------- Screen 7: Saved Bookmarks (/bookmarks) ----------

function renderBookmarks() {
  const root = el("div", { className: "stack-lg" });
  const data = state.bookmarks;
  const items = data?.items || [];

  root.appendChild(
    el("div", { className: "row-between" }, [
      el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "← На головну", onClick: () => goDashboard() }),
      el("span", {
        className: "badge badge-accent",
        text: `🔖 ${items.length} ${pluralUk(items.length, ["закладка", "закладки", "закладок"])}`,
      }),
    ])
  );

  const headerActions = items.length
    ? [
        el("button", {
          type: "button",
          id: "bookmarks-train-btn",
          className: "btn btn-primary btn-sm",
          text: `▶ Тренувати закладки (${items.length})`,
          onClick: () =>
            startTraining({
              mode: "bookmarks",
              questionIds: items.map((q) => q.id),
              limit: Math.min(150, Math.max(items.length, 20)),
              title: "Закладки",
            }),
        }),
      ]
    : [];

  root.appendChild(
    el("section", { className: "card stack-md" }, [
      el("div", { className: "row-between" }, [
        el("div", {}, [
          el("h1", { text: "Збережені закладки" }),
          el("p", {
            className: "muted",
            style: "margin:0",
            text: state.auth.authenticated
              ? "Персональна добірка питань КРОК-1, збережених у вашому профілі."
              : "Локальна добірка браузера — синхронізується з профілем після входу через Telegram.",
          }),
        ]),
        ...headerActions,
      ]),
    ])
  );

  if (state.bookmarksLoading) {
    root.appendChild(el("div", { className: "card muted", text: "Завантаження закладок…" }));
    mainEl.appendChild(root);
    return;
  }

  if (data?.error) {
    root.appendChild(el("div", { className: "card", text: `Не вдалося завантажити закладки: ${data.error}` }));
    mainEl.appendChild(root);
    return;
  }

  if (!items.length) {
    root.appendChild(
      el("section", { id: "bookmarks-empty-state", className: "card stack-md" }, [
        el("div", { style: "font-weight:700;font-size:17px", text: "Поки що немає збережених закладок" }),
        el("p", {
          className: "muted",
          style: "margin:0",
          text: "Натискайте ☆ у картках пошуку, під час тренування або на флешкартках, щоб відкладати складні тести КРОК-1 сюди для швидкого повторення.",
        }),
        el("div", { className: "hero-actions" }, [
          el("button", {
            type: "button",
            className: "btn btn-primary",
            text: "🔍 Відкрити пошук тестів",
            onClick: () => {
              goDashboard();
              requestAnimationFrame(() => document.getElementById("search-input")?.focus());
            },
          }),
          el("button", {
            type: "button",
            className: "btn btn-secondary",
            text: "Обрати тему",
            onClick: () => {
              const subj = state.subjects[0];
              openModeSelector({
                subjectId: subj?.id ?? null,
                subjectTitle: subj?.title_uk ?? "Мікробіологія",
                title: subj?.title_uk ?? "Мікробіологія",
              });
            },
          }),
        ]),
      ])
    );
    mainEl.appendChild(root);
    return;
  }

  for (const item of items) {
    const tagsRow = el("div", { className: "chips-row" });
    if (item.topic_title) {
      tagsRow.appendChild(el("span", { className: "badge", text: item.topic_title }));
    }
    for (const tag of item.source_tags || []) {
      tagsRow.appendChild(el("span", { className: "badge badge-accent", text: tag }));
    }

    const toolbar = el("div", { className: "question-toolbar" }, [
      tagsRow,
      el("button", {
        type: "button",
        className: "bookmark-btn",
        "aria-pressed": "true",
        "aria-label": "Прибрати із закладок",
        text: "🔖",
        onClick: async () => {
          await handleBookmarkToggle(item, () => {});
          state.bookmarks = {
            ...state.bookmarks,
            items: (state.bookmarks?.items || []).filter((x) => x.id !== item.id),
          };
          state.bookmarks.total = state.bookmarks.items.length;
          if (state.auth.authenticated) {
            refreshCatalogAndStats().catch(() => {});
          }
          render();
        },
      }),
    ]);

    const revealed = state.revealedBookmarkIds.get(item.id);
    const cardChildren = [
      toolbar,
      el("p", { className: "search-stem", text: item.stem }),
    ];
    if (revealed) {
      cardChildren.push(el("div", { className: "spoiler-answer", text: `✓ Правильна відповідь: ${revealed.correct_text}` }));
      if (revealed.explanation?.anchor_uk) {
        cardChildren.push(el("div", { className: "badge badge-amber", text: `✨ Якір КРОК: ${revealed.explanation.anchor_uk}` }));
      }
      if (revealed.explanation?.explanation_uk) {
        cardChildren.push(el("div", { className: "muted", style: "font-size:13.5px", text: revealed.explanation.explanation_uk }));
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
              state.revealedBookmarkIds.set(item.id, rev);
              render();
            },
          }),
        ])
      );
    }
    root.appendChild(el("article", { className: "card search-result-card" }, cardChildren));
  }

  mainEl.appendChild(root);
}

// ---------- Root Render & Global Keyboard Shortcuts ----------

let lastRenderScreen = null;
let lastRenderPathname = null;
let lastQuizSessionId = null;
let lastQuizIdx = null;
let lastQuizFinished = null;
let lastCardIdx = null;
let lastCardFinished = null;
let lastExamId = null;
let lastExamIdx = null;

function scrollPageToTop() {
  try {
    window.scrollTo({ top: 0, behavior: "instant" });
  } catch {
    window.scrollTo(0, 0);
  }
}

function blurFocusedElement({ keepSearch = false } = {}) {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement)) return;
  if (keepSearch && active.id === "search-input") return;
  active.blur();
}

function render() {
  const curPathname = window.location.pathname || "/";
  const screenChanged = state.screen !== lastRenderScreen;
  const pathSwapBetweenRootAndSearch =
    (lastRenderPathname === "/" && curPathname === "/search") ||
    (lastRenderPathname === "/search" && curPathname === "/");
  const routeChanged =
    lastRenderScreen !== null &&
    curPathname !== lastRenderPathname &&
    !(state.screen === "dashboard" && lastRenderScreen === "dashboard" && pathSwapBetweenRootAndSearch && document.activeElement?.id === "search-input");
  const quizStepChanged =
    state.screen === "quiz" &&
    state.quiz &&
    (state.quiz.sessionId !== lastQuizSessionId ||
      state.quiz.idx !== lastQuizIdx ||
      Boolean(state.quiz.finished) !== Boolean(lastQuizFinished));
  const cardStepChanged =
    state.screen === "flashcards" &&
    state.cards &&
    (state.cards.idx !== lastCardIdx || Boolean(state.cards.finished) !== Boolean(lastCardFinished));
  const examStepChanged =
    state.screen === "exam" &&
    state.exam &&
    (state.exam.examId !== lastExamId || state.exam.idx !== lastExamIdx);

  if (screenChanged || routeChanged || quizStepChanged || cardStepChanged || examStepChanged) {
    blurFocusedElement({ keepSearch: (screenChanged || routeChanged) && state.screen === "dashboard" });
  }

  clear(mainEl);
  updateAuthHeaderPill();
  if (state.screen === "dashboard") renderDashboard();
  else if (state.screen === "mode") renderModeSelector();
  else if (state.screen === "quiz") renderQuiz();
  else if (state.screen === "flashcards") renderFlashcards();
  else if (state.screen === "exam") renderExamRunner();
  else if (state.screen === "exam-results") renderExamResults();
  else if (state.screen === "profile") renderProfile();
  else if (state.screen === "bookmarks") renderBookmarks();

  if (screenChanged || routeChanged || quizStepChanged || cardStepChanged || examStepChanged) {
    scrollPageToTop();
  }

  lastRenderScreen = state.screen;
  lastRenderPathname = curPathname;
  lastQuizSessionId = state.quiz?.sessionId ?? null;
  lastQuizIdx = state.quiz?.idx ?? null;
  lastQuizFinished = state.quiz?.finished ?? null;
  lastCardIdx = state.cards?.idx ?? null;
  lastCardFinished = state.cards?.finished ?? null;
  lastExamId = state.exam?.examId ?? null;
  lastExamIdx = state.exam?.idx ?? null;
}

function setupGlobalEvents() {
  document.getElementById("brand-home-btn")?.addEventListener("click", () => {
    state.searchQuery = "";
    state.searchResponse = null;
    state.searchLoading = false;
    goDashboard({ pushUrl: true });
  });
  document.getElementById("shortcuts-btn")?.addEventListener("click", showShortcutsModal);
  document.getElementById("guest-pill-btn")?.addEventListener("click", () => {
    if (state.auth.authenticated) openProfile();
    else openAuthDialog();
  });
  window.addEventListener("popstate", () => {
    applyRouteFromLocation();
  });

  examConfirmDialog?.addEventListener("close", () => {
    const val = examConfirmDialog.returnValue;
    examConfirmDialog.returnValue = "";
    if (val === "confirm") {
      finalizeExam();
    }
  });

  resetStatsDialog?.addEventListener("close", async () => {
    const val = resetStatsDialog.returnValue;
    resetStatsDialog.returnValue = "";
    if (val !== "confirm") return;
    const keepBookmarks = Boolean(document.getElementById("reset-keep-bookmarks")?.checked ?? true);
    try {
      const res = await api.resetMyStats({ keepBookmarks });
      if (keepBookmarks) {
        clearGuestAttemptsOnly();
      } else {
        clearGuestBuffer();
        state.bookmarks = { total: 0, items: [] };
        state.revealedBookmarkIds.clear();
      }
      await refreshCatalogAndStats();
      syncBookmarkCountBadges();
      render();
      announce("Результати та аналітику скинуто");
      showInfoDialog("Аналітику скинуто", [
        keepBookmarks
          ? `Стерто історію відповідей і ${res.deleted_exam_sessions} ${pluralUk(res.deleted_exam_sessions, ["іспит", "іспити", "іспитів"])}. Збережені закладки залишилися недоторканими.`
          : `Повністю очищено результати, історію іспитів та закладки.`,
      ]);
    } catch (err) {
      showInfoDialog("Не вдалося скинути аналітику", [err.message]);
    }
  });

  document.getElementById("report-cancel-btn")?.addEventListener("click", () => {
    reportQuestionDialog?.close("cancel");
  });

  document.getElementById("report-comment-input")?.addEventListener("input", () => {
    const commentEl = document.getElementById("report-comment-input");
    const statusEl = document.getElementById("report-form-status");
    commentEl?.removeAttribute("aria-invalid");
    if (statusEl && statusEl.classList.contains("is-error")) {
      statusEl.textContent = "";
      statusEl.className = "report-form-status";
    }
  });

  reportQuestionDialog?.addEventListener("close", () => {
    reportQuestionDialog.returnValue = "";
    const statusEl = document.getElementById("report-form-status");
    if (statusEl) {
      statusEl.textContent = "";
      statusEl.className = "report-form-status";
    }
    reportingQuestion = null;
  });

  document.getElementById("report-question-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    const commentEl = document.getElementById("report-comment-input");
    const statusEl = document.getElementById("report-form-status");
    const submitBtn = document.getElementById("report-submit-btn");
    const q = reportingQuestion;
    if (!q) return;

    const fd = new FormData(form);
    const reason = String(fd.get("reason") || "wrong_key");
    const comment = String(fd.get("comment") || "").trim();

    if (reason === "other" && !comment) {
      commentEl?.setAttribute("aria-invalid", "true");
      if (statusEl) {
        statusEl.textContent = "Для причини «Інше» коротко опишіть помилку.";
        statusEl.className = "report-form-status is-error";
      }
      commentEl?.focus();
      return;
    }

    if (submitBtn) submitBtn.disabled = true;
    try {
      const res = await api.reportQuestion(q.id, { reason, comment });
      reportedQuestionIds.add(q.id);
      reportQuestionDialog?.close("submitted");
      render();
      announce(res.already_reported ? "Ви вже надсилали скаргу на це питання" : "Скаргу надіслано");
    } catch (err) {
      if (submitBtn) submitBtn.disabled = false;
      if (commentEl && String(err.message || "").includes("Інше")) {
        commentEl.setAttribute("aria-invalid", "true");
      }
      if (statusEl) {
        statusEl.textContent = err.message || "Не вдалося надіслати скаргу";
        statusEl.className = "report-form-status is-error";
      }
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
        advanceQuizStep();
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
      const isTimedOutQ = Boolean(ex.timedOutIds?.has(q.id));
      const mapKey = { "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, a: 0, b: 1, c: 2, d: 3, e: 4 };
      if (!isTimedOutQ && k in mapKey && mapKey[k] < q.options.length) {
        ex.selected.set(q.id, q.options[mapKey[k]].option_id);
        render();
      } else if (e.key === "ArrowRight" && ex.idx + 1 < ex.questions.length) {
        ex.idx++;
        if (ex.questionTimeSec != null) ex.questionRemainingSec = ex.questionTimeSec;
        render();
      } else if (e.key === "ArrowLeft" && ex.idx > 0) {
        ex.idx--;
        if (ex.questionTimeSec != null) ex.questionRemainingSec = ex.questionTimeSec;
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
    await applyRouteFromLocation();
  } catch (err) {
    clear(mainEl);
    mainEl.appendChild(el("div", { className: "card", text: `Не вдалося завантажити дані: ${err.message}` }));
  }
}

bootstrap();
