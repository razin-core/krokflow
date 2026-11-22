"""Cached KROK clinical markers, anchor formulas, and quota-protected Gemini Flash explanations."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, status

from app.config import get_settings
from app.schemas import ExplanationOut, UserOut

# Curated high-yield clinical/diagnostic triggers for deterministic AMBOSS-style marker extraction.
# Every matched trigger is validated as an exact verbatim substring of the question stem.
_TRIGGER_PATTERNS: list[str] = [
    # Microscopy & stains
    r"темнопольн[аоіїу]\w*\s+мікроскопі[яюї]",
    r"фазово-контрастн\w+\s+мікроскопі[яюї]",
    r"люмінесцентн\w+\s+мікроскоп\w*",
    r"електронн\w+\s+мікроскопі[яюї]",
    r"імерсійн\w+\s+мікроскопі?[яюї]?",
    r"імерсійн\w+\s+масло",
    r"висяча\s+крапля",
    r"за\s+(?:методом\s+)?ціл[яь]-?нільсен\w*",
    r"за\s+(?:методом\s+)?нейс+ер\w*",
    r"за\s+(?:методом\s+)?леффлер\w*",
    r"за\s+(?:методом\s+)?буррі-?гінс\w*",
    r"за\s+(?:методом\s+)?гінсом-?буррі",
    r"за\s+(?:методом\s+)?ожешк\w*",
    r"за\s+(?:методом\s+)?романовськ\w*-?гімз\w*",
    r"за\s+(?:методом\s+)?грам\w*",
    r"методом\s+здродовськ\w*",
    # Morphology & bodies
    r"тільц[яі]\s+бабеша-?негрі",
    r"тільц[яі]\s+бабеша-?ернста",
    r"тільц[яі]\s+гварнієрі",
    r"тільц[яі]\s+пашена",
    r"тільц[яі]\s+люпшютца",
    r"зерн\w+\s+волютину",
    r"гроно\s+винограду|грона\s+винограду",
    r"у\s+вигляді\s+ланцюжк\w+",
    r"у\s+вигляді\s+паличок|під\s+кутом\s+одна\s+до\s+одної",
    r"барабанн\w+\s+паличк\w+",
    r"тенісн\w+\s+ракетк\w+",
    r"бобопод[іi]бн\w+\s+диплокок\w*",
    r"біполярн\w+\s+забарвленн\w+",
    r"овоїдн\w+\s+форм\w+",
    r"бруньк\w+\s+(?:клітин|нитк)\w*",
    r"друз[иі]",
    r"спороутворююч\w+",
    r"кислотостійк\w+",
    r"ундулююч\w+\s+мембран\w+",
    r"чотир\w+\s+ядрами|4\s+ядрами",
    r"синциті[йю]",
    r"плазмокоагулаз\w+",
    r"гіалуронідаз\w+",
    r"уреазн?\w*",
    r"лецитиназ\w*",
    r"ліпополісахарид\w*|лпс|ендотоксин\w*",
    r"екзотоксин\w*",
    r"цитопатичн\w+\s+ді[яюї]",
    # Culture media & sterilization
    r"жовточно-сольов\w+\s+агар\w*|жса|молочно-сольов\w+",
    r"кров['’]?яно-?телуритов\w+\s+агар\w*|телурітов\w+",
    r"середовищ[еі]\s+ендо|агар\w*\s+ендо",
    r"середовищ[еі]\s+левіна",
    r"середовищ[еі]\s+плоскірєва",
    r"середовищ[еі]\s+сабуро",
    r"середовищ[еі]\s+кітт?а-?тароц+і",
    r"середовищ[еі]\s+левенштейн\w*-?йєнсен\w*",
    r"середовищ[еі]\s+вільсона-?блера",
    r"лужний\s+агар|лужна\s+пептонна\s+вода",
    r"шоколадн\w+\s+агар\w*",
    r"кров['’]?яному?\s+агар\w*|зоною\s+гемолізу|зона\s+гемолізу",
    r"середовищ[еі]\s+ігла",
    r"синьо-?зелен\w+\s+пігмент\w*|жовто-?зелен\w+\s+пігмент\w*|запах\w*\s+жасмину",
    r"апарат\w*\s+кротова|седиментаційн\w+\s+метод\w*",
    r"автоклавуванн\w*|автоклав\w*|тиском\s+в\s+автоклав\w*",
    r"сухим\s+жаром|піч\s+пастера",
    r"тиндалізаці\w*|дрібно\s+текучою\s+парою",
    # Serology & immunity
    r"реакці[яюєї]\s+вассермана",
    r"реакці[яюєї]\s+відаля",
    r"реакці[яюєї]\s+райта|хедльсона",
    r"реакці[яюєї]\s+асколі|термопреципітації",
    r"реакці[яюєї]\s+зв['’]?язування\s+комплементу|рзк",
    r"реакці[яюєї]\s+імунофлю?оресценції|ріф",
    r"реакці[яюєї]\s+гемадсорбці\w*",
    r"реакці[яюєї]\s+(?:затримки|гальмування)\s+гемаглютинаці\w*|ртга|ргга",
    r"реакці[яюєї]\s+(?:непрямої|пасивної)\s+гемаглютинаці\w*|рпга|рнга",
    r"реакці[яюєї]\s+преципітаці\w+\s+в\s+гел\w*",
    r"реакці[яюєї]\s+нейтралізаці\w*",
    r"імуноферментн\w+\s+аналіз\w*|іфа",
    r"полімеразна\s+ланцюгова\s+реакці\w*|плр",
    r"кольоров\w+\s+проб\w*",
    r"проб[ауи]\s+манту",
    r"реакці[яюєї]\s+шика|діка|бюрне",
    r"імуноглобулін\w*\s+(?:класу\s+)?[mgdaeмгдае]|[iі]g[mgdaeмгдае]|анти[hн][bв]s[iі]g[mgdaeмгдае]",
    r"т-?лімфоцит\w*|в-?лімфоцит\w*|плазматичн\w+\s+клітин\w*",
    r"недостатніст\w+\s+комплементу|еритроцит\w*\s+барана",
    r"гемолітичн\w+\s+сироватк\w*",
    r"австралійськ\w+\s+антиген\w*|[hн][bв]s-?ag|[hн][bв]sag|[hн][bв]eag|[hн]cag",
    r"gp\s*120|gp\s*41|cd\s*4",
    r"зворотн\w+\s+транскриптаз\w*",
    r"анатоксин\w*|антитоксичн\w+\s+сироватк\w*",
    r"бактеріофаг\w*|фаготипуванн\w*|фагова\s+конверсія",
    r"парні\s+сироватки|наростання\s+титру",
    # Pathogens & clinical signatures
    r"тверд\w+\s+шанкер\w*|шанкер\w*",
    r"t\.\s*pallidum|трепонем\w*",
    r"ригідність\s+м['’]?язів\s+потилиці|менінгеальн\w+",
    r"сірі\s+плівки|сіруват\w+\s+плівк\w*|кровотеч\w+",
    r"малиново-?червон\w+\s+язик|носогубн\w+\s+трикутник\w*",
    r"рисового\s+відвару|діарея|водянист\w+\s+випорожнен\w*",
    r"м['’]?ясн\w+\s+консерв\w*|в['’]?ялена\s+риба|двоїння\s+в\s+очах|порушення\s+ковтання",
    r"колот\w+\s+ран\w*|правець|тризм",
    r"укус\w*\s+(?:собаки|лисиці|кліща|москіт\w*)|козине\s+молоко",
    r"висип\w*\s+на\s+слизов\w+\s+щ[іi]к|плями\s+філатова|молоко,\s+що\s+скипілося",
    r"болісн\w+\s+виразк\w*\s+на\s+слизовій\s+оболонці\s+губ",
    r"оперізувальн\w+\s+характер\w*",
    r"гепатоспленомегалі\w*|атипов\w+\s+мононуклеар\w*",
    r"гнійн\w+\s+виділен\w*|уретрит|бленоре\w*",
    r"виразк\w+\s+шлунка|хелікобактер\w*",
    r"колоті|сироватков\w+\s+хвороб\w*|анафілактичн\w+",
    r"нефіксованому\s+препараті",
    r"некип['’]?ячене\s+козине\s+молоко",
    r"куряч\w+\s+ембріон\w*",
    r"миш\w*-?сосунк\w*|мишат-?сисунк\w*",
    r"колі-?індекс|колі-?титр|мікробне\s+число",
    r"недоношен\w*|новонароджен\w*|трансплацентарн\w*|на\s+2-му\s+місяці\s+вагітності",
    r"дифузн\w+\s+гломерулонефрит\w*|ревматичн\w+\s+ураженн\w+",
    r"гемолітичн\w+",
    r"анаероб\w+",
    r"випорожнен\w+|фекалі\w+|харкотинн\w+|мокротинн\w+|ранов\w+\s+вміст\w*",
    r"виділен\w+\s+чист\w+\s+культур\w+|чист\w+\s+культур\w+",
    r"ідентифікаці\w+",
    r"серологічн\w+\s+реакці\w*",
    r"біоптат\w*|мазк\w*\s+(?:із|з)\s+(?:зіва|мигдаликів|носоглотки|нальоту)",
    r"імерсійн\w+\s+мікроскоп\w*",
    r"(?:за|по)\s+(?:методом\s+)?(?:нейс+ер|ціл[яь]-?нільсен|леффлер|буррі|гінсом|ожешк|романовськ|грам)\w*",
    r"синьо-?зелен\w+\s+(?:пігмент|кольор)\w*|перламутров\w+\s+відтінк\w*",
    r"запах\w*\s+(?:фіалок\s+або\s+)?жасмину",
    r"грам(?:позитивн|негативн)\w+\s+(?:кок|паличк|диплокок)\w*",
    r"паличк\w*\s+синього\s+кольору|жовті\s+палички\s+з\s+синіми\s+зернами|потовщеннями\s+на\s+полюсах",
    r"[“\"«]?грон[оа][”\"»]?\s+винограду|брунькуються",
    r"ніжн\w+\s+плівк\w*|1%\s+пептон\w*\s+вод\w*",
    r"рибн\w+\s+консерв\w*|водн\w+\s+фактор\w*|донорськ\w+\s+шкір\w*|відторгатися",
    r"шкірн\w+\s+алергічн\w+\s+проб\w*|реакці\w+\s+преципітації\s+(?:по\s+)?асколі",
    r"титр\w*\s+антитіл|О-?антиген\w+|Н-?антиген\w+|HBs-?антиген\w+",
    r"через\s+10\s+днів\s+після\s+введення\s+антитоксичної",
    r"туберкульоз\w*|дифтері\w*|черевн\w+\s+тиф\w*|поворотн\w+\s+тиф\w*|тифо-?паратифозн\w*|холер\w*|дизентері\w*|шигельоз\w*|бруцельоз\w*",
    r"сибірк\w+|сибірськ\w+\s+виразк\w*|підозрілим\s+порошком|худобомогильник\w*|карбункул\w*",
    r"епідемічн\w+\s+паротит\w*|туляремі\w*|ондатр\w*|менінгокок\w*|ботулізм\w*|саркома\s+капоші|рак\s+шийки\s+матки",
    r"ротавірус\w*|мононуклеоз\w*|енцефаліт\w*|опортуністичн\w+\s+інфекці\w*|мікоплазм\w*|Mycoplasmatacea\w*",
    r"загибель\s+щурів|чум[аиіу]|укус\w*\s+(?:.*?\s+)?лисиц\w*|по\s+ходу\s+міжреберних\s+нервів|пухірцев\w+\s+висипк\w+",
    r"фагопрофілактик\w*|фібринозн\w+\s+коліт\w*|спастичн\w+\s+кашл\w+|демінералізації\s+емалі",
    r"мікробн\w+\s+числ\w+\s+повітря|1500\s+клітин|мутантних\s+клітин|вживання\s+морепродуктів",
    r"повторного\s+введення\s+антигену|недостатня\s+кількість\s+імуноглобулінів|індикації\s+вірусів\s+в\s+культурі\s+клітин",
    r"газов\w+\s+гангрен\w*|малярі\w*|актиноміцет\w*|сальмонел\w*|ГРВІ",
    r"копрологічн\w+\s+досліджен\w*|округл\w+\s+цист\w*|білим\s+нальотом|гнійн\w+\s+вміст\w*",
    r"мембранн\w+\s+органел\w*|нуклеосомн\w+\s+організаці\w*|термостабільн\w+\s+білок\w*",
    r"бензилпеніцилін\w*|пеніцилін\w*|антигістамінн\w+\s+препарат\w*|ендемічн\w+\s+вогнищ\w*",
    r"гепатит\w*\s+[A-EА-Е]|цитомегаловірусн\w*|поліомієліт\w*|гострий\s+герпес|кору|кір",
    r"середовищ\w+\s+[А-ЯІЇЄҐA-Z]{2,}|групи\s+кишкових\s+паличок",
    r"Shigella\s+\w+|Salmonella\s+\w+|Escherichia\s+coli|Vibrio\s+cholerae|S\.\s*(?:typhi|aureus|pyogenes)",
    r"Corynebacterium\s+\w+|Mycobacterium\s+\w+|Staphylococcus\s+\w+|Streptococcus\s+\w+",
    r"Clostridium\s+\w+|Neisseria\s+\w+|Helicobacter\s+pylori|Bordetella\s+\w+",
    r"Brucella\s+\w+|Yersinia\s+\w+|Treponema\s+\w+|Rickettsia\s+\w+|Chlamydia\s+\w+|P\.\s*aeruginosa",
    r"антибіотикогра\w*|метод\w*\s+паперових\s+дисків|серійних\s+розведень",
    r"кон['’]?югаці[яюєї]|трансдукці\w*|трансформаці\w*|плазміди",
]

_FALLBACK_PATTERNS: list[str] = [
    r"[A-Z][a-z]{2,}\s+[a-z]{3,}",
    r"(?:грампозитивн|грамнегативн|кислотостійк|умовно-?патогенн|імуносупресивн|імунокомпетентн)\w+",
    r"(?:бактеріоскопічн|бактеріологічн|серологічн|вірусологічн|біологічн|алергологічн)\w+\s+\w+",
    r"(?:гемаглютинін|нейрамінідаз|комплемент|антигенпрезентаці|фагоцитоз|лізоцим|інтерферон|анатоксин|ендотоксин|екзотоксин)\w*",
    r"(?:поліомієліт|грипу|снід\w*|віл-?інфекці|стафілокок|стрептокок|пневмокок|менінгіт|гоноре|кандидоз|актиномікоз|піодермі|кольпо-?вагініт)\w*",
    r"(?:реакці\w+\s+\w+|метод\w+\s+забарвлен\w*|фарбуван\w+\s+мазк\w+|переливан\w+\s+крові|поживн\w+\s+середовищ\w*)",
    r"(?:вакцин\w+|сироватк\w+|алерген\w+|антибіотик\w+|імунодефіцит\w+|сенсибілізаці\w+|імунітет\w*)",
]

# Require non-letter/non-digit boundaries around every trigger so short tokens (e.g. IgE, РІФ)
# never match inside unrelated words such as Sh[ige]lla.
_BOUNDARY_LEFT = r"(?:^|(?<=[^\wа-яА-ЯіїєґІЇЄҐ]))"
_BOUNDARY_RIGHT = r"(?:$|(?=[^\wа-яА-ЯіїєґІЇЄҐ]))"
_COMPILED_TRIGGERS = [
    re.compile(f"{_BOUNDARY_LEFT}(?:{pat}){_BOUNDARY_RIGHT}", re.IGNORECASE | re.UNICODE)
    for pat in _TRIGGER_PATTERNS
]
_COMPILED_FALLBACKS = [
    re.compile(f"{_BOUNDARY_LEFT}(?:{pat}){_BOUNDARY_RIGHT}", re.IGNORECASE | re.UNICODE)
    for pat in _FALLBACK_PATTERNS
]


def _normalize_verbatim_markers(stem: str, candidates: list[str], max_items: int = 3) -> list[str]:
    """Keep only markers that exist verbatim (case-insensitive) in stem without overlaps."""
    stem_low = stem.lower()
    chosen: list[tuple[int, int, str]] = []
    for cand in candidates:
        c = cand.strip()
        if len(c) < 2:
            continue
        pos = stem_low.find(c.lower())
        if pos == -1:
            continue
        end = pos + len(c)
        overlaps = any(not (end <= s or pos >= e) for s, e, _ in chosen)
        if not overlaps:
            chosen.append((pos, end, stem[pos:end]))
        if len(chosen) >= max_items:
            break
    chosen.sort(key=lambda t: t[0])
    return [t[2] for t in chosen]


def _select_non_overlapping(stem: str, patterns: list[re.Pattern[str]], max_items: int = 3) -> list[str]:
    matches: list[tuple[int, int, str]] = []
    for pat in patterns:
        m = pat.search(stem)
        if m:
            matches.append((m.start(), m.end(), stem[m.start():m.end()]))

    matches.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    selected: list[tuple[int, int, str]] = []
    for start, end, text in matches:
        if any(not (end <= s or start >= e) for s, e, _ in selected):
            continue
        selected.append((start, end, text))
        if len(selected) >= max_items:
            break
    selected.sort(key=lambda item: item[0])
    return [item[2] for item in selected]


def extract_krok_triggers(stem: str, correct_text: str) -> tuple[list[str], str]:
    """Deterministically extract up to 3 high-yield clinical triggers from stem."""
    markers = _select_non_overlapping(stem, _COMPILED_TRIGGERS, max_items=3)
    if not markers:
        markers = _select_non_overlapping(stem, _COMPILED_FALLBACKS, max_items=3)

    if markers:
        anchor = f"{' + '.join(markers)} → {correct_text}"
    else:
        anchor = f"Ключ → {correct_text}"
    return markers, anchor


def get_cached_explanation(conn: sqlite3.Connection, qid: int) -> ExplanationOut | None:
    """Return cached explanation row from SQLite if present."""
    row = conn.execute(
        """
        SELECT markers_json, anchor_uk, explanation_uk, distractors_uk, model_id
        FROM question_explanations
        WHERE question_id = ?
        """,
        (qid,),
    ).fetchone()
    if row is None:
        return None
    return ExplanationOut(
        markers=json.loads(row["markers_json"]),
        anchor_uk=row["anchor_uk"],
        explanation_uk=row["explanation_uk"],
        distractors_uk=row["distractors_uk"],
        model_id=row["model_id"],
    )


def save_explanation(
    conn: sqlite3.Connection,
    *,
    qid: int,
    markers: list[str],
    anchor_uk: str,
    explanation_uk: str,
    distractors_uk: str,
    model_id: str,
    commit: bool = True,
) -> ExplanationOut:
    """Upsert cached explanation row for question_id."""
    now_ts = int(time.time())
    conn.execute(
        """
        INSERT INTO question_explanations (
            question_id, markers_json, anchor_uk, explanation_uk, distractors_uk, model_id, updated_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(question_id) DO UPDATE SET
            markers_json = excluded.markers_json,
            anchor_uk = excluded.anchor_uk,
            explanation_uk = excluded.explanation_uk,
            distractors_uk = excluded.distractors_uk,
            model_id = excluded.model_id,
            updated_ts = excluded.updated_ts
        """,
        (
            qid,
            json.dumps(markers, ensure_ascii=False),
            anchor_uk.strip(),
            explanation_uk.strip(),
            distractors_uk.strip(),
            model_id,
            now_ts,
        ),
    )
    if commit:
        conn.commit()
    return ExplanationOut(
        markers=markers,
        anchor_uk=anchor_uk.strip(),
        explanation_uk=explanation_uk.strip(),
        distractors_uk=distractors_uk.strip(),
        model_id=model_id,
    )


def generate_gemini_explanation(
    *,
    stem: str,
    options: list[str],
    correct_idx: int,
    api_key: str,
    model: str,
) -> ExplanationOut:
    """Call Gemini Flash REST API once and validate structured JSON output."""
    correct_text = options[correct_idx]
    distractors = [o for i, o in enumerate(options) if i != correct_idx]
    prompt = (
        "Ти — викладач ВНМУ ім. М. І. Пирогова. Склади надкороткий, високоточний розбір тесту КРОК-1 українською мовою без води.\n"
        "Поверни ВИКЛЮЧНО JSON-об'єкт з полями:\n"
        '- "markers": масив із 2–3 точних дослівних фрагментів з тексту умови (щоб їх можна було знайти підрядком у stem);\n'
        '- "anchor_uk": коротка формула-якір на 1 рядок ("тригер + тригер → правильна відповідь");\n'
        '- "explanation_uk": клініко-мікробіологічний механізм у 2 коротких реченнях;\n'
        '- "distractors_uk": чому не підходять головні дистрактори (1–2 речення).\n\n'
        f"Умова: {stem}\n"
        f"Правильна відповідь: {correct_text}\n"
        f"Дистрактори: {json.dumps(distractors, ensure_ascii=False)}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    with httpx.Client(timeout=25.0) as client:
        resp = client.post(url, params={"key": api_key}, json=payload)
        resp.raise_for_status()
        body = resp.json()

    candidates = body.get("candidates") or []
    raw_text = candidates[0]["content"]["parts"][0]["text"]
    parsed = json.loads(raw_text)

    markers = _normalize_verbatim_markers(stem, list(parsed.get("markers") or []), max_items=3)
    if not markers:
        markers, _ = extract_krok_triggers(stem, correct_text)

    anchor_uk = str(parsed.get("anchor_uk") or f"{' + '.join(markers) or 'Ключ'} → {correct_text}").strip()
    explanation_uk = str(parsed.get("explanation_uk") or "").strip()
    distractors_uk = str(parsed.get("distractors_uk") or "").strip()
    return ExplanationOut(
        markers=markers,
        anchor_uk=anchor_uk,
        explanation_uk=explanation_uk,
        distractors_uk=distractors_uk,
        model_id=model,
    )


def get_or_generate_explanation(
    conn: sqlite3.Connection,
    *,
    qid: int,
    user: UserOut | None,
    upgrade_triggers: bool = False,
) -> ExplanationOut:
    """Return cached explanation or generate once via Gemini Flash for authenticated users."""
    row = conn.execute(
        "SELECT id, stem, options_json, correct_idx FROM questions WHERE id = ? AND status = 'verified'",
        (qid,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Питання не знайдено")

    cached = get_cached_explanation(conn, qid)
    if cached is not None and not (upgrade_triggers and cached.model_id == "trigger-index-v1"):
        return cached

    if user is None:
        if cached is not None:
            return cached
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Жива генерація розборів доступна лише авторизованим користувачам",
        )

    settings = get_settings()
    if not settings.gemini_api_key:
        if cached is not None:
            return cached
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY ще не налаштований у .env; доступні лише прегенеровані маркери",
        )

    # Enforce daily quota per non-admin user in SQLite so restarts never reset daily limits.
    day_ymd = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if user.role != "admin":
        usage = conn.execute(
            "SELECT cnt FROM explain_usage WHERE user_id = ? AND day_ymd = ?",
            (user.id, day_ymd),
        ).fetchone()
        used = int(usage["cnt"]) if usage else 0
        if used >= settings.explain_daily_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Досягнуто денний ліміт розборів ({settings.explain_daily_limit}/день)",
            )

    options: list[str] = json.loads(row["options_json"])
    correct_idx = int(row["correct_idx"])
    generated = generate_gemini_explanation(
        stem=row["stem"],
        options=options,
        correct_idx=correct_idx,
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )

    conn.execute(
        """
        INSERT INTO explain_usage (user_id, day_ymd, cnt)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, day_ymd) DO UPDATE SET cnt = cnt + 1
        """,
        (user.id, day_ymd),
    )
    return save_explanation(
        conn,
        qid=qid,
        markers=generated.markers,
        anchor_uk=generated.anchor_uk,
        explanation_uk=generated.explanation_uk,
        distractors_uk=generated.distractors_uk,
        model_id=generated.model_id,
        commit=True,
    )
