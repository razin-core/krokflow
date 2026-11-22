/** Color-scheme manager synced with <meta name="color-scheme"> and cross-tab storage. */

const STORAGE_KEY = "krok-color-scheme";

function getMeta() {
  return document.querySelector('meta[name="color-scheme"]');
}

export function getActiveScheme() {
  const meta = getMeta();
  const val = meta ? meta.content : "dark";
  if (val === "light" || val === "dark") return val;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyScheme(scheme, { persist = true } = {}) {
  const target = scheme === "light" ? "light" : "dark";
  const meta = getMeta();
  if (meta) meta.content = target;
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, target);
    } catch {
      // Ignore storage blocks; in-memory <meta> update still works.
    }
  }
}

export function initThemeToggle(btn) {
  if (!btn) return;
  btn.addEventListener("click", () => {
    const next = getActiveScheme() === "dark" ? "light" : "dark";
    applyScheme(next, { persist: true });
  });

  window.addEventListener("storage", (e) => {
    if (e.key === STORAGE_KEY) {
      applyScheme(e.newValue === "light" ? "light" : "dark", { persist: false });
    }
  });
}
