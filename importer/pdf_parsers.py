"""Dedicated PDF parsers for Pharmacology (3-column) and Pathomorphology (1-column) KROK-1 banks."""

from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path

import pdfplumber

from app.db import db_session, init_db
from importer.krok_importer import (
    ParsedQuestion,
    clean_display_text,
    compute_norm_hash,
    normalize_for_hash,
)

# ---------------------------------------------------------------------------
# Shared text cleanup helpers
# ---------------------------------------------------------------------------

_CYR_TO_LAT_OPTION = {
    "А": "A",
    "а": "A",
    "В": "B",
    "в": "B",
    "С": "C",
    "с": "C",
    "Е": "E",
    "е": "E",
}

_SKIP_PHARM_HEADERS = {
    "МЕДИЧНИЙ ФАКУЛЬТЕТ",
    "БАЗА КРОК-1",
    "КРОК-1 Буклети (по роках)",
    "КРОК-1 Буклети",
}

_YEAR_HEADER_RE = re.compile(r"^((?:19|20)\d{2})(?:\s*\(([^)]+)\))?$")
_Q_NUM_RE = re.compile(r"^(\d{1,3})\.\s+(.+)$")
# Matches: "A. *Text", "A. A.* Text", "А. *Text", "F. Text", "A.*Text"
_OPT_LETTER_RE = re.compile(
    r"^([A-Ja-jАаВвСсЕе])\.\s*(?:[A-Ja-jАаВвСсЕе]\.\s*)?(\*?)\s*(.+)$"
)
_OPT_LETTER_NO_SPACE_STAR_RE = re.compile(
    r"^([A-Ja-jАаВвСсЕе])\.\s*(\*+)(.+)$"
)
# Matches Russian-only letters/patterns for Pathomorphology exam bank filtering
_RU_SPECIFIC_LETTERS_RE = re.compile(r"[ыэъёЫЭЪЁ]")
_UK_SPECIFIC_LETTERS_RE = re.compile(r"[іїєґІЇЄҐ]")
_RU_STOPWORDS_RE = re.compile(
    r"\b(?:больного|больной|больному|мужчины|женщины|ребенка|обнаружены|обнаружено|"
    r"поставлен|диагноз|назовите|какой|какая|какое|какие|вскрытии|микроскопически|"
    r"препарате|ткани|клеток|железы|печени|почек|легких|сердца|крови|слизистой|"
    r"характерно|является|выявлены|выявлено|наблюдается|развился|развилась)\b",
    re.IGNORECASE,
)

# Known corrupted answer keys in source PDFs (verified medically)
_KNOWN_KEY_FIXES: list[tuple[str, str]] = [
    # 2023 #17: Herpes simplex of lips -> Acyclovir (PDF erroneously has *Амікацин)
    ("простий герпес слизової", "ац"),
]


def _normalize_option_letter(ch: str) -> str:
    return _CYR_TO_LAT_OPTION.get(ch, ch.upper())


def _format_caps_topic_title(raw: str) -> str:
    """Convert ALL-CAPS Ukrainian topic header into clean Title/Sentence case preserving acronyms."""
    text = clean_display_text(raw)
    text = re.sub(r",\s*$", "", text).strip()
    if not text:
        return text
    # Preserve known acronyms
    acronyms = {"НПЗЗ", "ШКТ", "ЦНС", "СРС", "АТ", "ВІЛ", "КРОК", "КРОК-1", "М", "Н"}
    parts = re.split(r"(\s+|(?<=[(\-–—/])|(?=[)\-–—/.,]))", text)
    out: list[str] = []
    first_word_done = False
    for p in parts:
        if not p or not re.search(r"[А-ЯІЇЄҐA-Z]", p):
            out.append(p)
            continue
        clean_p = p.strip()
        if clean_p in acronyms:
            out.append(clean_p)
            first_word_done = True
            continue
        if not first_word_done:
            out.append(p[0].upper() + p[1:].lower())
            first_word_done = True
        else:
            out.append(p.lower())
    res = "".join(out)
    # Restore M- / H- prefixes like "М-холіноблокатори"
    res = re.sub(r"\b([мн])-([а-яіїєґ])", lambda m: f"{m.group(1).upper()}-{m.group(2)}", res)
    return re.sub(r"\s+", " ", res).strip()


def clean_latex_artifacts(text: str) -> str:
    """Replace raw LaTeX snippets from Pathomorphology PDF with clean Unicode text."""
    s = text
    # Common patterns like $B_{12}$, $t^o$, $10^9$, $\alpha$, $O_2$, $CO_2$, $H_2O$
    s = re.sub(r"\$\\alpha\$|\\alpha\b", "α", s)
    s = re.sub(r"\$\\beta\$|\\beta\b", "β", s)
    s = re.sub(r"\$\\gamma\$|\\gamma\b", "γ", s)
    s = re.sub(r"\$\\delta\$|\\delta\b", "δ", s)
    s = re.sub(r"\$\\mu\$|\\mu\b", "μ", s)
    s = re.sub(r"\$\\pm\$|\\pm\b", "±", s)
    s = re.sub(r"\$\\times\$|\\times\b", "×", s)
    s = re.sub(r"\$\\geq\$|\\geq\b|\\ge\b", "≥", s)
    s = re.sub(r"\$\\leq\$|\\leq\b|\\le\b", "≤", s)
    s = re.sub(r"\$t\^\{?[o0°]\}?\$", "t°", s)
    s = re.sub(r"\^\{\\circ\}|\^\\circ", "°", s)
    # Unwrap $...$ math spans and clean _{...} / ^{...}
    def _unwrap_math(m: re.Match[str]) -> str:
        inner = m.group(1)
        inner = re.sub(r"_\{([^}]+)\}", r"\1", inner)
        inner = re.sub(r"\^\{([^}]+)\}", r"^\1", inner)
        inner = re.sub(r"_([A-Za-z0-9]+)", r"\1", inner)
        inner = inner.replace("\\,", " ").replace("\\;", " ").replace("\\ ", " ")
        inner = inner.replace("{", "").replace("}", "").replace("\\", "")
        return inner.strip()

    s = re.sub(r"\$([^$]{1,80})\$", _unwrap_math, s)
    s = re.sub(r"\^[oOоО0]", "°", s)
    # Remove stray backslashes or braces left over
    s = s.replace("\\%", "%").replace("^", "")
    s = re.sub(r"[\\{}]", "", s)
    s = s.replace("$", "")
    return clean_display_text(s)


def is_russian_text(text: str) -> bool:
    """Detect Russian-language questions (used to filter Russian duplicates in Pathomorphology Part 2)."""
    if _RU_SPECIFIC_LETTERS_RE.search(text):
        return True
    if _UK_SPECIFIC_LETTERS_RE.search(text):
        return False
    ru_hits = len(_RU_STOPWORDS_RE.findall(text))
    return ru_hits >= 2


# ---------------------------------------------------------------------------
# Pharmacology 3-Column Parser (Booklets 2005-2023 & Thematic Base)
# ---------------------------------------------------------------------------

def _extract_3col_lines(pdf_path: Path) -> list[tuple[int, int, str]]:
    """Extract lines strictly column-by-column (left, middle, right) from 3-column landscape PDF."""
    lines: list[tuple[int, int, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            w, h = page.width, page.height
            # Empirically verified gutters for 841.9pt landscape pages: x=288 and x=556
            c1 = min(288.0, w / 3.0 + 7.0)
            c2 = min(556.0, 2.0 * w / 3.0 - 5.0)
            for cidx, bbox in enumerate([(0, 0, c1, h), (c1, 0, c2, h), (c2, 0, w, h)]):
                txt = page.crop(bbox).extract_text(x_tolerance=2, y_tolerance=3) or ""
                for raw in txt.splitlines():
                    s = raw.strip()
                    if not s:
                        continue
                    if cidx == 0 and s == str(pno) and len(s) <= 3:
                        continue
                    lines.append((pno, cidx, s))
    return lines


def _is_caps_topic_header(s: str) -> bool:
    if s in _SKIP_PHARM_HEADERS:
        return False
    if len(s) < 6 or len(s) > 95:
        return False
    if re.match(r"^[A-Ja-jАаВвСсЕе]\.", s) or re.match(r"^\d+\.", s):
        return False
    if s != s.upper():
        return False
    return bool(re.search(r"[А-ЯІЇЄҐ]{4,}", s))


def _apply_known_key_fixes(stem: str, options: list[str], correct_idx: int) -> int:
    stem_low = stem.lower()
    for needle, opt_prefix in _KNOWN_KEY_FIXES:
        if needle in stem_low:
            for idx, opt in enumerate(options):
                if opt.lower().startswith(opt_prefix):
                    return idx
    return correct_idx


def parse_pharmacology_3col_pdf(
    pdf_path: Path,
    *,
    is_booklet: bool,
    module_no: int,
) -> tuple[list[ParsedQuestion], list[str | None]]:
    """Parse 3-column Pharmacology PDF.

    Returns (questions, per_question_extra_tags).
    For booklets, extra_tag is e.g. 'Буклет 2023'.
    """
    lines = _extract_3col_lines(pdf_path)
    raw_items: list[dict] = []
    cur_section: str | None = None
    cur_year: str | None = None
    cur_q: dict | None = None
    in_opts = False
    opt_style: str | None = None  # 'letter' | 'number'
    prev_was_topic_header = False

    def _flush() -> None:
        nonlocal cur_q, in_opts, opt_style
        if cur_q is not None:
            raw_items.append(cur_q)
            cur_q = None
        in_opts = False
        opt_style = None

    for pno, _cidx, s in lines:
        if s in _SKIP_PHARM_HEADERS:
            prev_was_topic_header = False
            continue

        if is_booklet:
            ym = _YEAR_HEADER_RE.match(s)
            if ym:
                _flush()
                cur_year = ym.group(1)
                cur_section = f"Буклет КРОК-1 · {s}"
                prev_was_topic_header = False
                continue
        else:
            if _is_caps_topic_header(s):
                _flush()
                if prev_was_topic_header and cur_section:
                    cur_section = f"{cur_section} {s}"
                else:
                    cur_section = s
                prev_was_topic_header = True
                continue
        prev_was_topic_header = False

        # Option by letter (A-J or Cyrillic А,В,С,Е)
        m_opt = _OPT_LETTER_RE.match(s) or _OPT_LETTER_NO_SPACE_STAR_RE.match(s)
        if m_opt and cur_q is not None:
            in_opts = True
            opt_style = "letter"
            letter = _normalize_option_letter(m_opt.group(1))
            star = m_opt.group(2)
            txt = m_opt.group(3)
            is_corr = bool(star) or txt.startswith("*")
            txt = txt.lstrip("* ").strip()
            cur_q["options"].append((letter, is_corr, txt))
            continue

        # Question start or numbered option (1..5)
        m_q = _Q_NUM_RE.match(s)
        if m_q:
            num = int(m_q.group(1))
            rest = m_q.group(2)
            # Treat as numbered option ONLY if:
            # - we are already collecting numbered options (opt_style == 'number') and num == len+1 <= 5, OR
            # - cur_q has 0 options, num == 1, and rest starts with '*' or stem ends with '?'/':' and rest is short
            if (
                cur_q is not None
                and opt_style == "number"
                and num == len(cur_q["options"]) + 1
                and num <= 5
            ):
                is_corr = rest.startswith("*")
                cur_q["options"].append((str(num), is_corr, rest.lstrip("* ").strip()))
                continue
            if (
                cur_q is not None
                and not cur_q["options"]
                and num == 1
                and (rest.startswith("*") or (cur_q["stem"].rstrip().endswith(("?", ":")) and len(rest) < 75))
            ):
                in_opts = True
                opt_style = "number"
                is_corr = rest.startswith("*")
                cur_q["options"].append((str(num), is_corr, rest.lstrip("* ").strip()))
                continue

            _flush()
            cur_q = {
                "page": pno,
                "section": cur_section,
                "year": cur_year,
                "num": num,
                "stem": rest,
                "options": [],
            }
            continue

        # Continuation line
        if cur_q is not None:
            if in_opts and cur_q["options"]:
                ltr, ic, ot = cur_q["options"][-1]
                cur_q["options"][-1] = (ltr, ic, f"{ot} {s}".strip())
            else:
                cur_q["stem"] = f"{cur_q['stem']} {s}".strip()

    _flush()

    questions: list[ParsedQuestion] = []
    extra_tags: list[str | None] = []
    for item in raw_items:
        stem = clean_display_text(item["stem"])
        raw_opts = item["options"]
        opts = [clean_display_text(t) for _, _, t in raw_opts]
        corr_indices = [idx for idx, (_, ic, _) in enumerate(raw_opts) if ic]

        topic_title = item["section"]
        if topic_title and not is_booklet:
            topic_title = _format_caps_topic_title(topic_title)

        status = "verified"
        reason = ""
        correct_idx = 0

        if len(stem) < 18:
            status = "needs_review"
            reason = f"short_stem({len(stem)})"
        elif len(opts) != 5:
            status = "needs_review"
            reason = f"options_count={len(opts)}"
            if len(opts) > 5:
                opts = opts[:5]
        elif len(corr_indices) != 1:
            status = "needs_review"
            reason = f"correct_markers={len(corr_indices)}"
        else:
            correct_idx = corr_indices[0]
            correct_idx = _apply_known_key_fixes(stem, opts, correct_idx)
            # Check empty or duplicate options
            if any(not o for o in opts):
                status = "needs_review"
                reason = "empty_option"
            elif len({o.lower() for o in opts}) < 4:
                status = "needs_review"
                reason = "duplicate_options"

        questions.append(
            ParsedQuestion(
                stem=stem,
                options=opts,
                correct_idx=correct_idx,
                topic_title=topic_title,
                module_no=module_no,
                status=status,
                review_reason=reason,
                page=item["page"],
            )
        )
        extra_tags.append(f"Буклет {item['year']}" if (is_booklet and item["year"]) else None)

    return questions, extra_tags


# ---------------------------------------------------------------------------
# Pathomorphology 1-Column Parser (Part 1 Thematic ?/+/- + Part 2 Exam Bank)
# ---------------------------------------------------------------------------

_PATH_SKIP_RE = re.compile(
    r"^(?:Тестові завдання кафедри патоморфології|"
    r"Крок 1 Загальна лікарська підготовка|"
    r"Медичний профіль\s*[–-]\s*патологічна анатомія|"
    r"Література:|"
    r"1\.\s*А\.І\.Струков)",
    re.IGNORECASE,
)
_PATH_P2_Q_RE = re.compile(r"^(\d{1,4})\.?\s+(.+)$")
_PATH_P2_OPT_RE = re.compile(r"^([A-Ea-eАаВвСсЕе])\.\s*(\*?)\s*(.+)$")


def _extract_1col_styled_lines(pdf_path: Path) -> list[tuple[int, str, bool, bool]]:
    """Extract lines with bold metadata: (page_no, text, line_is_bold, option_body_is_bold)."""
    out: list[tuple[int, str, bool, bool]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=3,
                extra_attrs=["fontname"],
            )
            if not words:
                continue
            # Group words into lines by top coordinate
            words.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
            groups: list[list[dict]] = []
            for w in words:
                if not groups or abs(w["top"] - groups[-1][0]["top"]) > 3.5:
                    groups.append([w])
                else:
                    groups[-1].append(w)

            for grp in groups:
                grp.sort(key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in grp).strip()
                if not text:
                    continue
                if text == str(pno) and len(text) <= 3:
                    continue
                total_chars = sum(len(w["text"]) for w in grp) or 1
                bold_chars = sum(
                    len(w["text"])
                    for w in grp
                    if "bold" in (w.get("fontname") or "").lower()
                )
                line_is_bold = (bold_chars / total_chars) >= 0.65

                # For "A. Option text", check bold ratio excluding the leading "A." token
                body_words = grp[1:] if len(grp) > 1 and re.match(r"^[A-Ea-eАаВвСсЕе]\.$", grp[0]["text"]) else grp
                body_chars = sum(len(w["text"]) for w in body_words) or 1
                body_bold_chars = sum(
                    len(w["text"])
                    for w in body_words
                    if "bold" in (w.get("fontname") or "").lower()
                )
                body_is_bold = (body_bold_chars / body_chars) >= 0.65

                out.append((pno, text, line_is_bold, body_is_bold))
    return out


def _answers_equivalent(a1: str, a2: str) -> bool:
    """Return True when two Ukrainian answer strings represent the same term."""
    n1 = normalize_for_hash(a1)
    n2 = normalize_for_hash(a2)
    if not n1 or not n2:
        return False
    if n1 == n2 or n1 in n2 or n2 in n1:
        return True
    if difflib.SequenceMatcher(None, n1, n2).ratio() >= 0.78:
        return True
    t1 = {w for w in n1.split() if len(w) >= 3} or set(n1.split())
    t2 = {w for w in n2.split() if len(w) >= 3} or set(n2.split())
    if not t1 or not t2:
        return False
    return (len(t1 & t2) / len(t1 | t2)) >= 0.5


def parse_pathomorphology_pdf(pdf_path: Path) -> dict:
    """Parse Pathomorphology PDF into Part 1 (Thematic, pp. 1-96) and Part 2 (Exam Bank, pp. 97-198).

    Returns dict with keys:
      part1_questions: list[ParsedQuestion]
      part2_questions: list[ParsedQuestion]  (Ukrainian-only, deduplicated against Part 1)
      part2_dup_hashes: set[str]             (norm_hashes from Part 2 that matched Part 1)
      stats: dict[str, int]
    """
    styled_lines = _extract_1col_styled_lines(pdf_path)

    p1_lines: list[tuple[int, str, bool]] = []
    p2_lines: list[tuple[int, str, bool, bool]] = []
    in_part2 = False
    skip_lit = False

    for pno, text, is_bold, body_bold in styled_lines:
        if "Екзаменаційний банк" in text:
            in_part2 = True
            skip_lit = False
            continue
        if not in_part2:
            if text.startswith("Література:"):
                skip_lit = True
                continue
            if skip_lit:
                continue
            if _PATH_SKIP_RE.match(text):
                continue
            p1_lines.append((pno, text, is_bold))
        else:
            if _PATH_SKIP_RE.match(text):
                continue
            p2_lines.append((pno, text, is_bold, body_bold))

    # --- Parse Part 1 (? / + / -) ---
    part1_raw: list[dict] = []
    cur_topic: str | None = None
    cur_q: dict | None = None
    in_opts = False
    prev_was_bold_topic = False

    def _flush_p1() -> None:
        nonlocal cur_q, in_opts
        if cur_q is not None:
            part1_raw.append(cur_q)
            cur_q = None
        in_opts = False

    for pno, s, is_bold in p1_lines:
        if s == "?":
            if cur_q is not None and cur_q["stem"] and not cur_q["options"]:
                cur_q["stem"] = f"{cur_q['stem']}?".strip()
                continue
            prev_was_bold_topic = False
            _flush_p1()
            cur_q = {"page": pno, "topic": cur_topic, "stem": "", "options": []}
            continue

        if is_bold and not s.startswith(("+", "-")):
            _flush_p1()
            if prev_was_bold_topic and cur_topic:
                cur_topic = f"{cur_topic} {s}"
            else:
                cur_topic = s
            prev_was_bold_topic = True
            continue
        prev_was_bold_topic = False

        if cur_q is None:
            continue

        if s.startswith("+") and (not in_opts or len(cur_q["options"]) < 5):
            in_opts = True
            cur_q["options"].append((True, s[1:].strip()))
            continue
        if s.startswith("-") and (in_opts or cur_q["stem"]):
            in_opts = True
            cur_q["options"].append((False, s[1:].strip()))
            continue

        if in_opts and cur_q["options"]:
            ic, ot = cur_q["options"][-1]
            cur_q["options"][-1] = (ic, f"{ot} {s}".strip())
        else:
            cur_q["stem"] = f"{cur_q['stem']} {s}".strip()

    _flush_p1()

    part1_questions: list[ParsedQuestion] = []
    part1_hashes: set[str] = set()
    part1_verified_index: list[tuple[str, set[str], str]] = []
    for item in part1_raw:
        stem = clean_latex_artifacts(item["stem"])
        raw_opts = item["options"]
        opts = [clean_latex_artifacts(t) for _, t in raw_opts]
        corr_indices = [idx for idx, (ic, _) in enumerate(raw_opts) if ic]
        topic_title = clean_display_text(item["topic"]).rstrip(".") if item["topic"] else None

        status = "verified"
        reason = ""
        correct_idx = 0
        if len(stem) < 18:
            status = "needs_review"
            reason = f"short_stem({len(stem)})"
        elif len(opts) != 5:
            status = "needs_review"
            reason = f"options_count={len(opts)}"
            if len(opts) > 5:
                opts = opts[:5]
        elif len(corr_indices) != 1:
            status = "needs_review"
            reason = f"correct_markers={len(corr_indices)}"
        else:
            correct_idx = corr_indices[0]
            if any(not o for o in opts):
                status = "needs_review"
                reason = "empty_option"

        pq = ParsedQuestion(
            stem=stem,
            options=opts,
            correct_idx=correct_idx,
            topic_title=topic_title,
            module_no=1,
            status=status,
            review_reason=reason,
            page=item["page"],
        )
        part1_questions.append(pq)
        nh_p1 = normalize_for_hash(stem)
        part1_hashes.add(nh_p1)
        if status == "verified":
            toks_p1 = {w for w in nh_p1.split() if len(w) >= 4}
            part1_verified_index.append((nh_p1, toks_p1, opts[correct_idx]))

    # --- Parse Part 2 (Exam Bank: numbered + A..E with * or Bold) ---
    part2_raw: list[dict] = []
    cur_q2: dict | None = None
    in_opts2 = False

    def _flush_p2() -> None:
        nonlocal cur_q2, in_opts2
        if cur_q2 is not None:
            part2_raw.append(cur_q2)
            cur_q2 = None
        in_opts2 = False

    for pno, s, _is_bold, body_bold in p2_lines:
        m_opt = _PATH_P2_OPT_RE.match(s)
        if m_opt and cur_q2 is not None:
            in_opts2 = True
            letter = _normalize_option_letter(m_opt.group(1))
            star = m_opt.group(2)
            txt = m_opt.group(3)
            has_star = bool(star) or txt.startswith("*")
            txt = txt.lstrip("* ").strip()
            cur_q2["options"].append((letter, has_star, body_bold, txt))
            continue

        m_q = _PATH_P2_Q_RE.match(s)
        if m_q and (cur_q2 is None or in_opts2):
            _flush_p2()
            cur_q2 = {"page": pno, "num": int(m_q.group(1)), "stem": m_q.group(2), "options": []}
            continue

        if cur_q2 is not None:
            if in_opts2 and cur_q2["options"]:
                ltr, hs, bb, ot = cur_q2["options"][-1]
                cur_q2["options"][-1] = (ltr, hs, bb or body_bold, f"{ot} {s}".strip())
            else:
                cur_q2["stem"] = f"{cur_q2['stem']} {s}".strip()

    _flush_p2()

    part2_questions: list[ParsedQuestion] = []
    part2_dup_hashes: set[str] = set()
    p2_seen_hashes: set[str] = set()
    skipped_russian = 0
    skipped_dup_p1 = 0
    skipped_dup_p2 = 0

    for item in part2_raw:
        stem = clean_latex_artifacts(item["stem"])
        raw_opts = item["options"]
        opts = [clean_latex_artifacts(t) for _, _, _, t in raw_opts]

        # Filter Russian questions in Part 2
        if is_russian_text(stem) or (opts and is_russian_text(" ".join(opts))):
            skipped_russian += 1
            continue

        nh = normalize_for_hash(stem)
        if nh in part1_hashes:
            part2_dup_hashes.add(nh)
            skipped_dup_p1 += 1
            continue
        if nh in p2_seen_hashes:
            skipped_dup_p2 += 1
            continue
        p2_seen_hashes.add(nh)

        star_indices = [idx for idx, (_, hs, _, _) in enumerate(raw_opts) if hs]
        bold_indices = [idx for idx, (_, _, bb, _) in enumerate(raw_opts) if bb]

        status = "verified"
        reason = ""
        correct_idx = 0
        if len(stem) < 18:
            status = "needs_review"
            reason = f"short_stem({len(stem)})"
        elif len(opts) != 5:
            status = "needs_review"
            reason = f"options_count={len(opts)}"
            if len(opts) > 5:
                opts = opts[:5]
        elif len(star_indices) == 1:
            correct_idx = star_indices[0]
        elif len(star_indices) == 0 and len(bold_indices) == 1:
            correct_idx = bold_indices[0]
        else:
            status = "needs_review"
            reason = f"stars={len(star_indices)},bold={len(bold_indices)}"

        if status == "verified" and any(not o for o in opts):
            status = "needs_review"
            reason = "empty_option"

        if status == "verified" and part1_verified_index:
            toks = {w for w in nh.split() if len(w) >= 4}
            if toks:
                best_nh, best_toks, best_ans = max(
                    part1_verified_index,
                    key=lambda x: len(toks & x[1]) / max(1, len(toks | x[1])),
                )
                jaccard = len(toks & best_toks) / max(1, len(toks | best_toks))
                if jaccard >= 0.65 and _answers_equivalent(opts[correct_idx], best_ans):
                    part2_dup_hashes.add(best_nh)
                    skipped_dup_p1 += 1
                    continue

        part2_questions.append(
            ParsedQuestion(
                stem=stem,
                options=opts,
                correct_idx=correct_idx,
                topic_title="Екзаменаційний банк (додаткові)",
                module_no=2,
                status=status,
                review_reason=reason,
                page=item["page"],
            )
        )

    return {
        "part1_questions": part1_questions,
        "part2_questions": part2_questions,
        "part2_dup_hashes": part2_dup_hashes,
        "stats": {
            "part1_total": len(part1_questions),
            "part1_verified": sum(1 for q in part1_questions if q.status == "verified"),
            "part1_review": sum(1 for q in part1_questions if q.status != "verified"),
            "part2_raw": len(part2_raw),
            "part2_skipped_russian": skipped_russian,
            "part2_skipped_dup_part1": skipped_dup_p1,
            "part2_skipped_dup_internal": skipped_dup_p2,
            "part2_unique_uk": len(part2_questions),
            "part2_verified": sum(1 for q in part2_questions if q.status == "verified"),
            "part2_review": sum(1 for q in part2_questions if q.status != "verified"),
        },
    }


# ---------------------------------------------------------------------------
# Multi-tag SQLite importer with non-destructive deduplication & FTS5 rebuild
# ---------------------------------------------------------------------------

def import_parsed_bank(
    questions: list[ParsedQuestion],
    *,
    subject_slug: str,
    subject_title: str,
    subject_icon: str,
    subject_sort_order: int,
    base_source_tag: str,
    extra_tags: list[str | None] | None = None,
    db_path: Path | str | None = None,
) -> dict[str, int]:
    """Insert or merge parsed questions into SQLite without touching existing users/progress."""
    init_db(db_path)
    now_ts = int(time.time())
    stats = {
        "total_parsed": len(questions),
        "inserted_verified": 0,
        "inserted_review": 0,
        "duplicates_merged": 0,
        "upgraded_from_review": 0,
    }

    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO subjects (slug, title_uk, sort_order, icon)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title_uk = excluded.title_uk,
                sort_order = excluded.sort_order,
                icon = excluded.icon
            """,
            (subject_slug, subject_title, subject_sort_order, subject_icon),
        )
        subject_id = int(
            cur.execute("SELECT id FROM subjects WHERE slug = ?", (subject_slug,)).fetchone()["id"]
        )

        topic_cache: dict[tuple[int, str], int] = {}
        for row in cur.execute("SELECT id, module_no, title_uk FROM topics WHERE subject_id = ?", (subject_id,)):
            topic_cache[(int(row["module_no"]), row["title_uk"])] = int(row["id"])
        next_sort = len(topic_cache) + 1

        def _get_topic_id(mod_no: int, title: str | None) -> int | None:
            nonlocal next_sort
            if not title:
                return None
            key = (mod_no, title)
            if key in topic_cache:
                return topic_cache[key]
            cur.execute(
                """
                INSERT INTO topics (subject_id, module_no, title_uk, sort_order)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(subject_id, module_no, title_uk) DO NOTHING
                """,
                (subject_id, mod_no, title, next_sort),
            )
            tid = int(
                cur.execute(
                    "SELECT id FROM topics WHERE subject_id = ? AND module_no = ? AND title_uk = ?",
                    (subject_id, mod_no, title),
                ).fetchone()["id"]
            )
            topic_cache[key] = tid
            next_sort += 1
            return tid

        for idx, q in enumerate(questions):
            tags_to_add = [base_source_tag]
            if extra_tags and idx < len(extra_tags) and extra_tags[idx]:
                tags_to_add.append(extra_tags[idx])

            nhash = compute_norm_hash(q.stem)
            existing = cur.execute(
                "SELECT id, subject_id, source_tags, status FROM questions WHERE norm_hash = ?",
                (nhash,),
            ).fetchone()
            if existing is not None:
                stats["duplicates_merged"] += 1
                tags = json.loads(existing["source_tags"])
                changed = False
                # Only merge tags when the duplicate belongs to the same subject
                if int(existing["subject_id"]) == subject_id:
                    for tg in tags_to_add:
                        if tg not in tags:
                            tags.append(tg)
                            changed = True
                if existing["status"] == "needs_review" and q.status == "verified":
                    cur.execute(
                        """
                        UPDATE questions
                        SET source_tags = ?, status = 'verified', options_json = ?,
                            correct_idx = ?, stem = ?
                        WHERE id = ?
                        """,
                        (
                            json.dumps(tags, ensure_ascii=False),
                            json.dumps(q.options, ensure_ascii=False),
                            q.correct_idx,
                            q.stem,
                            existing["id"],
                        ),
                    )
                    stats["upgraded_from_review"] += 1
                elif changed:
                    cur.execute(
                        "UPDATE questions SET source_tags = ? WHERE id = ?",
                        (json.dumps(tags, ensure_ascii=False), existing["id"]),
                    )
                continue

            topic_id = _get_topic_id(q.module_no, q.topic_title)
            cur.execute(
                """
                INSERT INTO questions (
                    subject_id, topic_id, norm_hash, stem, options_json,
                    correct_idx, source_tags, status, created_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subject_id,
                    topic_id,
                    nhash,
                    q.stem,
                    json.dumps(q.options, ensure_ascii=False),
                    q.correct_idx,
                    json.dumps(tags_to_add, ensure_ascii=False),
                    q.status,
                    now_ts,
                ),
            )
            if q.status == "verified":
                stats["inserted_verified"] += 1
            else:
                stats["inserted_review"] += 1

        # Rebuild FTS5 index so all newly imported/updated questions are instantly searchable
        cur.execute("INSERT INTO questions_fts(questions_fts) VALUES('rebuild')")
        conn.commit()

    return stats


def tag_duplicate_hashes(
    norm_hashes: set[str],
    *,
    subject_slug: str,
    tag_to_add: str,
    db_path: Path | str | None = None,
) -> int:
    """Attach an additional source_tag to existing questions matching normalized stem strings."""
    if not norm_hashes:
        return 0
    import hashlib

    sha_set = {hashlib.sha256(nh.encode("utf-8")).hexdigest() for nh in norm_hashes}
    updated = 0
    with db_session(db_path) as conn:
        cur = conn.cursor()
        srow = cur.execute("SELECT id FROM subjects WHERE slug = ?", (subject_slug,)).fetchone()
        if srow is None:
            return 0
        sid = int(srow["id"])
        for row in cur.execute("SELECT id, norm_hash, source_tags FROM questions WHERE subject_id = ?", (sid,)):
            if row["norm_hash"] in sha_set:
                tags = json.loads(row["source_tags"])
                if tag_to_add not in tags:
                    tags.append(tag_to_add)
                    cur.execute(
                        "UPDATE questions SET source_tags = ? WHERE id = ?",
                        (json.dumps(tags, ensure_ascii=False), row["id"]),
                    )
                    updated += 1
        conn.commit()
    return updated


