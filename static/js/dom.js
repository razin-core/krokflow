/** Safe DOM helpers (zero innerHTML on untrusted text) and dialog polyfill fallback. */

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, val] of Object.entries(attrs)) {
    if (val === undefined || val === null || val === false) continue;
    if (key === "className") {
      node.className = val;
    } else if (key === "text") {
      node.textContent = String(val);
    } else if (key === "dataset" && typeof val === "object") {
      for (const [dk, dv] of Object.entries(val)) {
        node.dataset[dk] = String(dv);
      }
    } else if (key.startsWith("on") && typeof val === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), val);
    } else if (val === true) {
      node.setAttribute(key, "");
    } else {
      node.setAttribute(key, String(val));
    }
  }
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined || child === false) continue;
    if (typeof child === "string" || typeof child === "number") {
      node.appendChild(document.createTextNode(String(child)));
    } else {
      node.appendChild(child);
    }
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

export function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Build highlighted text fragments safely using Text nodes and <mark>. */
export function appendHighlightedText(parent, text, terms, markClass = "") {
  const cleanTerms = (terms || []).filter((t) => t && t.length >= 2);
  if (!cleanTerms.length) {
    parent.appendChild(document.createTextNode(text));
    return;
  }
  const pattern = new RegExp(`(${cleanTerms.map(escapeRegex).join("|")})`, "gi");
  let lastIdx = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > lastIdx) {
      parent.appendChild(document.createTextNode(text.slice(lastIdx, start)));
    }
    parent.appendChild(el("mark", { className: markClass || undefined, text: match[0] }));
    lastIdx = start + match[0].length;
  }
  if (lastIdx < text.length) {
    parent.appendChild(document.createTextNode(text.slice(lastIdx)));
  }
}

/** Fallback light-dismiss for browsers without native <dialog closedby="any">. */
export function setupDialogLightDismiss() {
  for (const dialog of document.querySelectorAll("dialog")) {
    dialog.addEventListener("close", () => {
      // Prevent stale returnValue leaks across re-opens.
      setTimeout(() => {
        dialog.returnValue = "";
      }, 0);
    });
  }
  if ("closedBy" in HTMLDialogElement.prototype) return;

  const isOutside = (e, dialog) => {
    const r = dialog.getBoundingClientRect();
    return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  };
  for (const dialog of document.querySelectorAll('dialog[closedby="any"]')) {
    let pressedOutside = false;
    dialog.addEventListener("pointerdown", (e) => {
      pressedOutside = isOutside(e, dialog);
    });
    dialog.addEventListener("pointerup", (e) => {
      if (pressedOutside && isOutside(e, dialog)) {
        dialog.close();
      }
    });
  }
}
