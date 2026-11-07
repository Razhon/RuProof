#!/usr/bin/env python3
"""Фильтрующий прокси перед LanguageTool: LT знает слова, прокси решает, что показать.

Всё, кроме POST /v2/check, проходит без изменений. /v2/check: U+2011 -> '-' перед LT, затем
орфографические замечания (MORFOLOGIK_RULE_RU_RU) на экспрессивные формы не помечаются или смягчаются до стиля.
Слово считается словарным, если его принимает speller самого LT (один запрос-оракул на проверку).
При любой ошибке уходит ответ LT без фильтра (fail open).

Режим (neutral — по умолчанию, prose — художественный текст) и отдельные правила задаёт proxy/config.ini
(образец: config.example.ini); файл перечитывается при изменении. Заголовок X-Proxy-Mode меняет режим одного запроса.

env: LT_URL, PORT, PROXY_DATA (каталог памяти имён), PROXY_DICT (слова пользователя), PROXY_CONFIG (config.ini)
запуск: proxy.py      сервер (регрессионный набор: regress.py)
"""

import collections
import configparser
import hashlib
import itertools
import json
import mmap
import os
import re
import socket
import sys
import tempfile
import threading
import time
import traceback
import types
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LT_URL = os.environ.get("LT_URL", "http://localhost:8010").rstrip("/")
PORT = int(os.environ.get("PORT", "8080"))
DATA = os.environ.get("PROXY_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
SPELL = "MORFOLOGIK_RULE_RU_RU"
NBH = "‑"  # слова с неразрывным дефисом LT не проверяет вовсе
HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authorization",
    "proxy-authenticate",
    "host",
    "content-length",
    "accept-encoding",
    "date",
    "server",
}  # date/server: send_response() пишет свои
PARTICLES = {
    "то",
    "либо",
    "нибудь",
    "бы",
    "ли",
    "же",
    "ка",
    "таки",
    "де",
    "с",
}  # что-бы должно остаться ошибкой
ENDINGS = {
    "",
    "а",
    "я",
    "у",
    "ю",
    "е",
    "и",
    "ы",
    "ом",
    "ем",
    "ём",
    "ой",
    "ей",
    "ою",
    "ею",
    "ов",
    "ев",
    "ам",
    "ям",
    "ами",
    "ями",
    "ах",
    "ях",
}  # Брумзиллоп/-а/-ом — одно имя
BOUNDARY_OK = {"PUNCTUATION", "TYPOGRAPHY", "CASING", "TYPOS"}  # эти проверяют сам стык
BOUNDARY_RULES = {"kosvennaja_rech"}  # правила других категорий, которые тоже проверяют стык (что «…»)
NOTE_NAME = "Похоже на имя: добавьте его в словарь (rpdict). "
NOTE_TITLE = "Похоже на название. "
NOTE_SPLIT = "Разбиение слова: художественный приём? "
NOTE_CUT = "Обрыв слова? "
NOTE_STAMMER = "Запинка? "
NOTE_STRETCH = "Заикание или растяжка? "
GUILLEMETS = "RU_UNPAIRED_GUILLEMETS"  # своё замечание прокси: RU_UNPAIRED_BRACKETS в LT пропускает «», а grammar.xml видит одно предложение
NESTED = "RU_NESTED_GUILLEMETS"  # своё замечание прокси: «» внутри «» должны быть „“
QUOTE_RULES = {
    "QUOTES",
    "RU_UNPAIRED_BRACKETS",
}  # замечания LT о кавычках (id правила или категории): не дублировать
# окончания, дописывающие слово, оборванное перед «…» (тобо… -> тобой, пон… -> понял); более длинный обрыв остаётся ошибкой
CUT_TAILS = [
    "а",
    "я",
    "о",
    "е",
    "ё",
    "и",
    "ы",
    "у",
    "ю",
    "й",
    "ь",
    "ой",
    "ей",
    "ий",
    "ый",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ую",
    "юю",
    "ом",
    "ем",
    "ём",
    "ам",
    "ям",
    "ах",
    "ях",
    "ов",
    "ев",
    "ть",
    "ал",
    "ял",
    "ил",
    "ел",
    "ул",
    "ла",
    "ло",
    "ли",
    "ет",
    "ит",
    "ут",
    "ют",
    "ат",
    "ят",
    "ем",
    "им",
    "ся",
    "сь",
    "на",
    "но",
    "ны",
    "ка",
    "ко",
    "ки",
    "ок",
    "ек",
    "ец",
    "ня",
    "ать",
    "ять",
    "еть",
    "ить",
    "уть",
    "ала",
    "ила",
    "ало",
    "ило",
    "али",
    "или",
    "ешь",
    "ишь",
    "ете",
    "ите",
    "ого",
    "его",
    "ому",
    "ему",
    "ими",
    "ыми",
    "ами",
    "ями",
]
# ключи политики (proxy/config.example.ini); защита правила 1, U+2011, кеш и fail open не выключаются
RULES = (
    "compound",  # 3: бизнес-аналитик
    "split",  # 0, 4: Безоб Разие, чел-овек
    "cut",  # 6: подум…
    "stretch_hint",  # 5: Нееет -> Не-е-ет первым вариантом
    "variant",  # 8: более частый близкий вариант слова с заглавной
    "concessive",  # что бы … ни
    "guillemets",  # непарные «»
    "nested",  # „лапки“ внутри «»
    "stretch",  # 2: П-прямо, Не-е-ет
    "stammer",  # Ва… ва… ваше
    "titles",  # 7: названия в «»
    "names",  # 9 и память имён
    "dialogue",  # разметка речи и автора, перепроверка на границах
    "nonstandard",  # слова вне нормы (rpdict -u), talk и просторечие RU_SIMPLE_REPLACE: не замечание (иначе стиль)
    "caps",  # слово ЗАГЛАВНЫМИ (AllCaps): не замечание (иначе стиль)
    "fillers",  # слова-паразиты (как бы, так сказать): не замечание (иначе как у LT)
)
FILLERS = {"kak_bi", "tak_skazat", "vozmojno_oshibayas"}  # правила «Слова-паразиты» из grammar.xml
PRESETS = {
    "neutral": frozenset(RULES[:8]),  # годится для любого текста
    "prose": frozenset(RULES),  # художественный текст: речь, имена, заикания
}
CONFIG = os.environ.get(
    "PROXY_CONFIG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"),
)


class LRU:
    def __init__(self, n):
        self.n, self.d, self.lock = n, collections.OrderedDict(), threading.Lock()

    def get(self, k):
        with self.lock:
            if k in self.d:
                self.d.move_to_end(k)
                return self.d[k]

    def put(self, k, v):
        with self.lock:
            self.d[k] = v
            self.d.move_to_end(k)
            if len(self.d) > self.n:
                self.d.popitem(last=False)

    def clear(self):
        with self.lock:
            self.d.clear()


CACHE = LRU(500)  # ответы LT по телу запроса: расширение пересылает неизменённые куски
WORDS = LRU(
    50000
)  # вердикты оракула; оба кеша сбрасываются, когда LT перезапускается с новыми правилами или словами (watch_lt)
SESSIONS = LRU(64)  # textSessionId -> весь документ (из его запроса textLevelOnly)
FAILED = LRU(256)  # хеш текста оракула -> время сбоя: повторный кусок не должен снова нагружать перегруженный LT


# ---------- чистые функции над текстом ----------

STUTTER = re.compile(r"(?i)^(\w{1,2})(?:-\1)+(?=\w)")  # П-прямо, Ко-ко-конечно
STRETCH = re.compile(r"(?i)(\w)(?:-\1)+")  # Не-е-ет, да-а-а (и однобуквенное заикание)
RUN = re.compile(r"(?i)(\w)\1{2,}")  # Нееет: растяжка без дефисов
CAPWORD = re.compile(r"(?<![\w-])[^\W\d_](?:[^\W\d_]|-[^\W\d_])*")
DASH = re.compile(r"[,.!?…:]\s+[—–]\s+")
AUTHOR, SPEECH, TITLE, TITLE1, UNKNOWN = range(5)  # виды участков, см. regions()
PAST = re.compile(r"\w{2,}(?:л|ла|ло|ли)(?:ся|сь)?$|\w+(?:ёс|ёк|ёг|ёз|яс|ог)(?:ся)?$")  # сказал, улыбнулась, произнёс
QUOTED = {
    SPEECH,
    TITLE,
    TITLE1,
}  # разбиение слова прощается только здесь; UNKNOWN считается авторским текстом
PERSONAL = {
    "я",
    "меня",
    "мне",
    "мной",
    "мы",
    "нас",
    "нам",
    "нами",
    "ты",
    "тебя",
    "тебе",
    "тобой",
    "вы",
    "вас",
    "вам",
    "вами",
}


def expressive(w):
    """Словарные кандидаты для слова с заиканием или растяжкой через дефис."""
    s = STUTTER.sub(r"\1", w)
    return [c for c in dict.fromkeys((s, STRETCH.sub(r"\1", w), STRETCH.sub(r"\1", s))) if c != w]


def unstretch(w, k):
    """'Нееет' -> (сжатая форма вроде 'нет', подсказка 'Не-е-ет'), повторы сокращаются до k букв."""
    return (
        RUN.sub(lambda m: m.group()[:k], w),
        RUN.sub(lambda m: m.group()[:k] + "".join("-" + c for c in m.group()[k:]), w),
    )


def dist(a, b):
    """Расстояние Дамерау — Левенштейна (optimal string alignment), без учёта регистра."""
    a, b = a.lower(), b.lower()
    d = [[i + j if not i * j else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + (a[i - 1] != b[j - 1]),
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def family(a, b):
    """Одно слово с точностью до падежного окончания: Брумзиллоп/Брумзиллопом — да, Брумзиллоп/Брумзилоп — нет."""
    a, b = a.lower(), b.lower()
    p = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return p >= 3 and a[p:] in ENDINGS and b[p:] in ENDINGS


def yo_error(w, reps):
    """LT предлагает то же слово с ё: настоящая ошибка, даже если части слова словарные."""
    return any("ё" in r.lower() and r.lower().replace("ё", "е") == w.lower().replace("ё", "е") for r in reps)


def sentence_start(text, i):
    j, quoted = i - 1, False
    while j >= 0 and (text[j] in " \t«„“\"'(—–"):
        quoted |= text[j] in '«„“"'
        j -= 1
    return j < 0 or text[j] in ".!?…\n" or (quoted and text[j] == ":")


def voice(seg):
    """Кто говорит после «— речь, —»: AUTHOR, если среди первых слов есть глагол прошедшего времени (сказал он, я кивнул),
    SPEECH, если его нет, но есть местоимение 1-го/2-го лица (хоть я и не уверен), иначе UNKNOWN."""
    words = re.findall(r"\w+", seg.lower())[:4]
    if any(PAST.match(w) for w in words):
        return AUTHOR
    return SPEECH if any(w in PERSONAL for w in words) else UNKNOWN


def regions(text, dialogue=True, titles=True):
    """Для каждого символа: AUTHOR, SPEECH (реплики диалога, речь в кавычках), TITLE — название в «» из 2–4 слов,
    TITLE1 — название из одного слова (там вероятнее опечатка вроде «Превет»), UNKNOWN (после тире реплики нет подсказки).
    dialogue=False: речи нет, titles=False: названий нет — такие участки остаются AUTHOR."""
    kind = bytearray(len(text))
    for line in re.finditer(r"[^\n]+", text) if dialogue else ():
        a, b = line.span()
        if line.group().lstrip()[:1] not in "—–":
            continue
        cuts = list(DASH.finditer(text, a, b))  # — Речь, — сказал он, — речь. — Речь.
        prev = AUTHOR  # первая часть — речь
        for s, e in zip([a] + [d.end() for d in cuts], [d.start() for d in cuts] + [b]):
            k = voice(text[s:e]) if prev == SPEECH else SPEECH  # продолженная речь остаётся речью до следующего тире
            kind[s:e] = bytes([k]) * (e - s)
            prev = k
    for q in re.finditer(r"«([^«»\n]*)»", text):
        inner = q.group(1)
        said = text[: q.start()].rstrip().endswith(":") or re.match(r"\s*[,.!?…]?\s*[—–]", text[q.end() :])
        title = not said and inner[:1].isupper() and len(inner.split()) <= 4 and not re.search(r"[.!?…,;:]", inner)
        if titles if title else dialogue:
            kind[q.start(1) : q.end(1)] = bytes(
                [SPEECH if not title else TITLE if " " in inner.strip() else TITLE1]
            ) * len(inner)
    return kind


def u16map(text):
    """Смещение в UTF-16 (его возвращает LT) -> индекс символа."""
    idx = []
    for i, ch in enumerate(text):
        idx.extend((i, i) if ord(ch) > 0xFFFF else (i,))
    return idx + [len(text)]


def u16(text, i):
    """Индекс символа -> смещение в UTF-16."""
    return len(text[:i].encode("utf-16-le")) // 2


def stammer(text, a, b):
    """«Ва… ва… ваше»: обрывок из 1–3 букв перед многоточием, который повторяет следующее слово (запинка, §186)."""
    f = text[a:b].lower()
    m = re.match(r"(?:…|\.\.\.)\s*(\w+)", text[b : b + 40])
    return bool(0 < len(f) <= 3 and f.isalpha() and m and m.group(1).lower().startswith(f))


CONCESSIVE = re.compile(
    r"(?i)(?:^|\W)(?:что|чего|чему|чем|чём|кто|кого|кому|кем|ком|где|куда|откуда|когда|как\w*|"
    r"сколько|чей|чь[яеёи]\w*|зачем|почему)\s(?:.*\s)?бы\s"
)
# shortcut: список вводных слов фиксирован; при другом вводном слове в запятых замечание LT остаётся (безопасная сторона)
_INTRO = (
    r"(?:наверн\w*|конечно|кажется|казалось бы|видимо|похоже|возможно|может быть|может|вероятно|пожалуй|"
    r"очевидно|разумеется|впрочем|кстати|в общем|правда|по-моему|по сути|собственно|вообще-то|к сожалению|"
    r"к счастью|честно говоря|по правде говоря|мол|дескать)"
)
INTRO = re.compile(rf"(?i),\s*{_INTRO}(?:\s*,\s*{_INTRO})*\s*,")  # цепочка: `, конечно, кажется,`
# «Всё, что ни делается»: «ни» без «бы» после обобщающего слова прямо перед запятой
ALL_WHAT = re.compile(
    r"(?i)(?:^|\W)(?:всё|все|всего|всем|везде|всюду|всегда|повсюду)\s*,\s*"
    r"(?:что|кто|кого|кому|кем|чем|чём|где|куда|откуда|когда|как\w*)\s[^,.!?;:…\n—–]*$"
)


def concessive(text, a):
    """«Что бы она ни хотела», «всё, что она ни хотела»: «ни» на индексе a в уступительном придаточном (правило LT
    по 3-граммам требует «не»). Вводные слова в запятых (`Что бы, честно говоря, она ни`) придаточное не завершают."""
    head = INTRO.sub(" ", text[:a])
    clause = re.split(r"[,.!?;:…\n—–]", head)[-1]
    return bool(CONCESSIVE.search(clause) or ALL_WHAT.search(head))


def unpaired(text):
    """Индексы « и » без пары в своём абзаце (вложенность допустима). Незакрытая « допустима, если
    следующий абзац начинается с « (цитата на несколько абзацев закрывается только в последнем)."""
    lines = [(m.start(), m.group()) for m in re.finditer(r"[^\n]*\S[^\n]*", text)]
    out = []
    for n, (s, line) in enumerate(lines):
        stack = []
        for i, ch in enumerate(line):
            if ch == "«":
                stack.append(s + i)
            elif ch == "»":
                if stack:
                    stack.pop()
                else:
                    out.append(s + i)
        if stack and not (n + 1 < len(lines) and lines[n + 1][1].lstrip().startswith("«")):
            out += stack
    return sorted(out)


def nested(text):
    """Индексы (открывающей, закрывающей) «» внутри «» в одной строке: внутренние кавычки должны быть „“ (Розенталь, §66.5),
    кроме случая, когда между внутренней и внешней закрывающими стоит ? или ! («С кем вы, «мастера культуры»?»)."""
    out = []
    for m in re.finditer(r"[^\n]+", text):
        s, line, stack = m.start(), m.group(), []
        for i, ch in enumerate(line):
            if ch == "«":
                stack.append(i)
            elif ch == "»" and stack:
                o = stack.pop()
                if stack and not (line[i + 1 : i + 2] in ("?", "!") and line[i + 2 : i + 3] == "»"):
                    out.append((s + o, s + i))
    return sorted(out)


def sentence_of(text, i):
    a = max(text.rfind(c, 0, i) for c in ".!?…\n") + 1
    ends = [e for e in (text.find(c, i) for c in ".!?…\n") if e >= 0]
    return text[a : min(ends) + 1 if ends else len(text)].strip()


def window(text, a, b):
    """Слово a:b и по одному слову с каждой стороны в пределах предложения: правка остальной части предложения
    не должна давать новую встречу имени."""
    left = re.split(r"[.!?…\n]", text[max(a - 40, 0) : a])[-1]
    right = re.split(r"[.!?…\n]", text[b : b + 40])[0]
    return " ".join(re.findall(r"\w+", left)[-1:] + [text[a:b]] + re.findall(r"\w+", right)[:1])


# ---------- память имён (proxy/data/names.json, names.txt для rpdict) ----------


def close(v, w):
    """v — близкое написание w (опечатка в имени: Брумзилоп и Брумзиллоп), а не форма того же слова."""
    lim = 1 if len(w) < 7 else 2
    return abs(len(v) - len(w)) <= lim and dist(v, w) <= lim and not family(v, w)


NAMES_TTL = 7  # дней: слово, которое перестали писать (исправленная опечатка), забывается само


def today():
    return int(time.time() // 86400)


class Names:
    """Незнакомые слова с заглавной буквы: различные встречи (слово с соседями, см. window()) во всех документах,
    t — день последней встречи. names.json перечитывается, если его изменил не прокси: удалить запись = забыть слово."""

    def __init__(self, path):
        self.path, self.lock, self.stamp, self.d = path, threading.Lock(), None, {}
        self.file = os.path.join(path, "names.json")
        self._load()

    def _load(self):  # вызывается под self.lock (или из __init__)
        try:
            stamp = os.stat(self.file).st_mtime_ns
        except OSError:
            return
        if stamp == self.stamp:
            return
        self.stamp = stamp
        try:
            with open(self.file, encoding="utf-8") as f:
                d = json.load(f)
        except (
            OSError,
            ValueError,
        ) as e:  # испорченная правка руками: остаётся прежняя память
            log(f"names: не прочитано: {e}")
            return
        for e in d.values():
            e.setdefault("t", today())  # записи без даты: срок отсчитывается с первой загрузки
        self.d = {k: e for k, e in d.items() if today() - e["t"] <= NAMES_TTL}

    def seen(self, w):
        with self.lock:
            self._load()
            return sum(len(v["s"]) for k, v in self.d.items() if family(k, w))

    def known(self):
        with self.lock:
            self._load()
            return {k for k, v in self.d.items() if len(v["s"]) >= 3}

    def add(self, items):  # [(word, sentence, window)]
        changed = False
        with self.lock:
            self._load()
            for w, sent, win in items:
                e = self.d.setdefault(w, {"s": [], "ex": sent[:120], "t": today()})
                h = hashlib.sha1(win.encode()).hexdigest()[:12]  # повторные проверки того же места не считаются
                if h not in e["s"] and len(e["s"]) < 50:
                    e["s"].append(h)
                    changed = True
                if e["t"] != today():
                    e["t"], changed = today(), True
            if changed:
                self.save()

    def forget(self, is_word):
        """Забыть слова, ставшие словарными (rpdict), и их близкие написания — опечатки этого имени."""
        with self.lock:
            self._load()
            words = [k for k in self.d if is_word(k)]
            gone = [k for k in self.d if k in words or any(close(k, w) for w in words)]
            for k in gone:
                del self.d[k]
            if gone:
                self.save()
                log(f"names: забыто {len(gone)} (в словаре)")

    def save(self):
        self.d = {k: e for k, e in self.d.items() if today() - e["t"] <= NAMES_TTL}
        try:
            os.makedirs(self.path, exist_ok=True)
            tmp = os.path.join(
                self.path, "names.json.tmp"
            )  # оборванная запись (остановка контейнера) не должна обнулить память
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False)
            os.replace(tmp, self.file)
            self.stamp = os.stat(self.file).st_mtime_ns
            with open(os.path.join(self.path, "names.txt"), "w", encoding="utf-8") as f:
                f.write(
                    "# слово<TAB>предложений<TAB>пример; настоящие имена добавляйте через rpdict (например, Брумти=нескл.м),"
                    f" тогда их опечатки забываются; не встречавшееся {NAMES_TTL} дней забывается само;"
                    " забыть сразу: удалить запись из names.json\n"
                )
                f.writelines(
                    f"{w}\t{len(e['s'])}\t{e['ex']}\n"
                    for w, e in sorted(self.d.items(), key=lambda kv: (-len(kv[1]["s"]), kv[0]))
                )
        except OSError as e:
            log(f"names: не сохранено: {e}")


class Wordlist:
    """data/words.raw: слова speller в виде строк «слово+частота», отсортированных побайтно (fsa_decompile в сервисе compose `words`).
    Двоичный поиск по файлу через mmap; файл открывается заново, когда его заменили."""

    def __init__(self, path):
        self.path, self.lock, self.mm, self.stamp = path, threading.Lock(), None, None

    def _map(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        with self.lock:
            if (st.st_mtime_ns, st.st_size) != self.stamp:
                with open(self.path, "rb") as f:
                    self.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) if st.st_size else None
                self.stamp = (st.st_mtime_ns, st.st_size)
            return self.mm

    def available(self):
        return self._map() is not None

    @staticmethod
    def _seek(mm, p):
        """Начало первой строки >= p."""
        lo, hi = 0, len(mm)
        while lo < hi:  # lo, hi: начала строк; останавливается на первой строке >= p
            s = mm.rfind(b"\n", 0, (lo + hi) // 2) + 1
            e = mm.find(b"\n", s)
            e = len(mm) if e < 0 else e
            if mm[s:e] < p:
                lo = e + 1
            else:
                hi = s
        return lo

    def has(self, w):
        """True, если w — слово словаря (с тем же регистром); None, если списка нет."""
        mm = self._map()
        if mm is None:
            return None
        p = w.encode()
        lo = self._seek(mm, p)
        e = mm.find(b"\n", lo)
        line = mm[lo : len(mm) if e < 0 else e]
        return line == p or line.startswith(p + b"+")

    def extends(self, w):
        """True, если с w начинается более длинное слово (подум -> подумать); None, если списка нет."""
        mm = self._map()
        if mm is None:
            return None
        p = w.encode()
        lo = self._seek(mm, p)
        for _ in range(3):  # само слово (по строке на частоту) стоит сразу перед более длинными формами
            e = mm.find(b"\n", lo)
            line = mm[lo : len(mm) if e < 0 else e]
            if not line.startswith(p):
                return False
            plus = line.rfind(b"+")
            if (plus if plus >= 0 else len(line)) > len(p):
                return True
            if e < 0:
                return False
            lo = e + 1
        return False


WORDLIST = Wordlist(os.path.join(DATA, "words.raw"))
DICT = os.environ.get("PROXY_DICT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dict"))
_custom = {"stamp": None, "words": set()}


def custom_words():
    """Слова пользователя, которых нет в ru_RU.dict (dict/spelling_custom.txt, ignore.txt), в нижнем регистре; перечитываются при изменении."""
    files = [os.path.join(DICT, f) for f in ("spelling_custom.txt", "ignore.txt")]
    stamp = tuple(os.stat(f).st_mtime_ns if os.path.exists(f) else 0 for f in files)
    if stamp != _custom["stamp"]:
        words = set()
        for f in files:
            try:
                with open(f, encoding="utf-8") as fh:
                    words.update(s.strip().lower() for s in fh if s.strip() and not s.startswith("#"))
            except OSError:
                pass
        _custom.update(stamp=stamp, words=words)
    return _custom["words"]


def parse_config(src):
    """Текст config.ini -> (режим, включённые ключи RULES); ValueError при неизвестном режиме, ключе или значении."""
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    cp.read_string(src)
    mode = cp.get("proxy", "mode", fallback="neutral")
    if mode not in PRESETS:
        raise ValueError(f"неизвестный режим {mode!r} (есть: {', '.join(PRESETS)})")
    on = set(PRESETS[mode])
    for k in cp.options("rules") if cp.has_section("rules") else ():
        if k not in RULES:
            raise ValueError(f"неизвестное правило {k!r}")
        (on.add if cp.getboolean("rules", k) else on.discard)(k)
    return mode, frozenset(on)


def header_mode(value):
    """Заголовок X-Proxy-Mode («prose titles=no names=yes») -> (режим, ключи); ошибки как у parse_config."""
    mode, *keys = value.split() or [""]
    return parse_config(f"[proxy]\nmode = {mode}\n[rules]\n" + "\n".join(keys))


_conf = {"stamp": None, "conf": ("neutral", PRESETS["neutral"])}


def config():
    """(режим, включённые ключи) из CONFIG, перечитывается при изменении; нет файла или ошибка в нём -> neutral."""
    try:
        stamp = os.stat(CONFIG).st_mtime_ns
    except OSError:
        stamp = None
    if stamp != _conf["stamp"]:
        conf = ("neutral", PRESETS["neutral"])
        if stamp is not None:
            try:
                with open(CONFIG, encoding="utf-8-sig") as f:  # PowerShell 5.1 пишет BOM
                    conf = parse_config(f.read())
            except (OSError, ValueError, configparser.Error) as e:
                log(f"config.ini не принят ({e}): режим neutral")
        off = sorted(set(RULES) - conf[1])
        log(f"режим {conf[0]}, выключено: {', '.join(off) or 'ничего'}")
        _conf.update(stamp=stamp, conf=conf)
    return _conf["conf"]


# ---------- LanguageTool ----------


def log(s):
    sys.stdout.write(s + "\n")  # одна запись: строки параллельных запросов не перемешиваются
    sys.stdout.flush()


NAMES = Names(DATA)  # после log(): загрузка пишет в лог


def lt(path, body, method="POST", headers=None):
    req = urllib.request.Request(LT_URL + path, data=body or None, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:  # больше maxCheckTimeMillis LT (60 с)
            return r.status, list(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:  # ответы LT с ошибкой проходят как есть
        return e.code, list(e.headers.items()), e.read()


def watch_lt(every=2):
    """LT перезапустили отдельно (rules.py, rpdict -n) -> кешированные ответы и вердикты оракула устарели: сбросить их.
    Перезапуск закрывает порт LT на 10+ с (старт JVM), поэтому TCP-проба раз в 2 с его замечает."""
    u = urllib.parse.urlsplit(LT_URL)
    up = True
    while True:
        try:
            socket.create_connection((u.hostname, u.port or 80), timeout=2).close()
            if not up:
                CACHE.clear()
                WORDS.clear()
                FAILED.clear()
                log("LT снова доступен: кеши сброшены")
            up = True
        except OSError:
            up = False
        time.sleep(every)


def oracle(words):
    """слово -> True, если его принимает speller LT."""
    need = [w for w in dict.fromkeys(words) if WORDS.get(w) is None]
    if need:
        text = "\n".join(need)
        fk = hashlib.sha1(text.encode()).hexdigest()
        if time.time() - (FAILED.get(fk) or 0) < 60:
            raise OSError("oracle: failed less than a minute ago")
        body = urllib.parse.urlencode(
            {
                "text": text,
                "language": "ru-RU",
                "enabledOnly": "true",
                "enabledRules": SPELL,
            }
        ).encode()
        try:
            status, _, data = lt("/v2/check", body)
            if status != 200:
                raise OSError(f"oracle: HTTP {status}")
        except OSError:  # в том числе таймаут 90 с
            FAILED.put(fk, time.time())
            raise
        idx, bad = u16map(text), set()
        for m in json.loads(data)["matches"]:
            # LT склеивает строки в одно замечание («П\nПпрямо»): плохи все строки, которых оно касается
            s, e = idx[m["offset"]], idx[m["offset"] + m["length"]]
            bad.update(range(text.count("\n", 0, s), text.count("\n", 0, e) + 1))
        for i, w in enumerate(need):
            WORDS.put(w, i not in bad)
    return {w: WORDS.get(w) for w in words}


# ---------- фильтрация ----------


def key(m):
    r = m["rule"]
    return f"{r['id']}[{r['subId']}]" if r.get("subId") else r["id"]


def cut(text, w, b):
    """Слово, кончающееся на b, оборвано многоточием: «Я не тобо…»."""
    return len(w) >= 2 and "-" not in w and (text.startswith("…", b) or text.startswith("...", b))


def soften(m, note):
    m["rule"]["issueType"] = "style"
    m["type"] = {"typeName": "Hint"}
    m["message"] = note + m.get("message", "")


def own_match(text, i, rule_id, message, repl=None):
    """Замечание, которое прокси добавляет сам, в формате LT (один символ на индексе i)."""
    c = max(i - 40, 0)
    return {
        "message": message,
        "shortMessage": message,
        "replacements": [{"value": repl}] if repl else [],
        "offset": u16(text, i),
        "length": 1,
        "context": {
            "text": text[c : i + 40],
            "offset": u16(text, i) - u16(text, c),
            "length": u16(text, i + 1) - u16(text, i),
        },
        "sentence": sentence_of(text, i),
        "type": {"typeName": "Other"},
        "ignoreForIncompleteSentence": False,
        "contextForSureMatch": 0,
        "rule": {
            "id": rule_id,
            "description": message,
            "issueType": "typographical",
            "category": {"id": "TYPOGRAPHY", "name": "Типографика"},
        },
    }


NOTES = {  # приставка к сообщению смягчённого замечания по причине решения
    "name": NOTE_NAME,
    "title": NOTE_TITLE,
    "split": NOTE_SPLIT,
    "space-split": NOTE_SPLIT,
    "cut": NOTE_CUT,
    "stammer": NOTE_STAMMER,
    "stretch": NOTE_STRETCH,
}


class Check:
    """Общие данные одной проверки для шагов политики: разметка текста, орфографические замечания,
    ответы оракула и слова документа с заглавной буквы."""

    def __init__(self, text, orig, matches, whole, on):
        self.text, self.orig, self.on = text, orig, on  # on: включённые ключи RULES
        self.idx = u16map(text)
        self.kind = regions(text, "dialogue" in on, "titles" in on)
        self.spans = []  # (замечание, слово, начало, конец) орфографических замечаний
        for m in matches:
            a, b = self.nbh(m)
            if m["rule"]["id"] == SPELL:
                self.spans.append((m, text[a:b], a, b))
        self.pairs = [  # соседние отмеченные слова через пробел: Безоб Разие
            (x, y) for x, y in itertools.pairwise(self.spans) if text[x[3] : y[2]] == " "
        ]
        cands = candidates(text, self.spans, self.pairs)
        self.ok = oracle(sorted(cands)) if cands else {}
        # слова документа с заглавной буквы, для имён
        self.doc = whole if whole and len(whole) >= len(text) else text
        caps = [
            (c.group(), sentence_start(self.doc, c.start()))
            for c in CAPWORD.finditer(self.doc)
            if c.group()[0].isupper()
        ]
        self.forms = collections.Counter(w for w, _ in caps)
        self.mid = {w for w, start in caps if not start}
        self.longer = None  # слова для completes(), собираются на первом оборванном слове

    def bounds(self, m):
        """Начало и конец замечания в символах text."""
        return self.idx[m["offset"]], self.idx[m["offset"] + m["length"]]

    def nbh(self, m):
        """Вернуть U+2011 в варианты исправления; -> bounds(m)."""
        a, b = self.bounds(m)
        if NBH in self.orig[a:b]:
            for r in m["replacements"]:
                r["value"] = r["value"].replace("-", NBH)
        return a, b

    def completes(self, w):
        """w — начало более длинного слова: из этого текста (Брумзил… / Брумзиллоп), запомненного имени или списка speller."""
        lw = w.lower()
        if self.longer is None:
            self.longer = (
                {v.lower() for v in CAPWORD.findall(self.doc)}
                | {k.lower() for k in (NAMES.known() if "names" in self.on else ())}
                | custom_words()
            )
        if any(len(v) > len(lw) and v.startswith(lw) for v in self.longer):
            return True
        found = WORDLIST.extends(w) or WORDLIST.extends(lw)
        return found if found is not None else any(self.ok.get(lw + t) for t in CUT_TAILS)

    def name_count(self, w):
        return max(sum(n for v, n in self.forms.items() if family(v, w)), 1)


def candidates(text, spans, pairs):
    """Слова для оракула: нормализованные формы отмеченных слов и склейки соседних."""
    cands = set()
    for m, w, a, b in spans:
        for c in expressive(w):  # формы заикания: правило 2 снимает замечание или даёт подсказку
            cands.add(c)
            if "-" in c:
                cands.update(p for p in c.split("-") if p)  # Ха-ха-ха-а -> части Ха-ха-ха
        if "-" in w:
            cands.update(p for p in w.split("-") if p)
            cands.add(w.replace("-", ""))
        if RUN.search(w):
            cands.update(unstretch(w, k)[0] for k in (1, 2))
        if cut(text, w, b) and not WORDLIST.available():
            cands.update(w.lower() + t for t in CUT_TAILS)  # «Преветь» с заглавной проходит
    cands.update(x[1] + y[1].lower() for x, y in pairs)
    return cands


def any_rule(ck, m):
    """Решение для замечания любого правила, до остальных шагов; None — шаг не решил."""
    a, b = ck.bounds(m)
    # обрывок-запинка: правило V.А читает его как вольт-ампер, speller — как опечатку
    if stammer(ck.text, a, b):  # без ключа не снимается, а становится подсказкой стиля
        return ("drop" if "stammer" in ck.on else "style"), "stammer"
    if "concessive" in ck.on and m["rule"]["id"] == "CONFUSION_RULE_НИ_НЕ" and concessive(ck.text, a):
        return "drop", "concessive"
    # снимается везде, и в авторском тексте тоже: текст от первого лица от него не отделить, разметка речи тут не поможет
    if m["rule"]["id"] in ("RU_NONSTANDARD", "talk") or slang(m):
        if "nonstandard" in ck.on:
            return "drop", "nonstandard"
        if slang(m):  # LT шлёт его как опечатку: без ключа — замечание стиля, как RU_NONSTANDARD
            return "style", "nonstandard"
    if m["rule"]["id"] == "AllCaps":
        return ("drop", "caps") if "caps" in ck.on else ("style", "caps")
    # паразиты в речи героя — приём, а автора от героя в тексте от первого лица не отличить: снимаются везде
    if "fillers" in ck.on and m["rule"]["id"] in FILLERS:
        return "drop", "fillers"
    return None


def slang(m):
    """Просторечие или жаргон из replace.txt LT: ошибки из списка убраны при сборке (rules.py, REPLACE_DROP)."""
    msg = m.get("message", "")
    return m["rule"]["id"] == "RU_SIMPLE_REPLACE" and ("— просторечие" in msg or msg == "Жаргон")


def crosses(ck, m):
    """Грамматика/стиль поперёк речи и авторского текста сравнивает несвязанные слова."""
    if m["rule"].get("category", {}).get("id") in BOUNDARY_OK or m["rule"]["id"] in BOUNDARY_RULES:
        return False
    a, b = ck.bounds(m)
    # и «— Да, ты прав, — хоть я…»: говорит один, но для LT пауза с тире делит два предложения
    return len({ck.kind[i] for i in range(a, b) if ck.text[i].isalpha()}) > 1 or bool(
        ck.kind[a] == SPEECH and DASH.search(ck.text, a, b)
    )


def spell_decision(ck, m, w, a, b, seen):
    """Решение по орфографическому замечанию на слово w (правила 1–9 политики, первое сработавшее);
    None — оставить как есть. seen: сюда дописываются встречи кандидатов в имена."""
    text, kind, ok, on = ck.text, ck.kind, ck.ok, ck.on
    reps = [r["value"] for r in m["replacements"]]
    parts = w.split("-")
    # подсказка LT только в другом регистре (по-Лавкрафтовски -> по-лавкрафтовски): части по отдельности speller
    # примет, а слово целиком есть лишь в этом регистре
    case_only = bool(reps) and reps[0] != w and reps[0].lower() == w.lower()
    if case_only or yo_error(w, reps) or ("-" in w and any(p.lower() in PARTICLES for p in parts[1:])):  # 1
        return "keep", "guard"
    # сжатая форма словарная целиком или, как составное правила 3, по частям: Ну-ну-ну-у -> Ну-ну-ну
    good = [
        c
        for c in expressive(w)
        if ok.get(c) or ("compound" in on and "-" in c and all(len(p) >= 2 and ok.get(p) for p in c.split("-")))
    ]
    if good:  # 2: без ключа — подсказка стиля, словарная форма первым вариантом (Не-е-ет -> Нет)
        if "stretch" in on:
            return "drop", "stretch"
        m["replacements"] = [{"value": good[0]}] + [r for r in m["replacements"] if r["value"] != good[0]]
        return "style", "stretch"
    if "compound" in on and "-" in w and all(len(p) >= 2 and ok.get(p) for p in parts):  # 3
        return "drop", "compound"
    if "split" in on and "-" in w and ok.get(w.replace("-", "")):  # 4
        return ("drop", "split") if kind[a] in QUOTED else ("style", "split")
    if RUN.search(w) and any(ok.get(unstretch(w, k)[0]) for k in (1, 2)):  # 5
        if "stretch_hint" in on:
            k = 1 if ok.get(unstretch(w, 1)[0]) else 2
            m["replacements"].insert(0, {"value": unstretch(w, k)[1]})
        return (
            "keep",
            "stretch-hint",
        )  # и без подсказки: растяжка не должна стать «именем»
    if "cut" in on and cut(text, w, b) and ck.completes(w):  # 6
        return ("drop", "cut") if kind[a] in QUOTED else ("style", "cut")
    if kind[a] == TITLE or (
        kind[a] == TITLE1 and not any(dist(r, w) <= 1 for r in reps)
    ):  # 7 (без titles названий в разметке нет)
        return "style", "title"
    if not w[0].isupper():
        return None
    n = ck.name_count(w)
    if "variant" in on:
        # 8: близкое написание весомее (Брумзилоп против Брумзиллоп) -> опечатка, предложить его; вес — встречи
        # в документе или в памяти, что больше (память уже содержит встречи этого документа); соседи вроде
        # «Брумти Тумти» — одно имя
        mem = "names" in on

        def weight(v):
            return max(ck.name_count(v), NAMES.seen(v)) if mem else ck.name_count(v)

        mine = weight(w)
        variants = [
            v
            for v in set(ck.forms) | (NAMES.known() if mem else set())
            if close(v, w) and f"{v} {w}" not in ck.doc and f"{w} {v}" not in ck.doc and weight(v) > mine
        ]
        if variants:
            v = min(variants, key=lambda v: (dist(v, w), -ck.forms[v]))
            if v not in reps:
                m["replacements"].insert(0, {"value": v})
            return "keep", "name-variant"
    if "names" not in on:
        return None
    # 9: имя — встречается в середине предложения и повторяется
    if reps and dist(reps[0], w) == 1 and WORDLIST.has(reps[0]):
        # LT предлагает словарное имя на букву дальше (Наташю -> Наталю): опечатка, не новое имя; с заглавной
        # в словаре хранятся только имена (Стол нет, есть стол), а LT пишет подсказку в регистре слова
        return None
    evidence = any(family(v, w) for v in ck.mid)
    if not sentence_start(text, a):
        seen.append((w, sentence_of(text, a), window(text, a, b)))
    if evidence and (n >= 2 or NAMES.seen(w) >= 3):
        return "style", "name"
    return None


def own_matches(text, matches, on):
    """Свои замечания прокси: непарные «» и «» внутри «», кроме мест с замечанием LT о кавычках."""
    lt_quotes = [
        (m["offset"], m["offset"] + m["length"])
        for m in matches
        if QUOTE_RULES & {m["rule"]["id"], m["rule"].get("category", {}).get("id")}
    ]
    out = []
    for i in unpaired(text) if "guillemets" in on else ():
        o = u16(text, i)
        if not any(a <= o < b for a, b in lt_quotes):
            out.append(own_match(text, i, GUILLEMETS, "Непарная кавычка"))
    for pair in nested(text) if "nested" in on else ():
        for i, repl in zip(pair, "„“"):
            o = u16(text, i)
            if not any(a <= o < b for a, b in lt_quotes):
                out.append(own_match(text, i, NESTED, "Внутренние кавычки — „лапки“", repl))
    return out


def filter_matches(text, orig, matches, whole, on, learn=False, own=True):
    """Вернуть (оставленные замечания, Counter решений). text: нормализованный текст запроса; orig: до замены
    U+2011; whole: весь документ, если известен (имена считаются по нему); on: включённые ключи RULES;
    learn: записывать кандидатов в имена (только запросы расширения: тесты не должны засорять память);
    own: добавлять свои замечания прокси (не для кусков allButTextLevelOnly: кусок может разрезать абзац,
    а запрос textLevelOnly той же сессии со всем документом их и так покажет)."""
    ck = Check(text, orig, matches, whole, on)
    decision = {}  # id(замечания) -> (действие, причина)
    for m in matches:
        d = any_rule(ck, m)
        if d:
            decision[id(m)] = d
    crossing = [(m, *ck.bounds(m)) for m in matches if "dialogue" in on and id(m) not in decision and crosses(ck, m)]
    rechecked = []
    if crossing:
        try:
            rechecked = recheck(text, ck.kind, crossing)
            for m, a, b in crossing:
                decision[id(m)] = ("drop", "dialogue-boundary")
            for m in rechecked:
                ck.nbh(m)
                decision[id(m)] = ("keep", "segment")
        except (
            OSError,
            ValueError,
            KeyError,
        ) as e:  # лучше оставить замечания, чем потерять настоящую ошибку
            log(f"recheck не удался: {e}")
    for x, y in ck.pairs:  # 0: Безоб Разие, Люци Фер
        if "split" in on and ck.ok.get(x[1] + y[1].lower()):
            d = ("drop", "space-split") if ck.kind[x[2]] in QUOTED else ("style", "space-split")
            decision[id(x[0])] = decision[id(y[0])] = d
    seen = []
    for m, w, a, b in ck.spans:
        if id(m) not in decision:
            d = spell_decision(ck, m, w, a, b, seen)
            if d:
                decision[id(m)] = d
    if seen and learn:
        NAMES.add(seen)

    stats = collections.Counter()
    kept = []
    for m in matches + rechecked:
        act, why = decision.get(id(m), ("keep", ""))
        if act == "style":
            soften(m, NOTES.get(why, ""))
        if act != "drop":
            kept.append(m)
        stats[f"{key(m)} {act}{' ' + why if why else ''}"] += 1
    if own:
        for m in own_matches(text, matches, on):
            kept.append(m)
            stats[f"{m['rule']['id']} add"] += 1
    kept.sort(key=lambda m: m["offset"])
    return kept, stats


def recheck(text, kind, crossing):
    """Проверить части речи и авторского текста под замечаниями, пересекающими границу, по отдельности и только
    этими правилами; вернуть замечания внутри одной части со смещениями в `text`."""
    segs = {}  # исходные (начало, конец) каждого участка речи/автора, которого касается пересекающее замечание
    for m, a, b in crossing:
        ls = text.rfind("\n", 0, a) + 1
        le = text.find("\n", b)
        le = len(text) if le < 0 else le
        s = ls
        for i in range(ls + 1, le + 1):
            if i == le or kind[i] != kind[s]:
                x = text[s:i]
                lead = len(x) - len(x.lstrip(" \t,—–"))
                x = x.rstrip(" \t,—–")
                if s + lead < i and s < b and i > a and any(c.isalpha() for c in x[lead:]):
                    segs[(s + lead, s + len(x))] = True
                s = i
    segs = sorted(segs)
    parts, starts, pos = [], [], 0
    for a, b in segs:
        starts.append(pos)
        parts.append(text[a:b])
        pos += b - a + 2
    rt = "\n\n".join(parts)  # отдельные абзацы: LT проверяет каждый сам по себе
    rules = sorted({m["rule"]["id"] for m, _, _ in crossing})
    body = urllib.parse.urlencode(
        {
            "text": rt,
            "language": "ru-RU",
            "level": "picky",
            "enabledOnly": "true",
            "enabledRules": ",".join(rules),
        }
    ).encode()
    ck = "recheck:" + hashlib.sha1(body).hexdigest()
    data = CACHE.get(ck)
    if data is None:
        status, _, data = lt("/v2/check", body)
        if status != 200:
            raise OSError(f"recheck: HTTP {status}")
        CACHE.put(ck, data)
    ridx, out = u16map(rt), []
    for m in json.loads(data)["matches"]:
        a, b = ridx[m["offset"]], ridx[m["offset"] + m["length"]]
        j = max(k for k, s in enumerate(starts) if s <= a)
        oa, ob = segs[j][0] + a - starts[j], segs[j][0] + b - starts[j]
        m["offset"], m["length"] = u16(text, oa), u16(text, ob) - u16(text, oa)
        c = max(oa - 40, 0)
        m["context"] = {
            "text": text[c : ob + 40],
            "offset": u16(text, oa) - u16(text, c),
            "length": m["length"],
        }
        out.append(m)
    return out


# ---------- HTTP ----------


def parse_check(body):
    """-> (пары формы с заменённым U+2011, нормализованный текст, исходный текст) или None, если запрос не разобран."""
    pairs = urllib.parse.parse_qsl(body.decode("utf-8"), keep_blank_values=True)
    out, text, orig = [], None, None
    for k, v in pairs:
        if k == "text":
            orig, text, v = v, v.replace(NBH, "-"), v.replace(NBH, "-")
        elif k == "data":
            d = json.loads(v)
            if "text" in d:
                orig = d["text"]
                d["text"] = text = orig.replace(NBH, "-")
            else:  # annotation: смещения учитывают и разметку; сама разметка не трогается
                orig = "".join(p.get("text", p.get("markup", "")) for p in d.get("annotation", []))
                for p in d.get("annotation", []):
                    if "text" in p:
                        p["text"] = p["text"].replace(NBH, "-")
                text = "".join(p.get("text", p.get("markup", "")) for p in d.get("annotation", []))
            v = json.dumps(d, ensure_ascii=False)
        out.append((k, v))
    return (out, text, orig) if text is not None else None


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def reply(self, status, headers, data):
        self.send_response(status)
        for k, v in headers:
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def forward(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        if (
            self.command == "POST"
            and self.path.split("?")[0] == "/v2/check"
            and "x-www-form-urlencoded" in self.headers.get("Content-Type", "")
        ):
            return self.check(body, hdrs)
        try:
            self.reply(*lt(self.path, body, self.command, hdrs))
        except OSError as e:
            self.reply(502, [], f"proxy: LanguageTool недоступен: {e}".encode())

    def check(self, body, hdrs):
        try:
            parsed = parse_check(body)
        except ValueError:
            parsed = None
        form = dict(parsed[0]) if parsed else {}
        fwd = urllib.parse.urlencode(parsed[0]).encode() if parsed else body
        ck = hashlib.sha1(
            urllib.parse.urlencode([p for p in parsed[0] if p[0] != "textSessionId"]).encode() if parsed else body
        ).hexdigest()
        sid, mode = form.get("textSessionId"), form.get("mode", "")
        if parsed and sid and mode == "textLevelOnly":
            SESSIONS.put(sid, parsed[1])
        hit = CACHE.get(ck)
        try:
            status, headers, data = hit or lt(self.path, fwd, "POST", hdrs)
        except OSError as e:
            return self.reply(502, [], f"proxy: LanguageTool недоступен: {e}".encode())
        if status == 200 and not hit:
            CACHE.put(ck, (status, headers, data))
        out, note = data, ""
        forced = self.headers.get("X-Proxy-Mode")  # для regress.py: режим без правки config.ini
        try:
            preset, on = header_mode(forced) if forced else config()
        except (
            ValueError,
            configparser.Error,
        ) as e:  # тест с опечаткой в заголовке должен упасть, а не пройти молча
            return self.reply(400, [], f"proxy: X-Proxy-Mode не принят: {e}".encode())
        if status == 200 and parsed:
            try:
                resp = json.loads(data)
                if resp.get("language", {}).get("code", "").startswith("ru"):
                    resp["matches"], stats = filter_matches(
                        parsed[1],
                        parsed[2],
                        resp["matches"],
                        SESSIONS.get(sid) if sid else None,
                        on,
                        bool(sid),
                        mode != "allButTextLevelOnly",
                    )
                    out = json.dumps(resp, ensure_ascii=False).encode()
                    note = " | " + ", ".join(f"{k} ×{n}" for k, n in sorted(stats.items()))
            except Exception as e:  # noqa: BLE001 — fail open: пользователь всё равно получает результат LT
                # только тип и строка: текст исключения может содержать кусок текста пользователя
                note = f" | FAIL OPEN: {type(e).__name__} в строке {traceback.extract_tb(e.__traceback__)[-1].lineno}"
                out = data
        log(f"check {mode or '-'} {preset} len={len(parsed[1]) if parsed else '?'}{' cached' if hit else ''}{note}")
        self.reply(status, headers, out)

    do_GET = do_POST = do_OPTIONS = do_HEAD = do_PUT = do_DELETE = forward

    def log_message(self, fmt, *args):
        pass  # check() пишет свою строку; остальные запросы неинтересны


if __name__ == "__main__":
    # самопроверка
    assert expressive("П-прямо") == ["Прямо"] and "пожалуйста" in expressive("п-п-пожалуйста")
    assert "Конечно" in expressive("Ко-ко-конечно") and "Нет" in expressive("Не-е-ет")
    assert "Неет" in expressive("Нее-ет") and "Нет" not in expressive("Нее-ет")
    assert unstretch("Нееет", 1) == ("Нет", "Не-е-ет") and unstretch("дааа", 1) == (
        "да",
        "да-а-а",
    )
    assert dist("Брумзиллоп", "Брумзилоп") == 1 and dist("ab", "ba") == 1
    assert family("Брумзиллоп", "Брумзиллопом") and not family("Брумзиллоп", "Брумзилоп")
    assert yo_error("темно-синий", ["тёмно-синий"]) and not yo_error("чел-овек", ["человек"])
    t = "Он ушёл. Брумти — друг. — Привет, Брумти! — Он сказал: «Мир»."
    assert sentence_start(t, t.index("Брумти")) and not sentence_start(t, t.rindex("Брумти"))
    assert sentence_start(t, t.index("Мир")) and sentence_start(t, t.index("Привет"))
    t = "— Речь, — сказал он, — ещё речь. — Он ушёл. — Снова.\nАвтор шёл в «Брумзи кул» и сказал: «Привет, мир»."
    k = regions(t)
    assert [k[t.index(s)] for s in ("Речь", "сказал", "ещё", "Он", "Снова", "Автор", "Брумзи", "Привет")] == [
        1,
        0,
        1,
        0,
        1,
        0,
        2,
        1,
    ] and regions("в «Превет»")[4] == 3
    t = "— Речь, — сказал он. В «Брумзи кул» и «Привет, мир», — сказал он."
    k = regions(t, dialogue=False)
    assert k[t.index("Брумзи")] == TITLE and not k[t.index("Речь")] + k[t.index("мир")]
    assert not any(regions(t, titles=False)[t.index("Брумзи") :][:10])
    k = regions("— П, — а. — П, — а.")
    assert [k[i] for i in (2, 7, 12, 17)] == [SPEECH, UNKNOWN, SPEECH, UNKNOWN]
    t = "— Ты прав, — хоть я и не уверен, — сказал он. — Да, — я кивнул. — Иди.\n— Ну, — Семён всё глядя."
    k = regions(t)
    assert [k[t.index(s)] for s in ("Ты", "хоть", "сказал", "Да", "кивнул", "Иди", "Ну", "Семён")] == [
        SPEECH,
        SPEECH,
        AUTHOR,
        SPEECH,
        AUTHOR,
        SPEECH,
        SPEECH,
        UNKNOWN,
    ]
    assert voice("задумчиво произнёс Семён") == voice("Он потряс бутылкой") == AUTHOR and voice("или нет") == UNKNOWN
    assert cut("не тобо… да", "тобо", 7) and cut("пон...", "пон", 3) and not cut("тобо, да", "тобо", 4)
    with tempfile.TemporaryDirectory() as tmp:
        wl = Wordlist(os.path.join(tmp, "w.txt"))
        assert wl.extends("под") is None and not wl.available()
        with open(wl.path, "wb") as f:
            f.write(
                "\n".join(
                    sorted(
                        [
                            "Свен+A",
                            "а+B",
                            "подиум+A",
                            "подум+A",
                            "подум+C",
                            "подумать+A",
                            "тобой+A",
                            "я+Z",
                        ],
                        key=str.encode,
                    )
                ).encode()
            )
        assert wl.extends("подум") and wl.extends("тобо") and wl.extends("Све") and wl.extends("а") is False
        assert (
            not wl.extends("Свен") and not wl.extends("подумать") and not wl.extends("я") and not wl.extends("превет")
        )
        assert wl.mm
        wl.mm.close()
    assert u16map("a😀b") == [0, 1, 1, 2, 3] and u16("a😀b", 2) == 3
    t = "Ва… ва… ваше"
    assert stammer(t, 0, 2) and stammer(t, 4, 6) and not stammer("Он ушёл… Ваня", 3, 7) and not stammer("Ну… да", 0, 2)
    # slang: просторечие и жаргон replace.txt — да; его опечатки и сокращения, другие правила — нет
    sr = {"id": "RU_SIMPLE_REPLACE"}
    assert slang({"rule": sr, "message": "«чё» — просторечие, исправление: «что»"}) and slang(
        {"rule": sr, "message": "Жаргон"}
    )
    assert not slang({"rule": sr, "message": "Опечатка"}) and not slang({"rule": {"id": "X"}, "message": "Жаргон"})
    t = "Что бы она ни хотела мне сказать, я не узнаю. Она ни хотела"
    assert (
        concessive(t, 11)
        and not concessive(t, t.rfind("ни"))
        and concessive("Как бы он ни", 10)
        and not concessive("Бы она ни", 7)
    )
    assert concessive("О чём бы она ни", 13) and concessive("Что бы, честно говоря, она ни", 27)
    assert not concessive("Кто бы мог подумать, что она ни", 29) and not concessive("Что бы, сказал он, она ни", 23)
    t = "Что бы, конечно, кажется, она ни"
    assert concessive(t, len(t) - 2) and concessive("Я сделал всё, что она ни", 22)
    assert not concessive("Я сделал всё, что она сказала, но она ни", 38)
    assert unpaired("«привет и ушёл") == [0] and unpaired("привет» и ушёл") == [6]
    assert unpaired("«да» и «нет»") == unpaired("«Первый.\n«Второй.»") == unpaired("«а «б» в»") == []
    assert unpaired("«Первый.\nВторой.") == [0] and unpaired("«а «б» в") == [0]
    assert nested("«а «б» в»") == [(3, 5)] and nested("«а «б»?»") == nested("«а» «б»") == nested("«а\n«б»") == []
    assert sentence_of("Раз. Два три! Четыре", 6) == "Два три!"
    t = "Раз. Потом Брумзик ушёл домой"
    assert window(t, 11, 18) == "Потом Брумзик ушёл" and window("Брумзик.", 0, 7) == "Брумзик"
    assert window("Вот. Потом Брумзик ушёл и сел", 11, 18) == window(t, 11, 18)  # правка вдалеке: та же встреча
    ann = json.dumps({"annotation": [{"text": "а‑б"}, {"markup": "<b>"}]}, ensure_ascii=False)
    r = parse_check(urllib.parse.urlencode({"data": ann}).encode())
    assert r
    f, t, o = r
    assert (t, o) == ("а-б<b>", "а‑б<b>") and json.loads(f[0][1])["annotation"][0]["text"] == "а-б"
    assert parse_config("") == ("neutral", PRESETS["neutral"])
    assert parse_config("[proxy]\nmode = prose ; комментарий\n[rules]\ntitles = no\n") == (
        "prose",
        PRESETS["prose"] - {"titles"},
    )
    assert parse_config("[rules]\nnames = yes\nnested = off")[1] == PRESETS["neutral"] - {"nested"} | {"names"}
    for bad in ("[proxy]\nmode = poems", "[rules]\nnamez = yes", "[rules]\nnames = да"):
        try:
            parse_config(bad)
            assert False, bad
        except ValueError:
            pass
    assert header_mode("prose") == ("prose", PRESETS["prose"])
    assert header_mode("neutral names=yes nested=no")[1] == PRESETS["neutral"] - {"nested"} | {"names"}
    for bad in ("", "poems", "prose namez=no", "prose titles", "prose [proxy]"):
        try:
            header_mode(bad)
            assert False, bad
        except ValueError, configparser.Error:
            pass
    with tempfile.TemporaryDirectory() as tmp:
        CONFIG_real, CONFIG = CONFIG, os.path.join(tmp, "config.ini")
        log_real, log = (
            log,
            lambda s: None,
        )  # строки о проверочных файлах не нужны в журнале
        assert config()[0] == "neutral"  # файла нет
        with open(CONFIG, "w", encoding="utf-8") as f:
            f.write("[proxy]\nmode = prose\n")
        assert config() == ("prose", PRESETS["prose"])
        with open(CONFIG, "w", encoding="utf-8") as f:
            f.write("[proxy\nmode = prose\n")
        os.utime(CONFIG, ns=(1, 1))  # другой mtime, даже если запись попала в тот же тик
        assert config()[0] == "neutral"  # ошибка в файле
        with open(CONFIG, "w", encoding="utf-8-sig") as f:
            f.write("[proxy]\nmode = prose\n")
        os.utime(CONFIG, ns=(2, 2))
        assert config()[0] == "prose"  # файл с BOM
        CONFIG, log = CONFIG_real, log_real
    # filter_matches без сети, с поддельным LT: эмодзи перед замечанием сдвигает смещения UTF-16 на единицу
    lt_real, calls = lt, []

    def fake_lt(path, body, *_):
        calls.append(body)
        text = urllib.parse.parse_qs(body.decode())["text"][0]
        if text == "Зербокс":
            return 500, [], b""
        if text == "Ъ\nЪъ\nПрямо":  # как настоящий LT: одно замечание на две строки
            return (
                200,
                [],
                json.dumps({"matches": [{"offset": 0, "length": 4}]}).encode(),
            )
        lines = text.split("\n")  # поддельный speller знает только «Прямо»
        bad = [
            {"offset": u16(text, sum(len(x) + 1 for x in lines[:i])), "length": len(x)}
            for i, x in enumerate(lines)
            if x != "Прямо"
        ]
        return 200, [], json.dumps({"matches": bad}).encode()

    lt = fake_lt  # pyright: ignore[reportAssignmentType]
    t = "😀 Он сказал «П-прямо сюда"
    kept, st = filter_matches(
        t,
        t,
        [{"offset": 14, "length": 7, "rule": {"id": SPELL}, "replacements": []}],
        None,
        PRESETS["prose"],
    )
    assert [(m["rule"]["id"], m["offset"], m["context"]["offset"]) for m in kept] == [(GUILLEMETS, 13, 13)], kept
    assert st[f"{SPELL} drop stretch"] == 1
    # без ключа stretch (neutral): подсказка стиля с словарной формой первой; смешанная форма Нее-ет остаётся ошибкой
    kept, _ = filter_matches(
        t,
        t,
        [{"offset": 14, "length": 7, "rule": {"id": SPELL}, "replacements": [{"value": "Ппрямо"}]}],
        None,
        PRESETS["neutral"],
        own=False,
    )
    assert kept[0]["rule"]["issueType"] == "style" and kept[0]["replacements"][0]["value"] == "Прямо", kept
    assert kept[0]["message"].startswith(NOTE_STRETCH), kept
    t2 = "😀 Он сказал «Нее-ет сюда"
    kept, _ = filter_matches(
        t2,
        t2,
        [{"offset": 14, "length": 6, "rule": {"id": SPELL}, "replacements": []}],
        None,
        PRESETS["neutral"],
        own=False,
    )
    assert kept and kept[0]["rule"].get("issueType") != "style", kept
    assert oracle(["Ъ", "Ъъ", "Прямо"]) == {"Ъ": False, "Ъъ": False, "Прямо": True}
    # без ключа names память имён не пополняется
    NAMES_real, added = NAMES, []
    NAMES = types.SimpleNamespace(
        add=added.append, known=set, seen=lambda w: 0
    )  # настоящая память записала бы names.json
    t = "Он видел Брумзик. Потом видел Брумзик."
    for on, want in ((PRESETS["prose"], 1), (PRESETS["neutral"], 0)):
        added.clear()
        filter_matches(
            t,
            t,
            [{"offset": a, "length": 7, "rule": {"id": SPELL}, "replacements": []} for a in (9, 30)],
            None,
            on,
            learn=True,
        )
        assert len(added) == want, (sorted(on), added)
    # 8: опечатка по всему тексту, правильное имя весомее в памяти -> предложить его; наоборот — нет
    mem = {"Брумзиллоп": 9, "Брумзилоп": 2}
    NAMES.known, NAMES.seen = lambda: set(mem), lambda w: mem.get(w, 0)
    for t, w, want in (
        ("Он видел Брумзилоп. Потом видел Брумзилоп.", "Брумзилоп", "Брумзиллоп"),
        ("Он видел Брумзиллоп.", "Брумзиллоп", None),
    ):
        ms = [
            {"offset": a, "length": len(w), "rule": {"id": SPELL}, "replacements": []}
            for a in (m.start() for m in re.finditer(w + r"\b", t))
        ]
        kept, _ = filter_matches(t, t, ms, None, PRESETS["prose"])
        assert [(m["replacements"] or [{}])[0].get("value") for m in kept] == [want] * len(ms), (t, kept)
    NAMES = NAMES_real
    assert close("Брумзилоп", "Брумзиллоп") and close("Брумит", "Брумти")
    assert not close("Брумзиллопом", "Брумзиллоп") and not close("Зербокс", "Брумти")
    # память имён: срок, забывание по словарю, правка names.json руками
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "w.raw"), "wb") as f:
            f.write("Брумзик+A\nБрумти+A\nБрумтия+B\nбрумзик+L\n".encode())
        wl = Wordlist(os.path.join(tmp, "w.raw"))
        assert wl.has("Брумти") and wl.has("брумзик") and not wl.has("Брумт")
        assert not wl.has("Зербокс") and not wl.has("Брумтиюшка")
        assert wl.mm
        wl.mm.close()  # Windows не удалит открытый файл
        assert Wordlist(os.path.join(tmp, "нет")).has("Брумзик") is None
        nm = Names(tmp)
        nm.add([(w, "", w + str(i)) for w in ("Брумзиллоп", "Брумзилоп", "Зербокс") for i in range(3)])
        assert nm.known() == {"Брумзиллоп", "Брумзилоп", "Зербокс"}
        nm.forget(lambda k: k == "Брумзиллоп")
        assert nm.known() == {"Зербокс"}
        with open(nm.file, encoding="utf-8") as f:
            d = json.load(f)
        d["Зербокс"]["t"] -= NAMES_TTL + 1
        d["Тумти"] = {"s": ["a", "b", "c"], "ex": ""}
        with open(nm.file, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.utime(nm.file, ns=(0, os.stat(nm.file).st_mtime_ns + 1))  # mtime мог не смениться за ту же миллисекунду
        assert nm.known() == {"Тумти"}, nm.d
    for _ in range(2):  # неудачный запрос к оракулу не повторяется в течение минуты
        try:
            oracle(["Зербокс"])
            assert False
        except OSError:
            pass
    assert sum(b"%D0%97%D0%B5%D1%80" in b for b in calls) == 1
    lt = lt_real
    WORDS.clear()
    FAILED.clear()
    if os.environ.get("SELFCHECK"):  # CI: только самопроверка, без сервера
        sys.exit(0)
    NAMES.forget(  # rpdict пересоздаёт прокси: слова, вошедшие в словарь, и их опечатки забываются здесь
        lambda k: k.lower() in custom_words() or WORDLIST.has(k) or WORDLIST.has(k.lower())
    )
    threading.Thread(target=watch_lt, daemon=True).start()
    log(f"прокси на :{PORT} -> {LT_URL}")
    ThreadingHTTPServer(("", PORT), Proxy).serve_forever()
