/** Cascading Subject -> Source/Type -> Searchable Multi-Select Topic/Year selector component. */

import { clear, el, pluralUk } from "./dom.js?v=2.8.0";

const BOOKLET_TAG_RE = /^Буклет\s+(\d{4})$/;

function getTagCount(subj, tagName) {
  const found = (subj?.source_tags || []).find((st) => st.tag === tagName);
  return found ? Number(found.count) : 0;
}

function getBookletYearTags(subjects, subjectId) {
  const list = [];
  const targetSubjects = subjectId != null ? subjects.filter((s) => s.id === subjectId) : subjects;
  for (const subj of targetSubjects) {
    for (const st of subj.source_tags || []) {
      const m = st.tag.match(BOOKLET_TAG_RE);
      if (m) {
        list.push({
          year: Number(m[1]),
          tag: st.tag,
          count: Number(st.count),
          subject: subj,
        });
      }
    }
  }
  list.sort((a, b) => b.year - a.year || a.subject.id - b.subject.id);
  return list;
}

function getThematicModules(subj) {
  if (!subj) return [];
  if (subj.slug === "microbiology") {
    return subj.modules.filter((m) => m.module_no >= 1 && m.module_no <= 3);
  }
  return subj.modules.filter((m) => m.module_no === 1);
}

export function getSourceKindOptions(subjects, subjectId) {
  const targetSubjects = subjectId != null ? subjects.filter((s) => s.id === subjectId) : subjects;
  const totalQ = targetSubjects.reduce((acc, s) => acc + Number(s.total_questions || 0), 0);
  const options = [{ value: "all", label: "Усі джерела", count: totalQ }];

  if (targetSubjects.length === 1) {
    const subj = targetSubjects[0];
    if (subj.slug === "microbiology") {
      const themCnt = getThematicModules(subj).reduce((a, m) => a + m.question_count, 0);
      if (themCnt > 0) options.push({ value: "thematic", label: "Тематична база (Модулі 1–3)", count: themCnt });
      const kkrCnt = getTagCount(subj, "ККР");
      if (kkrCnt > 0) options.push({ value: "kkr", label: "🎯 Тільки ККР", count: kkrCnt });
      const m5 = subj.modules.find((m) => m.module_no === 5);
      if (m5 && m5.question_count > 0) {
        options.push({ value: "m5", label: "Збірник тестів (Модуль 5)", count: m5.question_count });
      }
      return options;
    }
    if (subj.slug === "pharmacology") {
      const themCnt = getTagCount(subj, "Тематична база");
      if (themCnt > 0) options.push({ value: "thematic", label: "Тематична база (по темах)", count: themCnt });
      const bookCnt = getTagCount(subj, "Буклети КРОК");
      if (bookCnt > 0) options.push({ value: "booklets", label: "Буклети КРОК (по роках)", count: bookCnt });
      return options;
    }
    if (subj.slug === "pathomorphology") {
      const themCnt = getTagCount(subj, "Тематична база");
      if (themCnt > 0) options.push({ value: "thematic", label: "Тематична база (по темах)", count: themCnt });
      const examCnt = getTagCount(subj, "Екзаменаційний банк");
      if (examCnt > 0) options.push({ value: "exam_bank", label: "Екзаменаційний банк", count: examCnt });
      return options;
    }
    for (const st of subj.source_tags || []) {
      options.push({ value: `tag:${st.tag}`, label: st.tag, count: st.count });
    }
    return options;
  }

  // All subjects combined
  const themTotal = targetSubjects.reduce((acc, s) => {
    if (s.slug === "microbiology") {
      return acc + getThematicModules(s).reduce((a, m) => a + m.question_count, 0);
    }
    return acc + getTagCount(s, "Тематична база");
  }, 0);
  if (themTotal > 0) options.push({ value: "thematic", label: "Тематична база", count: themTotal });

  const bookletsTotal = targetSubjects.reduce((acc, s) => acc + getTagCount(s, "Буклети КРОК"), 0);
  if (bookletsTotal > 0) options.push({ value: "booklets", label: "Буклети КРОК (по роках)", count: bookletsTotal });

  const kkrTotal = targetSubjects.reduce((acc, s) => acc + getTagCount(s, "ККР"), 0);
  if (kkrTotal > 0) options.push({ value: "kkr", label: "🎯 Тільки ККР", count: kkrTotal });

  const examBankTotal = targetSubjects.reduce((acc, s) => acc + getTagCount(s, "Екзаменаційний банк"), 0);
  if (examBankTotal > 0) options.push({ value: "exam_bank", label: "Екзаменаційний банк", count: examBankTotal });

  return options;
}

export function getTopicOrYearOptions(subjects, subjectId, sourceKind) {
  const targetSubjects = subjectId != null ? subjects.filter((s) => s.id === subjectId) : subjects;
  const multiSubject = targetSubjects.length > 1;
  const srcOpts = getSourceKindOptions(subjects, subjectId);
  const currentSrc = srcOpts.find((o) => o.value === sourceKind) || srcOpts[0];

  const allLabel =
    sourceKind === "booklets"
      ? "Усі роки буклетів"
      : sourceKind === "all"
        ? "Усі теми та роки"
        : "Усі теми джерела";

  const items = [
    {
      key: "all",
      label: allLabel,
      group: "",
      count: currentSrc ? currentSrc.count : 0,
      scope: buildDefaultScopeForSource(targetSubjects, sourceKind),
    },
  ];

  // Booklets by year (2023 -> 2005)
  if (sourceKind === "booklets") {
    const years = getBookletYearTags(subjects, subjectId);
    for (const y of years) {
      const prefix = multiSubject ? `${y.subject.icon} ` : "";
      items.push({
        key: `tag:${y.tag}`,
        label: `${prefix}Буклет КРОК-1 · ${y.year}`,
        group: "Буклети КРОК",
        count: y.count,
        scope: {
          subjectId: y.subject.id,
          subjectTitle: y.subject.title_uk,
          moduleNo: null,
          topicId: null,
          sourceTag: y.tag,
          title: `${y.subject.title_uk} · ${y.tag}`,
        },
      });
    }
    return items;
  }

  // KKR filter (Microbiology modules + KKR source tag)
  if (sourceKind === "kkr") {
    for (const subj of targetSubjects) {
      if (getTagCount(subj, "ККР") <= 0) continue;
      for (const mod of subj.modules) {
        if (mod.module_no === 5) continue;
        for (const t of mod.topics) {
          items.push({
            key: `t:${t.id}`,
            label: multiSubject ? `${subj.icon} ${t.title_uk}` : t.title_uk,
            group: mod.title_uk,
            count: t.question_count,
            scope: {
              subjectId: subj.id,
              subjectTitle: subj.title_uk,
              moduleNo: mod.module_no,
              topicId: t.id,
              sourceTag: "ККР",
              title: `${t.title_uk} · ККР`,
            },
          });
        }
      }
    }
    return items;
  }

  // Module 5 (Microbiology collection)
  if (sourceKind === "m5") {
    for (const subj of targetSubjects) {
      const m5 = subj.modules.find((m) => m.module_no === 5);
      if (!m5) continue;
      for (const t of m5.topics) {
        items.push({
          key: `t:${t.id}`,
          label: t.title_uk,
          group: m5.title_uk,
          count: t.question_count,
          scope: {
            subjectId: subj.id,
            subjectTitle: subj.title_uk,
            moduleNo: 5,
            topicId: t.id,
            sourceTag: null,
            title: t.title_uk,
          },
        });
      }
    }
    return items;
  }

  // Exam bank (Pathomorphology)
  if (sourceKind === "exam_bank") {
    for (const subj of targetSubjects) {
      if (getTagCount(subj, "Екзаменаційний банк") <= 0) continue;
      for (const mod of subj.modules) {
        for (const t of mod.topics) {
          items.push({
            key: `t:${t.id}`,
            label: multiSubject ? `${subj.icon} ${t.title_uk}` : t.title_uk,
            group: mod.title_uk,
            count: t.question_count,
            scope: {
              subjectId: subj.id,
              subjectTitle: subj.title_uk,
              moduleNo: mod.module_no,
              topicId: t.id,
              sourceTag: "Екзаменаційний банк",
              title: t.title_uk,
            },
          });
        }
      }
    }
    return items;
  }

  // Thematic or All
  if (sourceKind === "all") {
    // Include booklet years at top when viewing Pharmacology or All
    const years = getBookletYearTags(subjects, subjectId);
    for (const y of years) {
      const prefix = multiSubject ? `${y.subject.icon} ` : "";
      items.push({
        key: `tag:${y.tag}`,
        label: `${prefix}Буклет КРОК-1 · ${y.year}`,
        group: "Буклети КРОК",
        count: y.count,
        scope: {
          subjectId: y.subject.id,
          subjectTitle: y.subject.title_uk,
          moduleNo: null,
          topicId: null,
          sourceTag: y.tag,
          title: `${y.subject.title_uk} · ${y.tag}`,
        },
      });
    }
  }

  for (const subj of targetSubjects) {
    const mods = sourceKind === "thematic" ? getThematicModules(subj) : subj.modules;
    for (const mod of mods) {
      // For Pharmacology "all", skip module 2 raw booklet topics since full year tags are listed above
      if (subj.slug === "pharmacology" && mod.module_no === 2) continue;
      for (const t of mod.topics) {
        items.push({
          key: `t:${t.id}`,
          label: multiSubject ? `${subj.icon} ${t.title_uk}` : t.title_uk,
          group: multiSubject ? `${subj.title_uk} · ${mod.title_uk}` : mod.title_uk,
          count: t.question_count,
          scope: {
            subjectId: subj.id,
            subjectTitle: subj.title_uk,
            moduleNo: mod.module_no,
            topicId: t.id,
            sourceTag: sourceKind === "thematic" && subj.slug !== "microbiology" ? "Тематична база" : null,
            title: t.title_uk,
          },
        });
      }
    }
  }

  return items;
}

function buildDefaultScopeForSource(targetSubjects, sourceKind) {
  const single = targetSubjects.length === 1 ? targetSubjects[0] : null;
  const subjectId = single ? single.id : null;
  const subjectTitle = single ? single.title_uk : "Усі предмети";

  if (sourceKind === "booklets") {
    return {
      subjectId,
      subjectTitle,
      moduleNo: null,
      topicId: null,
      sourceTag: "Буклети КРОК",
      title: single ? `${single.title_uk} · Буклети КРОК` : "Буклети КРОК (по роках)",
    };
  }
  if (sourceKind === "kkr") {
    return {
      subjectId,
      subjectTitle,
      moduleNo: null,
      topicId: null,
      sourceTag: "ККР",
      title: single ? `${single.title_uk} · ККР` : "Тільки ККР",
    };
  }
  if (sourceKind === "m5") {
    return {
      subjectId,
      subjectTitle,
      moduleNo: 5,
      topicId: null,
      sourceTag: null,
      title: "Збірник тестів з мікробіології (М5)",
    };
  }
  if (sourceKind === "exam_bank") {
    return {
      subjectId,
      subjectTitle,
      moduleNo: null,
      topicId: null,
      sourceTag: "Екзаменаційний банк",
      title: single ? `${single.title_uk} · Екзаменаційний банк` : "Екзаменаційний банк",
    };
  }
  if (sourceKind === "thematic") {
    if (single && single.slug === "microbiology") {
      return {
        subjectId,
        subjectTitle,
        moduleNo: null,
        topicId: null,
        sourceTag: null,
        title: `${single.title_uk} · Тематична база`,
      };
    }
    return {
      subjectId,
      subjectTitle,
      moduleNo: null,
      topicId: null,
      sourceTag: "Тематична база",
      title: single ? `${single.title_uk} · Тематична база` : "Тематична база КРОК-1",
    };
  }
  return {
    subjectId,
    subjectTitle,
    moduleNo: null,
    topicId: null,
    sourceTag: null,
    title: single ? single.title_uk : "Усі предмети КРОК-1",
  };
}

function getSelectedKeys(cascade, topicOpts) {
  const validKeys = new Set(topicOpts.filter((o) => o.key !== "all").map((o) => o.key));
  const rawList = Array.isArray(cascade.itemKeys) && cascade.itemKeys.length
    ? cascade.itemKeys
    : cascade.itemKey && cascade.itemKey !== "all" && cascade.itemKey !== "multi"
      ? [cascade.itemKey]
      : [];
  const seen = new Set();
  const clean = [];
  for (const k of rawList) {
    if (validKeys.has(k) && !seen.has(k)) {
      seen.add(k);
      clean.push(k);
    }
  }
  return clean;
}

function syncItemKeyFromKeys(cascade) {
  const keys = Array.isArray(cascade.itemKeys) ? cascade.itemKeys : [];
  cascade.itemKey = keys.length === 0 ? "all" : keys.length === 1 ? keys[0] : "multi";
}

function formatMultiTitle(matchedItems, sourceKind) {
  const n = matchedItems.length;
  const allBooklets = sourceKind === "booklets" || matchedItems.every((m) => m.scope.topicId == null && m.scope.sourceTag);
  const allTopics = matchedItems.every((m) => m.scope.topicId != null);
  if (allBooklets) {
    return `Обрано ${n} ${pluralUk(n, ["буклет", "буклети", "буклетів"])}`;
  }
  if (allTopics) {
    return `Обрано ${n} ${pluralUk(n, ["тему", "теми", "тем"])}`;
  }
  return `Обрано ${n} ${pluralUk(n, ["позицію", "позиції", "позицій"])}`;
}

export function resolveCascadeScope(subjects, cascade) {
  const srcOpts = getSourceKindOptions(subjects, cascade.subjectId);
  const validSource = srcOpts.some((o) => o.value === cascade.sourceKind) ? cascade.sourceKind : "all";
  const itemOpts = getTopicOrYearOptions(subjects, cascade.subjectId, validSource);
  const selectedKeys = getSelectedKeys(cascade, itemOpts);
  cascade.itemKeys = selectedKeys;
  syncItemKeyFromKeys(cascade);

  if (selectedKeys.length === 0) {
    const allOpt = itemOpts[0];
    return {
      ...(allOpt?.scope || {
        subjectId: cascade.subjectId,
        subjectTitle: "Усі предмети",
        moduleNo: null,
        topicId: null,
        sourceTag: null,
        title: "Усі предмети КРОК-1",
      }),
      topicIds: null,
      sourceTags: null,
      questionCount: allOpt ? allOpt.count : 0,
      sourceKind: validSource,
      itemKey: "all",
      itemKeys: [],
    };
  }

  if (selectedKeys.length === 1) {
    const matched = itemOpts.find((o) => o.key === selectedKeys[0]) || itemOpts[0];
    return {
      ...matched.scope,
      topicIds: null,
      sourceTags: null,
      questionCount: matched.count,
      sourceKind: validSource,
      itemKey: matched.key,
      itemKeys: [matched.key],
    };
  }

  const keySet = new Set(selectedKeys);
  const matchedItems = itemOpts.filter((o) => keySet.has(o.key));
  const topicIds = matchedItems.map((m) => m.scope.topicId).filter((id) => id != null);
  const sourceTags = matchedItems
    .filter((m) => m.scope.topicId == null && m.scope.sourceTag)
    .map((m) => m.scope.sourceTag);

  const uniqSubjs = new Set(matchedItems.map((m) => m.scope.subjectId).filter((v) => v != null));
  const commonSubjId = uniqSubjs.size === 1 ? [...uniqSubjs][0] : (cascade.subjectId ?? null);
  const commonSubj = commonSubjId != null ? subjects.find((s) => s.id === commonSubjId) : null;

  const uniqMods = new Set(matchedItems.map((m) => m.scope.moduleNo));
  const commonModuleNo = uniqMods.size === 1 ? [...uniqMods][0] : null;

  const rawSourceTags = matchedItems.map((m) => (m.scope.topicId != null ? m.scope.sourceTag : null));
  const commonSourceTag =
    sourceTags.length === 0 && new Set(rawSourceTags).size === 1 ? rawSourceTags[0] : null;

  const totalCount = matchedItems.reduce((acc, m) => acc + Number(m.count || 0), 0);

  return {
    subjectId: commonSubjId,
    subjectTitle: commonSubj ? commonSubj.title_uk : "Усі предмети",
    moduleNo: commonModuleNo,
    topicId: null,
    topicIds: topicIds.length ? topicIds : null,
    sourceTag: commonSourceTag,
    sourceTags: sourceTags.length ? sourceTags : null,
    title: formatMultiTitle(matchedItems, validSource),
    questionCount: totalCount,
    sourceKind: validSource,
    itemKey: "multi",
    itemKeys: matchedItems.map((m) => m.key),
  };
}

export function syncCascadeFromSelection(subjects, sel, cascade) {
  cascade.subjectId = sel.subjectId ?? null;
  const keys = [];
  if (Array.isArray(sel.topicIds) && sel.topicIds.length) {
    for (const tid of sel.topicIds) {
      if (tid != null) keys.push(`t:${tid}`);
    }
  } else if (sel.topicId != null) {
    keys.push(`t:${sel.topicId}`);
  }
  if (Array.isArray(sel.sourceTags) && sel.sourceTags.length) {
    for (const st of sel.sourceTags) {
      if (st) keys.push(`tag:${st}`);
    }
  } else if (sel.sourceTag && BOOKLET_TAG_RE.test(sel.sourceTag)) {
    keys.push(`tag:${sel.sourceTag}`);
  }

  if (sel.sourceKind && sel.sourceKind !== "all") {
    cascade.sourceKind = sel.sourceKind;
  } else if (sel.sourceTag && BOOKLET_TAG_RE.test(sel.sourceTag)) {
    cascade.sourceKind = "booklets";
  } else if (sel.sourceTag === "Буклети КРОК" || (Array.isArray(sel.sourceTags) && sel.sourceTags.length && !sel.topicIds?.length)) {
    cascade.sourceKind = "booklets";
  } else if (sel.sourceTag === "ККР") {
    cascade.sourceKind = "kkr";
  } else if (sel.sourceTag === "Екзаменаційний банк") {
    cascade.sourceKind = "exam_bank";
  } else if (sel.sourceTag === "Тематична база") {
    cascade.sourceKind = "thematic";
  } else if (sel.moduleNo === 5) {
    cascade.sourceKind = "m5";
  } else {
    cascade.sourceKind = "all";
  }

  cascade.itemKeys = keys;
  syncItemKeyFromKeys(cascade);
}

/**
 * Render the 3-level cascading selector:
 * 1. Subject (<select class="brand-select">)
 * 2. Source / Type (<select class="brand-select">)
 * 3. Topic / Year (Searchable Multi-Select Popover Combobox with checkboxes)
 */
export function createCascadeSelector({ idPrefix = "cascade", subjects, cascade, onChange }) {
  const totalAll = subjects.reduce((a, s) => a + Number(s.total_questions || 0), 0);
  const srcOpts = getSourceKindOptions(subjects, cascade.subjectId);
  if (!srcOpts.some((o) => o.value === cascade.sourceKind)) {
    cascade.sourceKind = "all";
  }
  const topicOpts = getTopicOrYearOptions(subjects, cascade.subjectId, cascade.sourceKind);
  cascade.itemKeys = getSelectedKeys(cascade, topicOpts);
  syncItemKeyFromKeys(cascade);

  const initialResolved = resolveCascadeScope(subjects, cascade);
  const grid = el("div", { className: "cascade-grid" });

  // 1. Subject dropdown
  const subjId = `${idPrefix}-subject-select`;
  const subjSelect = el("select", {
    id: subjId,
    name: "subject",
    className: "brand-select",
    onChange: (e) => {
      const val = e.target.value;
      cascade.subjectId = val ? Number(val) : null;
      cascade.sourceKind = "all";
      cascade.itemKey = "all";
      cascade.itemKeys = [];
      onChange(resolveCascadeScope(subjects, cascade));
    },
  });
  subjSelect.appendChild(
    el("option", {
      value: "",
      text: `📚 Усі предмети (${totalAll})`,
      selected: cascade.subjectId === null,
    })
  );
  for (const s of subjects) {
    subjSelect.appendChild(
      el("option", {
        value: String(s.id),
        text: `${s.icon} ${s.title_uk} (${s.total_questions})`,
        selected: cascade.subjectId === s.id,
      })
    );
  }
  grid.appendChild(
    el("div", { className: "cascade-field" }, [
      el("label", { for: subjId, className: "cascade-label", text: "1. Предмет" }),
      subjSelect,
    ])
  );

  // 2. Source / Type dropdown
  const srcId = `${idPrefix}-source-select`;
  const srcSelect = el("select", {
    id: srcId,
    name: "source_kind",
    className: "brand-select",
    onChange: (e) => {
      cascade.sourceKind = e.target.value || "all";
      cascade.itemKey = "all";
      cascade.itemKeys = [];
      onChange(resolveCascadeScope(subjects, cascade));
    },
  });
  for (const opt of srcOpts) {
    srcSelect.appendChild(
      el("option", {
        value: opt.value,
        text: `${opt.label} (${opt.count})`,
        selected: cascade.sourceKind === opt.value,
      })
    );
  }
  grid.appendChild(
    el("div", { className: "cascade-field" }, [
      el("label", { for: srcId, className: "cascade-label", text: "2. Джерело / Тип" }),
      srcSelect,
    ])
  );

  // 3. Topic / Year searchable multi-select combobox popover
  const popoverId = `${idPrefix}-topic-popover`;
  const triggerId = `${idPrefix}-topic-trigger`;
  const searchId = `${idPrefix}-topic-search`;

  const triggerTextEl = el("span", { className: "combo-trigger-text", text: initialResolved.title });
  const triggerCountEl = el("span", { className: "combo-option-count", text: String(initialResolved.questionCount ?? 0) });
  const triggerBtn = el(
    "button",
    {
      id: triggerId,
      type: "button",
      className: `combo-trigger ${cascade.itemKeys.length ? "has-selection" : ""}`,
      popovertarget: popoverId,
    },
    [
      triggerTextEl,
      el("span", { className: "combo-trigger-meta" }, [
        triggerCountEl,
        el("span", { "aria-hidden": "true", className: "muted", text: "▾" }),
      ]),
    ]
  );

  const popover = el("div", {
    id: popoverId,
    popover: "auto",
    className: "combo-popover",
  });

  const listEl = el("div", {
    className: "combo-list",
    role: "group",
    "aria-label": "Список тем і років з вибором галочками",
  });
  const clearBtn = el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "Скинути" });
  const selectFilteredBtn = el("button", { type: "button", className: "btn btn-secondary btn-sm hidden", hidden: true });
  const doneBtn = el("button", { type: "button", className: "btn btn-primary btn-sm" });

  let filterText = "";
  let highlightedIdx = 0;
  let visibleItems = topicOpts;
  let dirty = false;

  const updateTriggerAndFooter = () => {
    const resolved = resolveCascadeScope(subjects, cascade);
    const selectedCount = cascade.itemKeys.length;
    triggerTextEl.textContent = selectedCount === 0 ? topicOpts[0]?.label || "Усі теми" : resolved.title;
    triggerCountEl.textContent = String(resolved.questionCount ?? 0);
    triggerBtn.classList.toggle("has-selection", selectedCount > 0);
    clearBtn.disabled = selectedCount === 0;
    doneBtn.textContent = `Готово · ${resolved.questionCount} пит.`;

    const selectableVisible = visibleItems.filter((item) => item.key !== "all");
    if (filterText.trim() && selectableVisible.length >= 2) {
      const selectedSet = new Set(cascade.itemKeys);
      const allVisibleSelected = selectableVisible.every((item) => selectedSet.has(item.key));
      selectFilteredBtn.hidden = false;
      selectFilteredBtn.classList.remove("hidden");
      selectFilteredBtn.textContent = allVisibleSelected
        ? `Зняти знайдені (${selectableVisible.length})`
        : `Обрати знайдені (${selectableVisible.length})`;
    } else {
      selectFilteredBtn.hidden = true;
      selectFilteredBtn.classList.add("hidden");
    }
  };

  const syncListSelectionState = () => {
    const selectedSet = new Set(cascade.itemKeys);
    for (const row of listEl.querySelectorAll(".combo-option")) {
      const key = row.dataset.key;
      const isAll = key === "all";
      const isChecked = isAll ? selectedSet.size === 0 : selectedSet.has(key);
      const isIndeterminate = isAll && selectedSet.size > 0;
      const cb = row.querySelector(".combo-checkbox");
      if (cb) {
        cb.checked = isChecked;
        cb.indeterminate = isIndeterminate;
      }
      row.classList.toggle("is-selected", isChecked);
    }
  };

  const toggleItemKey = (key) => {
    if (key === "all") {
      cascade.itemKeys = [];
      cascade.itemKey = "all";
    } else {
      const idx = cascade.itemKeys.indexOf(key);
      if (idx >= 0) {
        cascade.itemKeys = cascade.itemKeys.filter((k) => k !== key);
      } else {
        cascade.itemKeys = [...cascade.itemKeys, key];
      }
      syncItemKeyFromKeys(cascade);
    }
    dirty = true;
    syncListSelectionState();
    updateTriggerAndFooter();
  };

  const renderList = () => {
    clear(listEl);
    const q = filterText.trim().toLowerCase();
    visibleItems = q
      ? topicOpts.filter(
          (item) =>
            item.label.toLowerCase().includes(q) ||
            (item.group && item.group.toLowerCase().includes(q))
        )
      : topicOpts;

    if (!visibleItems.length) {
      listEl.appendChild(el("div", { className: "combo-empty", text: "Нічого не знайдено за цим запитом." }));
      return;
    }
    if (highlightedIdx >= visibleItems.length) highlightedIdx = 0;

    const selectedSet = new Set(cascade.itemKeys);
    visibleItems.forEach((item, idx) => {
      const isAll = item.key === "all";
      const isChecked = isAll ? selectedSet.size === 0 : selectedSet.has(item.key);
      const isIndeterminate = isAll && selectedSet.size > 0;

      const checkbox = el("input", {
        type: "checkbox",
        className: "combo-checkbox",
        onChange: () => toggleItemKey(item.key),
      });
      checkbox.checked = isChecked;
      checkbox.indeterminate = isIndeterminate;

      const row = el(
        "label",
        {
          dataset: { key: item.key },
          className: `combo-option ${isAll ? "combo-option-all" : ""} ${isChecked ? "is-selected" : ""} ${idx === highlightedIdx ? "is-highlighted" : ""}`,
        },
        [
          checkbox,
          el("span", { className: "combo-option-label", text: item.label }),
          el("span", { className: "combo-option-count", text: String(item.count) }),
        ]
      );
      listEl.appendChild(row);
    });
  };

  clearBtn.addEventListener("click", () => {
    if (!cascade.itemKeys.length) return;
    cascade.itemKeys = [];
    cascade.itemKey = "all";
    dirty = true;
    syncListSelectionState();
    updateTriggerAndFooter();
  });

  selectFilteredBtn.addEventListener("click", () => {
    const selectableVisible = visibleItems.filter((item) => item.key !== "all");
    if (!selectableVisible.length) return;
    const selectedSet = new Set(cascade.itemKeys);
    const allVisibleSelected = selectableVisible.every((item) => selectedSet.has(item.key));
    if (allVisibleSelected) {
      const drop = new Set(selectableVisible.map((item) => item.key));
      cascade.itemKeys = cascade.itemKeys.filter((k) => !drop.has(k));
    } else {
      for (const item of selectableVisible) {
        if (!selectedSet.has(item.key)) {
          selectedSet.add(item.key);
        }
      }
      cascade.itemKeys = [...selectedSet];
    }
    syncItemKeyFromKeys(cascade);
    dirty = true;
    syncListSelectionState();
    updateTriggerAndFooter();
  });

  doneBtn.addEventListener("click", () => {
    try {
      popover.hidePopover();
    } catch {
      popover.removeAttribute("open");
    }
  });

  const searchInput = el("input", {
    id: searchId,
    type: "search",
    className: "combo-search-input",
    placeholder:
      cascade.sourceKind === "booklets"
        ? "Пошук року буклету (напр. 2023)…"
        : `Пошук серед ${topicOpts.length - 1} ${pluralUk(topicOpts.length - 1, ["теми", "тем", "тем"])}…`,
    autocomplete: "off",
    autocorrect: "off",
    autocapitalize: "none",
    spellcheck: "false",
    onInput: (e) => {
      filterText = e.target.value;
      highlightedIdx = 0;
      renderList();
      updateTriggerAndFooter();
    },
    onKeydown: (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (visibleItems.length) {
          highlightedIdx = (highlightedIdx + 1) % visibleItems.length;
          renderList();
          listEl.children[highlightedIdx]?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (visibleItems.length) {
          highlightedIdx = (highlightedIdx - 1 + visibleItems.length) % visibleItems.length;
          renderList();
          listEl.children[highlightedIdx]?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        const chosen = visibleItems[highlightedIdx];
        if (chosen) {
          toggleItemKey(chosen.key);
        }
      }
    },
  });

  popover.addEventListener("toggle", (e) => {
    if (e.newState === "open") {
      dirty = false;
      filterText = "";
      searchInput.value = "";
      const firstSelected = cascade.itemKeys[0];
      highlightedIdx = firstSelected
        ? Math.max(0, topicOpts.findIndex((o) => o.key === firstSelected))
        : 0;
      renderList();
      updateTriggerAndFooter();
      requestAnimationFrame(() => {
        searchInput.focus({ preventScroll: true });
      });
    } else if (e.newState === "closed" && dirty) {
      dirty = false;
      onChange(resolveCascadeScope(subjects, cascade));
    }
  });

  popover.appendChild(
    el("div", { className: "combo-search-bar" }, [
      el("span", { "aria-hidden": "true", text: "🔍" }),
      searchInput,
    ])
  );
  popover.appendChild(listEl);
  popover.appendChild(
    el("div", { className: "combo-footer" }, [
      el("div", { className: "combo-footer-left" }, [clearBtn, selectFilteredBtn]),
      doneBtn,
    ])
  );
  renderList();
  updateTriggerAndFooter();

  const fieldLabel = cascade.sourceKind === "booklets" ? "3. Рік буклету" : "3. Тема / Рік (можна кілька)";
  grid.appendChild(
    el("div", { className: "cascade-field cascade-field-full" }, [
      el("label", { for: triggerId, className: "cascade-label", text: fieldLabel }),
      triggerBtn,
      popover,
    ])
  );

  return {
    element: grid,
    resolved: initialResolved,
  };
}
