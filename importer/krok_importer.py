"""Positional PDF importer & deduplicator for KROK Trainer (Phase 1)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from app.db import db_session, init_db

# Characters visually identical between Latin and Cyrillic in Ukrainian KROK PDFs.
_HOMOGLYPH_MAP = str.maketrans({
    "a": "а",
    "c": "с",
    "e": "е",
    "i": "і",
    "o": "о",
    "p": "р",
    "x": "х",
    "y": "у",
    "k": "к",
    "m": "м",
    "h": "н",
    "t": "т",
    "b": "в",
})

_CYR_I_LEFT_RE = re.compile(r"(?<=[а-яіїєґА-ЯІЇЄҐ])i")
_CYR_I_RIGHT_RE = re.compile(r"i(?=[а-яіїєґА-ЯІЇЄҐ])")
_CYR_CAP_I_LEFT_RE = re.compile(r"(?<=[а-яіїєґА-ЯІЇЄҐ])I")
_CYR_CAP_I_RIGHT_RE = re.compile(r"I(?=[а-яіїєґА-ЯІЇЄҐ])")

_LEADING_NUM_RE = re.compile(r"^\s*\d{1,4}[\.\)]\s*")
_TOPIC_HDR_RE = re.compile(r"^(\d{1,2})\.\s*(.+)$")
_MODULE_HDR_RE = re.compile(r"^Змістовий\s+модуль\s+(\d+)\.?", re.I)

# Grammatical linkers/prepositions that never end a complete option on their own.
_LINKERS = {
    "за", "з", "зі", "із", "від", "до", "на", "у", "в", "та", "і", "й",
    "або", "чи", "при", "для", "проти", "по", "після", "через", "над",
    "під", "між", "без", "біля", "серед", "про", "що", "які", "яка", "роду", "виду",
    "яке", "який", "щодо", "№", "ig", "anti", "anti-",
}

# Head nouns that take a capitalized eponym, acronym, or serotype directly after them.
_EPONYM_HEAD_WORDS = {
    "метод", "методом", "методу", "методи", "методика", "методикою",
    "реакція", "реакції", "реакцію", "реакцією", "реакціями",
    "середовище", "середовищі", "середовища", "середі", "середу", "агар", "агарі", "агару",
    "проба", "проби", "пробу", "пробою", "тільця", "тілець", "зерна", "зерен",
    "набряк", "лімфома", "ангіна", "дизентерія", "дизентерії", "шигела", "шигели",
    "вірус", "вірусу", "віруса", "вірусів", "тип", "типу", "клас", "класу",
    "група", "групи", "синдром", "хвороба", "хвороби", "апарат", "апарата",
    "вакцина", "вакцини", "анатоксин", "сироватка", "сироватки",
    "лікування", "діагностика", "профілактика", "збудник", "збудника", "антиген",
    "проти", "гепатит", "гепатиту", "герпес", "штам", "штаму", "рід", "вид",
    "паличка", "палички", "коксакі", "секреторного", "рівня", "рівень", "вміст",
    "активація", "синтез", "виділення", "визначення", "виявлення",
    "працівників", "хворого", "хворої", "пацієнта", "дитини",
    "всіх", "усіх", "бурої", "первинний", "вторинний",
    "напіврідкий", "кров’яний", "кров'яний", "жовточно-сольовий", "молочно-сольовий",
    "електронна", "люмінесцентна", "імунна", "пряма", "непряма", "прямий", "непрямий",
    "твердофазний", "розгорнута", "клінічної", "гемолітична",
    "жива", "живу", "убита", "вбита", "хімічна", "комбіновану", "асоційована",
    "протидифтерійну", "протиправцеву", "антирабічну", "аутовакцина",
    "табл", "мг", "мл", "мкм", "од", "року", "років",
}

# Known Ukrainian eponyms, acronyms, and type markers that follow _EPONYM_HEAD_WORDS.
_EPONYMS_AND_TYPES = {
    "грама", "грам", "нільсена", "ціля-нільсена", "цілем-нільсеном", "цілем-нільсена",
    "циля-нільсена", "буррі", "бурі", "гінса", "буррі-гінса", "гінсом-буррі",
    "ожешки", "ожешко", "нейссера", "нейсера", "леффлера", "пешкова",
    "романовського", "романовського-гімза", "романовським-гімза", "гімза",
    "здродовського", "сабуро", "ендо", "левіна", "гіса", "гісса", "ресселя",
    "мюллера", "кітта-тароцці", "кіттa-тароцці", "плоскірєва", "вільсона-блера",
    "левентштейна", "левенштейна-йєнсена", "левенштейна-йенсена", "ігла",
    "кумбса", "вассермана", "відаля", "райта", "хедльсона", "асколі",
    "борде-жангу", "борде", "жангу", "манту", "діка", "шіка", "шика", "бюрне",
    "артюса", "феномен", "прайса",
    "пашена", "гварнієрі", "бабеша-негрі", "бабеша-ернста", "арагао", "люпшютца",
    "квінке", "беркета", "симановського-венсана", "кротова",
    "зонне", "флекснера", "бойда", "нью-кастла", "григор’єва-шига",
    "коксакі", "епштейна-барр", "епштейна-бар", "марбург", "ебола", "ласса",
    "шкт", "цнс", "віл", "снід", "бцж", "акдп", "адп", "адп-м",
    "рзк", "рпга", "ріф", "іфа", "плр", "ра", "рн", "ртга", "ргга", "рнга", "рп", "ріа",
    "мпа", "мпб", "жса", "цпд", "цпм", "орз", "грві", "тавte", "тавте",
    "ев", "ev", "сті", "sti", "hbs", "hbsag", "hbeag", "hav", "hbv", "hcv", "hdv", "hev",
    "dna", "rna", "днк", "рнк", "і-рнк", "т-хелпери", "в-лімфоцити",
    "а", "в", "с", "д", "е", "о", "н", "і", "к", "м", "g", "d", "e", "a", "b", "c",
    "1", "2", "3", "4", "5", "6", "I", "II", "III", "IV", "V", "IV",
}

_LATIN_GENUS_RAW = {
    "staphylococcus", "streptococcus", "neisseria", "escherichia", "salmonella",
    "shigella", "vibrio", "corynebacterium", "bordetella", "mycobacterium",
    "clostridium", "bacillus", "brucella", "yersinia", "francisella",
    "rickettsia", "chlamydia", "mycoplasma", "treponema", "borrelia",
    "leptospira", "candida", "trichophyton", "microsporum", "epidermophyton",
    "aspergillus", "penicillium", "mucor", "proteus", "klebsiella",
    "pseudomonas", "enterococcus", "helicobacter", "campylobacter", "haemophilus",
    "legionella", "listeria", "actinomyces", "nocardia", "entamoeba",
    "lamblia", "giardia", "trichomonas", "toxoplasma", "plasmodium",
    "leishmania", "trypanosoma", "balantidium", "herpes",
    "epstein", "epstein-barr", "varicella", "varicella-zoster",
    "coxsackie", "coxsacki-virus", "calymmatobacterium", "gram+", "gram-",
}
_LATIN_GENUS_HOMO = {w.translate(_HOMOGLYPH_MAP) for w in _LATIN_GENUS_RAW}
_EPONYMS_HOMO = {w.translate(_HOMOGLYPH_MAP) for w in _EPONYMS_AND_TYPES}
_EPONYM_HEAD_HOMO = {w.translate(_HOMOGLYPH_MAP) for w in _EPONYM_HEAD_WORDS}
_LINKERS_HOMO = {w.translate(_HOMOGLYPH_MAP) for w in _LINKERS}

_REPEATED_PREFIX_PHRASES = [
    "За допомогою", "У разі", "Під час", "В результаті", "Внаслідок",
    "За рахунок", "Проти", "Для", "Метод", "Методом", "Реакція", "Реакцію",
    "Реакцією", "Вірус", "Вірусу", "Віруса", "Сироватка", "Сироватки",
    "Середовище", "Середовищі", "Агар", "Вода", "Наявність", "Наявності",
    "Відсутність", "Чутливість", "Виділення", "Визначення", "Введення",
    "Вивчити", "Зниження", "Підвищення", "Посилює", "Сприяє", "Викликає",
    "Стимулює", "Забезпечує", "Утворення", "Розташування", "Кількість",
    "Всі", "Усі", "На", "До", "З", "Із", "Від", "За", "При",
    "Anti-", "Herpes", "Streptococcus", "Staphylococcus", "Clostridium",
    "Salmonella", "Shigella", "Mycobacterium", "Corynebacterium", "Neisseria",
    "Escherichia", "Treponema", "Vibrio", "Bacillus", "Yersinia", "Brucella",
    "Chlamydia", "Mycoplasma", "Rickettsia", "Candida", "Грипозна", "Гепатит",
    "Про", "По", "Пряма", "Прямий", "Непряма", "Непрямий",
]

# Notice: standalone single words like "Фекалії" or "Реакція" are NOT in stem openers
# unless followed by clinical context!
_NEW_STEM_OPENERS_RE = re.compile(
    r"^(?:"
    r"У\s|В\s|При\s|З\s|Із\s|До\s|Для\s|На\s|Під\s+час\s|Після\s|Через\s|"
    r"Хвор[иіоа]|Пацієнт|Жін[ціко]|Чоловік|Дитин[аіи]|Дівчин|Хлопчик|Немовля|"
    r"Лікар|Студент|Мислив|Робітник|Працівник|Вагітн|Юнак|Людин|"
    r"В\s+лабораторі|У\s+лабораторі|У\s+кліні|В\s+кліні|У\s+дитяч|В\s+інфекційн|"
    r"Мікробіологіч|Бактеріологіч|Вірусологіч|Серологіч|Імунологіч|"
    r"Вкажіть|Назвіть|Який|Яка|Яке|Які|Що\s|Де\s|Котр|Скільки|"
    r"Збудник\s|Основним|Реакція\s+імуно|Встановлено|При\s+мікроскопі|"
    r"Випорожнення\s|Матеріалом\s|Фекалії\s|З\s+метою|Зважаючи|"
    r"П'ятирічний|П’ятирічний|Новонароджен|Семирічного|Оглядаючи|"
    r"Інвазивні|Деякі\s+патоген|Патогенні\s+бактері|В\s+імунодіагностиц|"
    r"Ефективна\s+діагностика|Прикладом\s+специфічних"
    r")"
)


@dataclass
class WordBox:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    fontname: str = ""
    size: float = 12.0


@dataclass
class PdfLine:
    page: int
    y0: float
    x0: float
    x1: float
    dy: float | None
    text: str
    words: list[WordBox]
    is_bold: bool
    size: float
    first_on_page: bool


@dataclass
class ParsedQuestion:
    stem: str
    options: list[str]
    correct_idx: int = 0
    topic_title: str | None = None
    module_no: int = 1
    status: str = "verified"
    review_reason: str = ""
    page: int = 0


@dataclass
class ImportStats:
    file_name: str
    module_no: int
    source_tag: str
    total_parsed: int = 0
    inserted: int = 0
    duplicates_merged: int = 0
    upgraded_from_review: int = 0
    verified: int = 0
    needs_review: int = 0
    review_items: list[dict] = field(default_factory=list)
    sample_questions: list[dict] = field(default_factory=list)


_BAD_ENCODING_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\u007f-\u009f\u4e00-\u9fff\u0800-\u083f\u1600-\u1cff\u3100-\u312f]"
)


def sanitize_text_encoding(text: str) -> str:
    """Strip control/CJK/Symbol-font garbage and normalize escaped % and low quotes."""
    s = unicodedata.normalize("NFKC", text)
    s = _BAD_ENCODING_RE.sub(" ", s)
    s = s.replace("\\%", "%")
    s = s.replace("`", "’").replace("\u2212", "-")
    s = re.sub(r"„([^„”«»]{1,120})[”\"]", r"«\1»", s)
    s = s.replace("„", "«").replace("”", "»")
    s = s.replace("сифиліс", "сифіліс").replace("Сифиліс", "Сифіліс")
    return s


def clean_display_text(text: str) -> str:
    """Clean PDF whitespace artifacts and fix Latin i/I inside Cyrillic words."""
    s = sanitize_text_encoding(text)
    s = s.replace("\u00a0", " ").replace("\xad", "")
    for _ in range(3):
        s = _CYR_I_LEFT_RE.sub("і", s)
        s = _CYR_I_RIGHT_RE.sub("і", s)
        s = _CYR_CAP_I_LEFT_RE.sub("І", s)
        s = _CYR_CAP_I_RIGHT_RE.sub("І", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,?;:])", r"\1", s)
    return s


def normalize_for_hash(stem: str) -> str:
    """Compute canonical deduplication string for a question stem."""
    s = unicodedata.normalize("NFKC", stem)
    s = _LEADING_NUM_RE.sub("", s)
    s = s.lower().translate(_HOMOGLYPH_MAP)
    s = re.sub(r"[’ʼ`'\"«»“”„]", "", s)
    s = re.sub(r"[^a-zа-яіїєґ0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def compute_norm_hash(stem: str) -> str:
    """SHA-256 hex digest of normalized stem."""
    return hashlib.sha256(normalize_for_hash(stem).encode("utf-8")).hexdigest()


def _split_midline_question_mark(line: PdfLine) -> list[PdfLine]:
    """If a stem ends with '?' mid-line followed by option text (e.g. KKR p101), split into 2 PdfLines."""
    # Find index of word ending with '?' where at least one substantive word follows it on the same line.
    for idx, wb in enumerate(line.words[:-1]):
        if wb.text.endswith("?"):
            nxt_txt = line.words[idx + 1].text
            if nxt_txt and (nxt_txt[0].isupper() or nxt_txt[0].isdigit()):
                stem_words = line.words[: idx + 1]
                opt_words = line.words[idx + 1 :]
                l1 = PdfLine(
                    page=line.page,
                    y0=line.y0,
                    x0=stem_words[0].x0,
                    x1=stem_words[-1].x1,
                    dy=line.dy,
                    text=" ".join(w.text for w in stem_words),
                    words=stem_words,
                    is_bold=line.is_bold,
                    size=line.size,
                    first_on_page=line.first_on_page,
                )
                l2 = PdfLine(
                    page=line.page,
                    y0=line.y0,
                    x0=opt_words[0].x0,
                    x1=opt_words[-1].x1,
                    dy=21.0,
                    text=" ".join(w.text for w in opt_words),
                    words=opt_words,
                    is_bold=False,
                    size=line.size,
                    first_on_page=False,
                )
                return [l1, l2]
    return [line]


def extract_lines_pdfplumber(pdf_path: Path) -> list[PdfLine]:
    """Extract positional lines sorted top-to-bottom with font metadata using pdfplumber."""
    result: list[PdfLine] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            words_raw = page.extract_words(extra_attrs=["fontname", "size"])
            # Sort strictly top-to-bottom then left-to-right so stream order never scrambles lines.
            words_sorted = sorted(words_raw, key=lambda w: (round(float(w["top"]), 1), float(w["x0"])))
            buckets: list[list[WordBox]] = []
            for w in words_sorted:
                wb = WordBox(
                    text=w["text"],
                    x0=float(w["x0"]),
                    x1=float(w["x1"]),
                    top=float(w["top"]),
                    bottom=float(w["bottom"]),
                    fontname=str(w.get("fontname", "")),
                    size=float(w.get("size", 12.0)),
                )
                if buckets and abs(wb.top - buckets[-1][0].top) <= 4.5:
                    buckets[-1].append(wb)
                else:
                    buckets.append([wb])

            prev_y: float | None = None
            for line_idx, wb_list in enumerate(buckets):
                wb_list.sort(key=lambda b: b.x0)
                text = " ".join(b.text for b in wb_list).strip()
                if not text:
                    continue
                y0 = wb_list[0].top
                dy = (y0 - prev_y) if prev_y is not None else None
                prev_y = y0
                bold_count = sum(1 for b in wb_list if "bold" in b.fontname.lower())
                is_bold = bold_count > len(wb_list) / 2.0
                max_size = max(b.size for b in wb_list)
                raw_line = PdfLine(
                    page=page_idx + 1,
                    y0=y0,
                    x0=wb_list[0].x0,
                    x1=wb_list[-1].x1,
                    dy=dy,
                    text=text,
                    words=wb_list,
                    is_bold=is_bold,
                    size=max_size,
                    first_on_page=(line_idx == 0),
                )
                result.extend(_split_midline_question_mark(raw_line))
    return result


def extract_lines_bbox(pdf_path: Path) -> list[PdfLine]:
    """Extract positional lines using `pdftotext -bbox-layout` XML output."""
    proc = subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    xml_text = re.sub(r'\sxmlns="[^"]+"', "", proc.stdout, count=1)
    root = ET.fromstring(xml_text)
    result: list[PdfLine] = []
    for p_idx, page_el in enumerate(root.findall(".//page")):
        page_words: list[WordBox] = []
        for w_el in page_el.findall(".//word"):
            txt = (w_el.text or "").strip()
            if not txt:
                continue
            page_words.append(
                WordBox(
                    text=txt,
                    x0=float(w_el.attrib["xMin"]),
                    x1=float(w_el.attrib["xMax"]),
                    top=float(w_el.attrib["yMin"]),
                    bottom=float(w_el.attrib["yMax"]),
                )
            )
        page_words.sort(key=lambda b: (round(b.top, 1), b.x0))
        buckets: list[list[WordBox]] = []
        for wb in page_words:
            if buckets and abs(wb.top - buckets[-1][0].top) <= 4.5:
                buckets[-1].append(wb)
            else:
                buckets.append([wb])
        prev_y: float | None = None
        for l_idx, wb_list in enumerate(buckets):
            wb_list.sort(key=lambda b: b.x0)
            y0 = wb_list[0].top
            dy = (y0 - prev_y) if prev_y is not None else None
            prev_y = y0
            raw_line = PdfLine(
                page=p_idx + 1,
                y0=y0,
                x0=wb_list[0].x0,
                x1=wb_list[-1].x1,
                dy=dy,
                text=" ".join(b.text for b in wb_list),
                words=wb_list,
                is_bold=False,
                size=12.0,
                first_on_page=(l_idx == 0),
            )
            result.extend(_split_midline_question_mark(raw_line))
    return result


def _split_line_by_large_gaps(line: PdfLine, min_gap: float = 18.0) -> list[str]:
    """Split a PdfLine into column fragments when horizontal word gap exceeds threshold."""
    if not line.words:
        return [line.text]
    chunks: list[list[WordBox]] = [[line.words[0]]]
    for w in line.words[1:]:
        gap = w.x0 - chunks[-1][-1].x1
        if gap > min_gap:
            chunks.append([w])
        else:
            chunks[-1].append(w)
    return [" ".join(b.text for b in chunk).strip() for chunk in chunks if chunk]


def _should_split_before_upper(prev_tokens: list[str], next_tokens: list[str]) -> bool:
    """Decide whether an uppercase token starts a new glued option."""
    if not prev_tokens or not next_tokens:
        return False
    prev_raw = prev_tokens[-1]
    prev_clean = prev_raw.lower().rstrip(",.;:!?")
    prev_homo = prev_clean.translate(_HOMOGLYPH_MAP)

    next_raw = next_tokens[0]
    next_clean = next_raw.lower().rstrip(",.;:!?")
    next_homo = next_clean.translate(_HOMOGLYPH_MAP)

    # Never split mid-abbreviation like "Т. pallidum" or "E. coli".
    if len(prev_clean) <= 2 and prev_raw.endswith("."):
        return False
    # Never split if previous token ended with punctuation connectors.
    if prev_raw.endswith((",", "(", "-", "–", "—", ":")):
        return False
    # Never split after pure linkers/prepositions/Ig.
    if prev_homo in _LINKERS_HOMO:
        return False
    # Keep two-word Latin binomials together (Staphylococcus aureus, Francisella tularensis).
    if prev_homo in _LATIN_GENUS_HOMO:
        return False
    # Keep eponyms/acronyms/serotypes attached when preceded by a valid head noun or preposition.
    if prev_homo in _EPONYM_HEAD_HOMO and (
        next_homo in _EPONYMS_HOMO
        or next_homo in _LATIN_GENUS_HOMO
        or (len(next_clean) <= 2 and next_raw not in {"А", "В", "С"} or next_homo in {"iv", "ii", "iii"})
        or (prev_homo not in {"реакціі", "реакція"} and bool(re.fullmatch(r"[A-ZА-ЯІЇЄҐ0-9]{1,5}[+-]?", next_raw)))
    ):
        return False
    # Keep "феномен Артюса", "типа сироваткової", "типа феномен Артюса".
    if prev_homo in {"типа", "типу", "феномен"} and next_homo in _EPONYMS_HOMO:
        return False
    # Specific compound cases like "тип 1", "група В", "гепатит В", "хвороба Боткіна", "ВІЛ-інфекція".
    if prev_homo in {"гепатит", "гепатиту", "тип", "типу", "група", "групи", "коксакі"} and len(next_clean) <= 3:
        return False
    # Keep "Т-хелпери", "В-лімфоцити" or "РН вірусів" together when acronym is followed by lowercase (handled outside).
    # Keep "Ig M, IgG" -> "Ig" is in _LINKERS, and after "IgM," comma check handles it; if no comma, allow split on next "Ig".
    if prev_raw in {"anti-", "Anti-"} or next_raw in {"IgM", "IgG", "IgA", "Ag", "Ag+"}:
        return False
    # Keep "ЕV СТІ" anthrax strain intact ("Живу вакцину ЕV СТІ")
    if prev_homo in {"ев", "ev"} and next_homo in {"сті", "sti"}:
        return False
    # Keep "А, В, С" or "А і В" etc.
    if len(prev_clean) == 1 and len(next_clean) == 1:
        return False
    return True


def split_glued_options_line(text: str) -> list[str]:
    """Split a single line that may contain 2..5 glued options."""
    s = clean_display_text(text)
    if not s:
        return []

    marked = s
    for phrase in sorted(_REPEATED_PREFIX_PHRASES, key=len, reverse=True):
        esc = re.escape(phrase)
        pat = re.compile(rf"(?<=\S)\s+(?={esc}(?:\s|$))")
        if len(pat.findall(marked)) >= 1 and (
            marked.startswith(phrase) or len(re.findall(rf"\b{esc}\b", marked)) >= 2
        ):
            marked = pat.sub("\x00SPLIT\x00", marked)

    if "\x00SPLIT\x00" in marked:
        parts = [p.strip() for p in marked.split("\x00SPLIT\x00") if p.strip()]
        out: list[str] = []
        for p in parts:
            sub = _split_by_uppercase_boundaries(p)
            out.extend(sub if len(sub) > 1 else [p])
        return out

    return _split_by_uppercase_boundaries(s)


def _split_by_uppercase_boundaries(s: str) -> list[str]:
    tokens = s.split()
    if len(tokens) <= 1:
        return [s]

    groups: list[list[str]] = [[tokens[0]]]
    for idx in range(1, len(tokens)):
        tok = tokens[idx]
        prev = groups[-1]
        starts_upper = bool(re.match(r"^[A-ZА-ЯІЇЄҐ«\"“0-9]", tok))
        is_num = tok[0].isdigit()
        if is_num:
            prev_l = prev[-1].lower().rstrip(",.;:")
            if (
                prev_l in {"в", "у", "на", "з", "із", "до", "від", "при", "через", "та", "і", "чи", "по", "-", "–", "тип", "типу", "№"}
                or prev[-1].endswith((",", "-", "–"))
            ):
                prev.append(tok)
            elif len(prev) >= 2 and prev[-1].isdigit() and prev[-2].lower() in {"та", "і", "-", "–"}:
                groups.append([tok])
            else:
                prev.append(tok)
            continue

        if starts_upper and _should_split_before_upper(prev, tokens[idx:]):
            if tok[0] in {"«", "\"", "“"}:
                prev.append(tok)
            else:
                groups.append([tok])
        else:
            prev.append(tok)

    return [" ".join(g).strip() for g in groups if g]


def _merge_option_continuations(raw_items: list[tuple[str, float]]) -> list[str]:
    """Merge wrapped lowercase/continuation option lines onto the preceding option."""
    merged: list[str] = []
    prev_x1 = 0.0
    for raw_txt, x1 in raw_items:
        txt = clean_display_text(raw_txt)
        if not txt:
            continue
        if merged:
            last = merged[-1]
            last_word = last.split()[-1].lower().rstrip(".,;:") if last.split() else ""
            # Only merge a lowercase continuation if previous line actually wrapped near margin
            # OR ended with an explicit grammatical connector (word-bounded!).
            has_connector = last.endswith((",", "-", "–", "—", "(")) or last_word in _LINKERS
            starts_cont = txt[0].islower() or txt.startswith(("(", "–", "—", ",", ")", "°"))
            # Exception: hyphenated suffix like "-Гімза"
            if txt.startswith("-") and len(txt) > 1:
                merged[-1] = f"{last}{txt}".strip()
                prev_x1 = max(prev_x1, x1)
                continue
            if starts_cont and (prev_x1 >= 410.0 or has_connector):
                merged[-1] = f"{last} {txt}".strip()
                prev_x1 = x1
                continue
        merged.append(txt)
        prev_x1 = x1
    return merged


def _resolve_options(option_lines: list[PdfLine], *, allow_glued_split: bool = True) -> list[str]:
    """Turn raw option PdfLines into normalized option strings."""
    if not option_lines:
        return []

    raw_items: list[tuple[str, float]] = []
    for ln in option_lines:
        frags = _split_line_by_large_gaps(ln, min_gap=22.0)
        if len(frags) == 1:
            raw_items.append((frags[0], ln.x1))
        else:
            for f in frags:
                raw_items.append((f, 0.0))

    merged = _merge_option_continuations(raw_items)
    if len(merged) == 5 or not allow_glued_split:
        return merged

    if len(merged) < 5:
        resplit: list[str] = []
        for item in merged:
            parts = split_glued_options_line(item)
            resplit.extend(parts)
        if len(resplit) == 5:
            return resplit
        if len(resplit) > 5:
            # Conservative pass: split only items that cleanly split without exceeding 5 total.
            conservative: list[str] = []
            for idx, item in enumerate(merged):
                rem = len(merged) - idx - 1
                p_list = split_glued_options_line(item)
                if len(conservative) + len(p_list) + rem <= 5:
                    conservative.extend(p_list)
                else:
                    conservative.append(item)
            if len(conservative) == 5:
                return conservative
        return resplit

    return merged


_IMPERATIVE_STEM_END_RE = re.compile(
    r"(?:^|[.!?]\s+)(?:Назвіть|Вкажіть|Визначте|Оберіть)\s+[^?!:]{5,110}\.?$",
    re.UNICODE,
)


def _is_stem_end_text(text: str) -> bool:
    return text.strip().endswith(("?", ":"))


def _is_imperative_stem_end(text: str, next_text: str) -> bool:
    t = clean_display_text(text)
    nt = clean_display_text(next_text)
    if not t or not nt:
        return False
    if nt[0].islower() or nt.startswith(("(", "–", "—", ",")):
        return False
    return bool(_IMPERATIVE_STEM_END_RE.search(t))


def _split_block_questions(lines: list[PdfLine]) -> list[list[PdfLine]]:
    """Split a block that may accidentally contain 2 questions (e.g. swallowed page-break)."""
    if len(lines) <= 5:
        return [lines]

    end_idxs = [
        i
        for i, l in enumerate(lines)
        if _is_stem_end_text(l.text)
        or (
            i + 1 < len(lines)
            and _is_imperative_stem_end(
                f"{lines[i - 1].text} {l.text}" if i > 0 else l.text,
                lines[i + 1].text,
            )
        )
    ]
    if len(end_idxs) < 2:
        for i, l in enumerate(lines):
            if l.text.strip() in {"-", "–"} and i >= 4 and i + 1 < len(lines) and len(lines[i + 1].text) > 30:
                return _split_block_questions(lines[: i + 1]) + _split_block_questions(lines[i + 1 :])
        return [lines]

    clusters: list[int] = [end_idxs[0]]
    for idx in end_idxs[1:]:
        between = lines[clusters[-1] + 1 : idx]
        resolved_between = _resolve_options(between, allow_glued_split=True) if between else []
        if (idx - clusters[-1] >= 2 and len(resolved_between) >= 5) or (idx - clusters[-1] >= 6):
            clusters.append(idx)
        else:
            clusters[-1] = idx

    if len(clusters) <= 1:
        return [lines]

    first_end = clusters[0]
    opt_start = first_end + 1
    second_end = clusters[1]
    split_at = None
    opts_acc: list[PdfLine] = []
    for k in range(opt_start, second_end):
        opts_acc.append(lines[k])
        resolved = _resolve_options(opts_acc, allow_glued_split=True)
        # Check if next line looks like a new stem start once we have 5 options.
        if len(resolved) >= 5 and k + 1 < second_end:
            nxt_txt = clean_display_text(lines[k + 1].text)
            if not nxt_txt[0].islower() and (len(nxt_txt) >= 30 or _NEW_STEM_OPENERS_RE.match(nxt_txt)):
                split_at = k + 1
                break
    if split_at is None:
        if second_end - opt_start >= 5:
            split_at = opt_start + 5
        else:
            return [lines]

    return _split_block_questions(lines[:split_at]) + _split_block_questions(lines[split_at:])


def _parse_single_module_block(
    blk: list[PdfLine],
    *,
    module_no: int,
    topic_title: str | None,
) -> ParsedQuestion | None:
    if not blk:
        return None

    stem_end_idx: int | None = None
    for i in range(len(blk) - 1, -1, -1):
        if _is_stem_end_text(blk[i].text) and i < len(blk) - 1:
            stem_end_idx = i
            break

    if stem_end_idx is None:
        # Handle stems without '?' or ':' (ending in '.', or bare imperative phrase).
        # Check from bottom: find minimum k trailing lines resolving to 5 options.
        for opt_lines_cnt in range(1, min(8, len(blk))):
            cand_opts = _resolve_options(blk[-opt_lines_cnt:], allow_glued_split=True)
            if len(cand_opts) == 5:
                cand_stem = blk[:-opt_lines_cnt]
                if cand_stem and any(len(l.text) > 25 for l in cand_stem):
                    stem_end_idx = len(blk) - opt_lines_cnt - 1
                    break
        if stem_end_idx is None and len(blk) >= 6:
            stem_end_idx = len(blk) - 6

    if stem_end_idx is None:
        stem_txt = clean_display_text(" ".join(l.text for l in blk))
        return ParsedQuestion(
            stem=stem_txt,
            options=[],
            topic_title=topic_title,
            module_no=module_no,
            status="needs_review",
            review_reason="stem_end_not_found",
            page=blk[0].page,
        )

    stem_txt = clean_display_text(" ".join(l.text for l in blk[: stem_end_idx + 1]))
    opt_lines = blk[stem_end_idx + 1 :]
    options = _resolve_options(opt_lines, allow_glued_split=True)

    return _validate_question(
        stem_txt,
        options,
        topic_title=topic_title,
        module_no=module_no,
        page=blk[0].page,
    )


_GLUED_STEM_RE = re.compile(
    r"(?:"
    r"(?:Назвіть|Вкажіть|Визначте|Оберіть)[^?.:]{3,75}\s+[А-ЯІЇЄҐA-Z][а-яіїєґa-z]+(?:\s+[А-ЯІЇЄҐA-Z][а-яіїєґa-z]+){2,}"
    r"|(?:Вкажіть|Назвіть|Визначте)\s+[^?!:]{10,80}\.\s+[A-ZА-ЯІЇЄҐ].{40,}[?:]$"
    r")",
    re.UNICODE,
)


def _validate_question(
    stem: str,
    options: list[str],
    *,
    topic_title: str | None,
    module_no: int,
    page: int,
) -> ParsedQuestion:
    stem = clean_display_text(stem)
    options = [clean_display_text(o) for o in options if clean_display_text(o)]

    reason = ""
    status = "verified"
    if len(stem) < 15:
        status = "needs_review"
        reason = f"short_stem({len(stem)})"
    elif len(options) != 5:
        status = "needs_review"
        reason = f"options_count={len(options)}"
    elif any(len(o) < 2 or o in {"-", "–", "—"} for o in options):
        status = "needs_review"
        reason = "invalid_option_placeholder"
    elif any("?" in o or len(o) > 220 or re.search(r"\b[A-E]\s*\*", o) for o in options):
        status = "needs_review"
        reason = "glued_option"
    elif _GLUED_STEM_RE.search(stem):
        status = "needs_review"
        reason = "glued_stem"

    return ParsedQuestion(
        stem=stem,
        options=options,
        correct_idx=0,
        topic_title=topic_title,
        module_no=module_no,
        status=status,
        review_reason=reason,
        page=page,
    )


def parse_module_pdf(pdf_path: Path, default_module_no: int = 1) -> list[ParsedQuestion]:
    """Parse structured module-by-module KROK-1 PDF using fonts and Y-coordinates."""
    lines = extract_lines_pdfplumber(pdf_path)
    cur_module = default_module_no
    cur_topic: str | None = None
    seen_topics: dict[tuple[int, str], str] = {}

    raw_blocks: list[tuple[int, str | None, list[PdfLine]]] = []
    cur_blk: list[PdfLine] = []

    i = 0
    while i < len(lines):
        ln = lines[i]
        txt = clean_display_text(ln.text)

        if ln.is_bold:
            if cur_blk:
                raw_blocks.append((cur_module, cur_topic, cur_blk))
                cur_blk = []

            mod_m = _MODULE_HDR_RE.match(txt)
            if mod_m:
                cur_module = int(mod_m.group(1))
                i += 1
                while i < len(lines) and lines[i].is_bold and (lines[i].size >= 13.0 or lines[i].x0 > 100):
                    i += 1
                continue

            if "Тестовий комп’ютерний контроль" in txt or "Тестовий комп'ютерний контроль" in txt:
                title = txt.rstrip("*").strip()
                while i + 1 < len(lines) and lines[i + 1].is_bold and (lines[i + 1].dy or 0) < 30:
                    i += 1
                    title += " " + clean_display_text(lines[i].text).rstrip("*")
                cur_topic = clean_display_text(title)
                i += 1
                continue

            topic_m = _TOPIC_HDR_RE.match(txt)
            if topic_m or ln.x0 < 100:
                title_parts = [txt]
                while (
                    i + 1 < len(lines)
                    and lines[i + 1].is_bold
                    and not _MODULE_HDR_RE.match(clean_display_text(lines[i + 1].text))
                    and (lines[i + 1].dy is None or lines[i + 1].dy < 30)
                    and not lines[i + 1].first_on_page
                ):
                    i += 1
                    title_parts.append(clean_display_text(lines[i].text))
                joined = clean_display_text(" ".join(title_parts))
                tm = _TOPIC_HDR_RE.match(joined)
                if tm:
                    num = int(tm.group(1))
                    body = tm.group(2).strip().rstrip("*").strip()
                    key = (cur_module, body.lower())
                    if key in seen_topics:
                        cur_topic = seen_topics[key]
                    else:
                        canonical = f"{num}. {body}"
                        seen_topics[key] = canonical
                        cur_topic = canonical
                else:
                    cur_topic = joined
                i += 1
                continue

        is_blank_break = (ln.dy is not None and ln.dy > 30.0) or (ln.first_on_page and ln.y0 >= 58.0)
        if is_blank_break and cur_blk:
            raw_blocks.append((cur_module, cur_topic, cur_blk))
            cur_blk = []

        cur_blk.append(ln)
        i += 1

    if cur_blk:
        raw_blocks.append((cur_module, cur_topic, cur_blk))

    # Merge orphan stem-only block followed by an option-only block (e.g. Virology p6).
    merged_blocks: list[tuple[int, str | None, list[PdfLine]]] = []
    idx = 0
    while idx < len(raw_blocks):
        mod, top, blk = raw_blocks[idx]
        if idx + 1 < len(raw_blocks):
            _, _, nxt = raw_blocks[idx + 1]
            blk_has_end = _is_stem_end_text(blk[-1].text)
            nxt_has_end = any(_is_stem_end_text(l.text) for l in nxt)
            if blk_has_end and len(blk) <= 5 and not nxt_has_end and len(nxt) <= 7:
                merged_blocks.append((mod, top, blk + nxt))
                idx += 2
                continue
        merged_blocks.append((mod, top, blk))
        idx += 1

    questions: list[ParsedQuestion] = []
    for mod, top, blk in merged_blocks:
        for sub_blk in _split_block_questions(blk):
            q = _parse_single_module_block(sub_blk, module_no=mod, topic_title=top)
            if q is not None:
                questions.append(q)
    return questions


def _looks_like_option_candidate(ln: PdfLine) -> bool:
    t = clean_display_text(ln.text)
    if not t:
        return False
    if ln.x0 >= 85.0:
        return True
    if _is_stem_end_text(t):
        return False
    if len(split_glued_options_line(t)) >= 2:
        return True
    if ln.x1 < 470.0 and not _NEW_STEM_OPENERS_RE.match(t):
        return True
    return False


def parse_dense_kkr_pdf(
    pdf_path: Path,
    default_module_no: int = 4,
    default_topic: str = "ККР · Додаткові завдання",
    *,
    extractor: str = "pdfplumber",
) -> list[ParsedQuestion]:
    """Parse dense KKR.pdf where blank lines are absent and short options may be glued."""
    lines = (
        extract_lines_bbox(pdf_path)
        if extractor == "bbox"
        else extract_lines_pdfplumber(pdf_path)
    )
    filtered: list[PdfLine] = []
    for ln in lines:
        txt = clean_display_text(ln.text)
        if ln.page == 1 and ln.y0 < 55.0 and "ККР" in txt.upper():
            continue
        filtered.append(ln)

    questions: list[ParsedQuestion] = []
    state = "STEM"
    stem_lines: list[PdfLine] = []
    opt_lines: list[PdfLine] = []

    def _flush() -> None:
        nonlocal stem_lines, opt_lines
        if not stem_lines and not opt_lines:
            return
        stem_txt = clean_display_text(" ".join(l.text for l in stem_lines))
        options = _resolve_options(opt_lines, allow_glued_split=True)
        questions.append(
            _validate_question(
                stem_txt,
                options,
                topic_title=default_topic,
                module_no=default_module_no,
                page=stem_lines[0].page if stem_lines else opt_lines[0].page,
            )
        )
        stem_lines = []
        opt_lines = []

    n = len(filtered)
    for i, ln in enumerate(filtered):
        txt = clean_display_text(ln.text)
        nxt = filtered[i + 1] if i + 1 < n else None
        nxt_txt = clean_display_text(nxt.text) if nxt is not None else ""

        if state == "STEM":
            stem_lines.append(ln)
            ends_q_or_colon = _is_stem_end_text(txt)
            is_imp_end = nxt is not None and _is_imperative_stem_end(txt, nxt_txt)
            next_is_indented = (
                nxt is not None
                and nxt.x0 >= 85.0
                and ln.x0 < 80.0
                and bool(nxt_txt)
                and not nxt_txt[0].islower()
                and not nxt_txt.startswith(("(", "–", "—", ","))
            )
            has_nearby_qend = False
            for j in range(i + 1, min(i + 4, n)):
                if _is_stem_end_text(filtered[j].text):
                    has_nearby_qend = True
                    break
                if filtered[j].x0 >= 85.0:
                    break

            if ends_q_or_colon or is_imp_end:
                if txt.endswith(":") and not is_imp_end and has_nearby_qend:
                    if nxt is not None and (nxt.x1 >= 430.0 or _is_stem_end_text(nxt.text)):
                        continue
                state = "OPTIONS"
            elif next_is_indented:
                state = "OPTIONS"
            elif (
                not has_nearby_qend
                and len(stem_lines) >= 2
                and (ln.x1 < 460.0 or (ln.x1 < 515.0 and txt.endswith(".")))
                and nxt is not None
                and not nxt_txt[0].islower()
                and _looks_like_option_candidate(nxt)
            ):
                state = "OPTIONS"
            continue

        # state == "OPTIONS"
        if opt_lines:
            cur_opts = _resolve_options(opt_lines, allow_glued_split=True)
            is_lowercase_cont = txt[0].islower() or txt.startswith(("(", "–", "—", ",", "-"))

            prev_indented = opt_lines[-1].x0 >= 85.0
            if prev_indented and ln.x0 < 78.0 and not is_lowercase_cont:
                if not (nxt is not None and nxt.x0 >= 85.0 and ln.x1 < 300.0):
                    _flush()
                    state = "STEM"
                    stem_lines.append(ln)
                    if _is_stem_end_text(txt):
                        state = "OPTIONS"
                    continue

            if len(cur_opts) >= 5 and not is_lowercase_cont:
                if not (ln.x0 >= 85.0 and opt_lines[-1].x0 >= 85.0):
                    _flush()
                    state = "STEM"
                    stem_lines.append(ln)
                    if _is_stem_end_text(txt):
                        state = "OPTIONS"
                    continue

            # Clear full-width clinical vignette opener always starts a new stem (unless line itself is glued options).
            if (
                not is_lowercase_cont
                and ln.x1 >= 490.0
                and _NEW_STEM_OPENERS_RE.match(txt)
                and (len(cur_opts) >= 5 or len(split_glued_options_line(txt)) == 1)
            ):
                _flush()
                state = "STEM"
                stem_lines.append(ln)
                if _is_stem_end_text(txt):
                    state = "OPTIONS"
                continue

            # Explicit question-mark / colon line inside OPTIONS (when previous Q had <5 parsed options).
            if not is_lowercase_cont and _is_stem_end_text(txt) and len(txt) >= 35:
                _flush()
                state = "STEM"
                stem_lines.append(ln)
                state = "OPTIONS"
                continue

        opt_lines.append(ln)

    _flush()
    return questions


def import_questions(
    questions: list[ParsedQuestion],
    *,
    subject_slug: str,
    subject_title: str,
    subject_icon: str,
    source_tag: str,
    file_name: str,
    module_no_default: int,
    db_path: Path | str | None = None,
) -> ImportStats:
    """Insert or deduplicate parsed questions into SQLite database."""
    init_db(db_path)
    stats = ImportStats(
        file_name=file_name,
        module_no=module_no_default,
        source_tag=source_tag,
        total_parsed=len(questions),
    )
    now_ts = int(time.time())

    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO subjects (slug, title_uk, sort_order, icon)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(slug) DO UPDATE SET title_uk = excluded.title_uk, icon = excluded.icon
            """,
            (subject_slug, subject_title, subject_icon),
        )
        cur.execute("SELECT id FROM subjects WHERE slug = ?", (subject_slug,))
        subject_id = int(cur.fetchone()["id"])

        topic_cache: dict[tuple[int, str], int] = {}
        cur.execute("SELECT id, module_no, title_uk FROM topics WHERE subject_id = ?", (subject_id,))
        for row in cur.fetchall():
            topic_cache[(int(row["module_no"]), row["title_uk"])] = int(row["id"])

        next_topic_sort = len(topic_cache) + 1

        def _get_topic_id(mod_no: int, title: str | None) -> int | None:
            nonlocal next_topic_sort
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
                (subject_id, mod_no, title, next_topic_sort),
            )
            cur.execute(
                "SELECT id FROM topics WHERE subject_id = ? AND module_no = ? AND title_uk = ?",
                (subject_id, mod_no, title),
            )
            tid = int(cur.fetchone()["id"])
            topic_cache[key] = tid
            next_topic_sort += 1
            return tid

        for q in questions:
            nhash = compute_norm_hash(q.stem)
            cur.execute(
                "SELECT id, source_tags, status, topic_id FROM questions WHERE norm_hash = ?",
                (nhash,),
            )
            existing = cur.fetchone()
            if existing is not None:
                stats.duplicates_merged += 1
                tags = json.loads(existing["source_tags"])
                if source_tag not in tags:
                    tags.append(source_tag)
                new_status = existing["status"]
                new_options_json = None
                if existing["status"] == "needs_review" and q.status == "verified":
                    new_status = "verified"
                    new_options_json = json.dumps(q.options, ensure_ascii=False)
                    stats.upgraded_from_review += 1
                    stats.verified += 1
                if new_options_json is not None:
                    cur.execute(
                        """
                        UPDATE questions
                        SET source_tags = ?, status = ?, options_json = ?, stem = ?
                        WHERE id = ?
                        """,
                        (
                            json.dumps(tags, ensure_ascii=False),
                            new_status,
                            new_options_json,
                            q.stem,
                            existing["id"],
                        ),
                    )
                else:
                    cur.execute(
                        "UPDATE questions SET source_tags = ? WHERE id = ?",
                        (json.dumps(tags, ensure_ascii=False), existing["id"]),
                    )
                continue

            topic_id = _get_topic_id(q.module_no, q.topic_title)
            opts_json = json.dumps(q.options, ensure_ascii=False)
            tags_json = json.dumps([source_tag], ensure_ascii=False)
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
                    opts_json,
                    q.correct_idx,
                    tags_json,
                    q.status,
                    now_ts,
                ),
            )
            stats.inserted += 1
            if q.status == "verified":
                stats.verified += 1
                if len(stats.sample_questions) < 3:
                    stats.sample_questions.append({
                        "stem": q.stem,
                        "options": q.options,
                        "topic": q.topic_title,
                        "page": q.page,
                    })
            else:
                stats.needs_review += 1
                stats.review_items.append({
                    "page": q.page,
                    "reason": q.review_reason,
                    "stem": q.stem[:140],
                    "options": q.options,
                })

        conn.commit()
    return stats


def parse_catdoc_doc(doc_path: Path, *, default_module_no: int = 5) -> list[ParsedQuestion]:
    """Extract questions from a legacy .doc file via catdoc (UTF-8), honoring '*' correct markers."""
    proc = subprocess.run(
        ["catdoc", "-d", "utf-8", str(doc_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    text = proc.stdout.replace("\t", "   ")
    text = re.sub(r"[ ]{2,}(?=[A-EАВСДЕ](?:\s*[-–—.]\s*|\s{2,})\*?)", "\n", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    opt_letters = [("A", "А"), ("B", "В"), ("C", "С"), ("D", "Д"), ("E", "Е")]
    opt_re = re.compile(
        r"^\s*(?:([A-E])(?:\s*[-–—.)]\s*|\s+(?=[А-ЯІЇЄҐA-Z0-9*]))|([АВСДЕ])(?:\s*[-–—.)]\s*|\s{2,}(?=[А-ЯІЇЄҐA-Z0-9*])))(.+)$"
    )
    q_start_re = re.compile(
        r"^\s*(?:№\s*\d+\.?|\d{1,3}\.|\d{1,2}\s+(?=[А-ЯІЇЄҐA-Z]))(?:\s*(.*))?$"
    )
    theme_re = re.compile(r"^\s*Тема\s*№\s*(\d+)\s*$", re.I)
    skip_re = re.compile(r"^(?:Базов[іи]\s+тести|Крок\s+\d+(?:-\d+)?|Тести\s+Крок.*)$", re.I)

    raw_items: list[tuple[str, str, list[str]]] = []
    cur_theme = "Тести з мікробіології (.doc)"
    cur_stem: list[str] = []
    cur_opts: list[str] = []
    collecting_theme = False
    theme_parts: list[str] = []

    def _clean_theme_title(parts: list[str]) -> str:
        prefix = parts[0].strip()
        rest = sanitize_text_encoding(" ".join(parts[1:]).strip())
        # Strip leading symbol-font ASCII/UTF garbage before first genuine Ukrainian title word.
        m_real = re.search(r"[А-ЯІЇЄҐ][а-яіїєґ]{2,}", rest)
        if not m_real:
            return prefix.rstrip(".")
        cleaned_rest = re.sub(r"\s{2,}", " ", rest[m_real.start() :]).strip()
        return f"{prefix} {cleaned_rest}".strip()

    def _flush() -> None:
        nonlocal cur_stem, cur_opts
        if cur_stem or cur_opts:
            raw_items.append((cur_theme, " ".join(cur_stem).strip(), cur_opts))
        cur_stem = []
        cur_opts = []

    for line in lines:
        m_th = theme_re.match(line)
        if m_th:
            _flush()
            collecting_theme = True
            theme_parts = [f"Тема {m_th.group(1)}."]
            continue
        if skip_re.match(line):
            if collecting_theme and len(theme_parts) > 1:
                cur_theme = _clean_theme_title(theme_parts)
                collecting_theme = False
            _flush()
            continue

        m_opt = opt_re.match(line)
        if m_opt and (cur_stem or cur_opts):
            letter = m_opt.group(1) or m_opt.group(2)
            body = m_opt.group(3).strip()
            idx = len(cur_opts)
            # Only treat line as Option N if its letter matches sequence A..E so "E. coli" in stem stays stem.
            if idx < 5 and letter in opt_letters[idx]:
                collecting_theme = False
                cur_opts.append(body)
                continue

        m_q = q_start_re.match(line)
        if m_q and (not cur_opts or len(cur_opts) >= 4):
            if collecting_theme and len(theme_parts) > 1:
                cur_theme = _clean_theme_title(theme_parts)
                collecting_theme = False
            _flush()
            tail = (m_q.group(1) or "").strip()
            if tail:
                cur_stem.append(tail)
            continue

        if cur_opts:
            cur_opts[-1] = f"{cur_opts[-1]} {line}".strip()
            continue

        if collecting_theme:
            theme_parts.append(line)
        else:
            cur_stem.append(line)

    _flush()

    parsed: list[ParsedQuestion] = []
    for idx_q, (topic_title, stem_raw, opts_raw) in enumerate(raw_items, start=1):
        stem = sanitize_text_encoding(re.sub(r"\s+", " ", stem_raw).strip())
        stem = re.sub(r"^\d{1,3}\s+(?=[А-ЯІЇЄҐA-Z])", "", stem)
        if len(stem) < 12:
            continue
        starred = [i for i, o in enumerate(opts_raw) if "*" in o[:3]]
        clean_opts = [
            sanitize_text_encoding(re.sub(r"\s+", " ", re.sub(r"^\s*\*\s*", "", o).rstrip(";")).strip())
            for o in opts_raw
        ]
        clean_opts = [o for o in clean_opts if o]

        has_glued_opt = any("?" in o or len(o) > 220 or re.search(r"\b[A-E]\s*\*", o) for o in clean_opts)
        if len(clean_opts) == 5 and len(starred) == 1 and not has_glued_opt:
            star_i = starred[0]
            reordered = [clean_opts[star_i]] + [o for j, o in enumerate(clean_opts) if j != star_i]
            parsed.append(
                ParsedQuestion(
                    stem=stem,
                    options=reordered,
                    topic_title=topic_title,
                    module_no=default_module_no,
                    page=idx_q,
                    status="verified",
                    correct_idx=0,
                )
            )
        else:
            reason = f"options_count={len(clean_opts)};stars={len(starred)}"
            parsed.append(
                ParsedQuestion(
                    stem=stem,
                    options=clean_opts,
                    topic_title=topic_title,
                    module_no=default_module_no,
                    page=idx_q,
                    status="needs_review",
                    review_reason=reason,
                    correct_idx=0,
                )
            )
    return parsed


def import_doc_file(
    doc_path: Path,
    *,
    module_no: int = 5,
    source_tag: str = "Тести з мікробіології",
    subject_slug: str = "microbiology",
    subject_title: str = "Мікробіологія",
    subject_icon: str = "🧬",
    db_path: Path | str | None = None,
) -> ImportStats:
    """Parse a legacy .doc file via catdoc and import its questions into SQLite."""
    parsed = parse_catdoc_doc(doc_path, default_module_no=module_no)
    return import_questions(
        parsed,
        subject_slug=subject_slug,
        subject_title=subject_title,
        subject_icon=subject_icon,
        source_tag=source_tag,
        file_name=doc_path.name,
        module_no_default=module_no,
        db_path=db_path,
    )


def import_pdf_file(
    pdf_path: Path,
    *,
    mode: str,
    module_no: int,
    source_tag: str,
    subject_slug: str = "microbiology",
    subject_title: str = "Мікробіологія",
    subject_icon: str = "🧬",
    db_path: Path | str | None = None,
) -> ImportStats:
    """Parse a PDF file and import its questions into SQLite."""
    if mode == "module":
        parsed = parse_module_pdf(pdf_path, default_module_no=module_no)
    elif mode == "kkr":
        parsed = parse_dense_kkr_pdf(pdf_path, default_module_no=module_no)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    return import_questions(
        parsed,
        subject_slug=subject_slug,
        subject_title=subject_title,
        subject_icon=subject_icon,
        source_tag=source_tag,
        file_name=pdf_path.name,
        module_no_default=module_no,
        db_path=db_path,
    )


DEFAULT_INBOX_MANIFEST = [
    ("База тестових завдань КРОК 1. Загальна мікробіологія.pdf", "module", 1, "Загальна мікробіологія"),
    ("База тестових завдань КРОК 1. Вірусологія.pdf", "module", 2, "Вірусологія"),
    ("База тестових завдань КРОК 1. Спеціальна бактеріологія.pdf", "module", 3, "Спеціальна бактеріологія"),
    ("ККР.pdf", "kkr", 4, "ККР"),
]


def import_default_inbox(
    inbox_dir: Path = Path("inbox"),
    db_path: Path | str | None = None,
) -> list[ImportStats]:
    """Import all 4 canonical Microbiology + KKR PDFs in deterministic order."""
    all_stats: list[ImportStats] = []
    for filename, mode, module_no, tag in DEFAULT_INBOX_MANIFEST:
        path = inbox_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing PDF: {path}")
        st = import_pdf_file(
            path,
            mode=mode,
            module_no=module_no,
            source_tag=tag,
            db_path=db_path,
        )
        all_stats.append(st)
    return all_stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KROK Trainer positional PDF importer")
    parser.add_argument("--inbox", type=Path, default=Path("inbox"))
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--reset-db", action="store_true", help="Delete existing DB before importing")
    args = parser.parse_args(argv)

    if args.reset_db and args.db is not None and args.db.exists():
        args.db.unlink()
    elif args.reset_db and args.db is None:
        from app.config import get_settings
        p = get_settings().db_path
        if p.exists():
            p.unlink()
        for suf in ("-wal", "-shm"):
            side = Path(f"{p}{suf}")
            if side.exists():
                side.unlink()

    all_stats = import_default_inbox(args.inbox, db_path=args.db)
    for st in all_stats:
        print(
            f"[{st.file_name}] parsed={st.total_parsed} inserted={st.inserted} "
            f"verified={st.verified} needs_review={st.needs_review} "
            f"dups_merged={st.duplicates_merged} upgraded={st.upgraded_from_review}"
        )
        for rev in st.review_items:
            print(f"  REVIEW p{rev['page']} ({rev['reason']}): {rev['stem']} | opts={rev['options']}")
        for smp in st.sample_questions[:1]:
            print(f"  SAMPLE p{smp['page']} [{smp['topic']}]: {smp['stem'][:95]}... -> {smp['options'][0]}")

    with db_session(args.db, read_only=True) as conn:
        tot = conn.execute("SELECT status, COUNT(*) AS cnt FROM questions GROUP BY status").fetchall()
        print("DB totals:", {r["status"]: r["cnt"] for r in tot})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
