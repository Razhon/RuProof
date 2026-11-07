#!/usr/bin/env python3
"""Вопросы rpdict о новом слове: варианты склонения по аналогии (forms.Index), меню, правка форм по ячейкам.

запуск: dialog.py — только самопроверка (модуль импортирует words.py)
"""

import builtins
import sys
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import forms
import store
from forms import Form
from store import Block

try:
    import readline  # noqa: F401  input() редактирует строку по символам: без него Backspace терминала стирает байт кириллической буквы
except ImportError:
    pass

YES = ("д", "y", "да", "yes")


class Option(NamedTuple):
    """Вариант меню pick: kind — para (парадигма), form (форма известного слова) или indecl."""

    kind: str
    lemma: str
    cls: str
    forms: list[Form]
    desc: str


class Choice(Enum):
    """Ответ на «как добавить слово» без размеченных значений."""

    SPELLING = "только орфография"
    SKIP = "пропустить"


def cased(word, form):
    """Перенести регистр букв word на form по их общему префиксу (ФСБшника -> ФСБшников, Брум)."""
    k = 0
    while k < min(len(word), len(form)) and word[k].lower() == form[k]:
        k += 1
    return word[:k] + form[k:]


def scripted(path):
    """rpdict -a: ответы из файла, по строке на вопрос (пустая = Enter), без терминала; вопрос и ответ печатаются."""
    left = Path(path).read_text(encoding="utf-8-sig").splitlines()

    def inp(p=""):
        if not left:
            # до записи: файлы не меняются
            sys.exit(f"\n! ответы кончились на вопросе: {p.strip()}")
        print(p + left[0])
        return left.pop(0)

    builtins.input = inp
    return left


def ask(prompt):
    """Ответ без пробелов по краям. Ctrl+D/Ctrl+Z — EOFError: его ловят циклы по словам (add_spelling, migrate)."""
    while True:
        a = input(prompt).strip()
        try:
            a.encode("utf-8")
            return a
        # Backspace в терминале может разрезать кириллическую букву пополам
        except UnicodeEncodeError:
            print("   в ответе испорченный символ, введите заново")


def confirm(q, default):
    """Вопрос да/нет; подсказка [Д/н] или [д/Н] дописывается по default — ответу на Enter."""
    return ask(f"{q} [{'Д/н' if default else 'д/Н'}]: ").lower() in (("", *YES) if default else YES)


def show_table(c, fl):
    """Напечатать все формы с отступом под меню."""
    print("      " + "\n      ".join(x for x in forms.table(c, fl, full=True) if x))


def covers(fl: list[forms.Form], words):
    """Все введённые слова есть среди форм варианта (без учёта регистра)."""
    return {w.lower() for w in words} <= {f.lower() for f, _ in fl}


def short_neut(rows, words):
    """Краткие формы ср.р. на -о среди введённых слов (хуёво от хуёвый): они бывают ещё и наречием, как быстро."""
    need = {w.lower() for w in words}
    return sorted({r[0] for r in rows if r[-1] == "ADJ:Short:Neut" and r[0].endswith("о") and r[0].lower() in need})


def options(ix, word, preferred=None, top=3, listed=(), own=()):
    """Разные способы разметить word: [Option].
    listed: формы, которые должны подойти (migrate: мутированной, а не угаданная лемма); own: парадигмы слов-образцов пользователя."""
    # сама форма: в полугорящая видно горящая, в полугорить — нет
    cands = ix.guess(listed[0] if listed else word, top=10)
    if word[:1].isupper() and not preferred:
        # Магнусон: имя на -он (как Абдуханон) раньше нарицательных на -сон (лусон: Магнусна), которые даёт guess
        w = (listed[0] if listed else word).lower()
        cands = [
            (lem, p, 0)
            for lem, p, _ in ix.models(w.capitalize())
            if lem == w and ix.paras[p].cls.startswith(forms.PROPER)
        ] + cands
    if preferred:  # [(лемма, pid)]: догадка группы migrate или слово-образец пользователя — первыми
        cands = [(lem, p, 0) for lem, p in preferred] + [c for c in cands if c[:2] not in preferred]
    # форма известного слова (потрясши от потрясти) важнее новой угаданной парадигмы (потряснуть); образец пользователя остаётся первым
    cands = sorted(
        cands,
        key=lambda x: 0 if x[:2] in own else 1 if ix.lemma_known(x[0].lower(), ix.paras[x[1]].cls) else 2,
    )
    out, seen, warned = [], set(), set()
    for lem, pid, _ in cands:
        c = ix.paras[pid].cls
        fl = [(cased(word, f), t) for f, t in ix.forms(lem, pid)]
        lem = cased(word, lem)
        # мутировать как модифицировать: переходная парадигма рядом с известной непереходной
        own_para = (lem, pid) in own
        if ix.lemma_known(lem.lower(), c) and not own_para:
            if word[:1].isupper() and not c.startswith(forms.PROPER):
                continue  # Роза — имя, а не форма слова роза
            # теги должны подходить известному слову (вид, переходность): образец другого рода даёт неверную форму
            fields = {x for t in ix.lemma_tags(lem.lower(), c) for x in t.split(":")}
            need = set(listed) or {word}
            rows = [(f, t) for f, t in fl if f in need and set(t.split(":")) <= fields]
            if {f for f, _ in rows} != need:
                warned.add(lem)
                continue
            key = ("form", lem, tuple(rows))
            desc = f"форма известного слова «{lem}»: " + "; ".join(f"{f} — {forms.describe(t)}" for f, t in rows)
            fl = rows
            kind = "form"
        else:
            if c.startswith("NN:Anim:") and word[:1].isupper() and word[1:] == word[1:].lower():
                # Слендермен — имя персонажа (правила о запятой при обращении и о заглавных ищут NN:Name),
                # ФСБшник остаётся нарицательным
                c = "NN:Name:" + c.split(":")[2]
                fl = [(f, t.replace("NN:Anim:", "NN:Name:", 1)) for f, t in fl]
            if listed and not own_para and not covers(fl, listed):
                continue  # хуёво хуёвый: «как царёв» (хуёв, хуёва) теряет введённое хуёвый
            tbl = forms.table(c, fl)
            if not any(tbl):
                continue  # записи без падежей (несклоняемые имена): их покрывает вариант «н»
            key = (c, tuple(tbl))
            head = lem.rpartition("-")[0]
            # интернет-магазин
            keep = f", «{head}» не меняется" if head and all(f.startswith(head + "-") for f, _ in fl) else ""
            desc = f"как «{ix.sample(lem.lower(), pid)}»{keep} — {forms.label(c, fl)}\n      " + "\n      ".join(
                x for x in tbl if x
            )
            kind = "para"
            first = next((o for o in out if o[:3] == ("para", lem, c)), None)
            if first:  # варианты часто отличаются лишь несколькими строками (краткими формами): показываем только их
                norm = lambda line: " ".join(line.split())
                was = {norm(line) for line in forms.table(c, first.forms)}
                rows = [line for line in tbl if not line.startswith(" ")]
                diff = [line for line in rows if norm(line) not in was]
                if 0 < len(diff) < len(rows):
                    desc = (
                        desc.split("\n")[0]
                        + f"\n      как {out.index(first) + 1}, кроме:\n      "
                        + "\n      ".join([line for line in tbl if line.startswith(" ")] + diff)
                    )
        if key not in seen and fl:
            seen.add(key)
            # только по вписанному образцу (сирота): у папа и мама формы тоже одни, Маккенна не должна стать общего рода
            k = com_key(kind, lem, c, fl) if own_para else None
            if k is None or (twin := next((i for i, o in enumerate(out) if com_key(*o[:4]) == k), None)) is None:
                out.append(Option(kind, lem, c, fl, desc))
            else:  # сирота: м.р. и ж.р. с одними формами — один вариант общего рода
                o = out[twin]
                cc = f"NN:{k[1]}:Com"
                cfl = [(f, t.replace(f":{o.cls.split(':')[2]}:", ":Com:", 1)) for f, t in o.forms]
                out[twin] = o._replace(
                    cls=cc, forms=cfl, desc=o.desc.replace(forms.label(o.cls, o.forms), forms.label(cc, cfl), 1)
                )
        if kind == "para" and c == "V":
            out[-1:-1] = participles(ix, lem, pid, fl, set(listed) or {word}, seen)
        if len(out) >= top:
            break
    # говорим, только если ни один вариант не покрывает известное слово
    for lem in sorted(warned - {o.lemma for o in out}):
        print(f"! у известного слова «{lem}» такой формы не выходит: возможно, ошибка")
    return out


def com_key(kind, lem, c, fl):
    """Вариант существительного м.р. или ж.р. без рода: у двух половин слова общего рода (сирота) ключи равны."""
    p = c.split(":")
    if kind != "para" or p[0] != "NN" or p[2] not in ("Masc", "Fem"):
        return None
    return lem, p[1], frozenset((f, t.replace(f":{p[2]}:", ":Com:", 1)) for f, t in fl)


def both(fl: list[Form]) -> list[Form]:
    """Общий род (тег NN:…:Com) при записи: те же формы с тегами м.р. и ж.р., как у LT; остальное как есть."""
    return sorted({(f, t.replace(":Com:", g, 1)) for f, t in fl for g in (":Masc:", ":Fem:")})


def participles(ix, lem, pid, fl, need, seen) -> list[Option]:
    """Варианты «только причастие, без глагола» из глагольного варианта fl: полугорящая без глагола полугореть.
    Одна цепочка причастия (полные и краткие формы) с родными тегами PT, чтобы правила о причастных оборотах её видели;
    лемма, как у LT, — инфинитив. seen пополняется."""
    out = []

    def chain(t):
        return t.startswith("PT") and ":".join(t.split(":")[1:5])

    for ch in sorted({chain(t) for f, t in fl if f in need and chain(t)}):
        pfl = [(f, t) for f, t in fl if chain(t) == ch]
        nom = next((t for _, t in pfl if t.endswith(":Masc:Nom")), None)
        pkey = ("PT", tuple(pfl))
        # ебанутый ебануть: введён и инфинитив, причастие без глагола его потеряло бы
        if not nom or pkey in seen or not covers(pfl, need):
            continue
        seen.add(pkey)
        ex = ", ".join(dict.fromkeys(f for e in (":Masc:Nom", ":Fem:Nom", ":Masc:R") for f, t in pfl if t.endswith(e)))
        s = ix.sample(lem.lower(), pid)
        smp = next((f for f, t in ix.forms(s, pid) if t == nom), s)
        vb = [
            f
            for f, t in fl
            if t.startswith(("VB:Real", "VB:Fut"))
            and t.endswith(":Sin:P1")
            or t.startswith("VB:Past")
            and t.endswith(":Masc")
        ][:2]
        verb = f" вроде «{'», «'.join(vb)}»" if vb else ""
        # инфинитив и вид угаданы по образцу (ёбанный как накарябанный -> ёбать, сов.): показываем, р1 их правит
        asp = next((forms.ASPECTS[x] for x in nom.split(":") if x in forms.ASPECTS), "?")
        desc = (
            f"только причастие, без глагола: {ex}…\n"
            f"      (как «{smp}»; инф. «{lem}», {asp} вид; формы глагола{verb} не добавятся)"
        )
        out.append(Option("para", lem, "PT", pfl, desc))
    return out


GENDER = {"м": "Masc", "ж": "Fem", "с": "Neut", "мж": "Com"}  # мж: общий род (сирота, визави), см. both()


def edit(c: str, fl: list[forms.Form]) -> tuple[str, list[forms.Form]]:
    """Пройти показанные формы с вопросами падежей; Enter оставляет, '-' убирает, 'a/b' даёт варианты. -> (класс, формы)"""
    if c.split(":")[0] == "NN":
        c, fl = noun_kind(c, fl)
    mid = ""  # середина тега инфинитива (TRANS:PFV): ею заполняются пустые ячейки глагола
    if c in ("V", "PT"):  # у причастия без глагола вид тоже взят у образца
        fl, mid = verb_kind(fl)
    for title, test in forms.cells(c):
        fl = edit_cell(c, title, test, fl, mid)
    return c, both(fl)


def noun_kind(c: str, fl: list[forms.Form]) -> tuple[str, list[forms.Form]]:
    """Род и одушевлённость существительного: одеялка -> одеялко меняет род, теги должны измениться следом."""
    p = c.split(":")
    # и: имя (Лавкрафт по образцу агроландшафт): правила об обращении и заглавных ищут NN:Name
    a = ask(
        f"   род, одушевлённость [{forms.label(c, fl)[5:]}] (м/ж/с/мж = общий, о/н/и = имя; Enter = как есть): "
    ).lower()
    g = "Com" if {"м", "ж"} <= set(a) else next((GENDER[x] for x in a if x in GENDER), p[2])
    an = "Name" if "и" in a else "Anim" if "о" in a else "Inanim" if "н" in a else p[1]
    fl = [(f, ":".join(["NN", an, g] + t.split(":")[3:])) for f, t in fl]
    # В. зависит от одушевлённости: вижу Лавкрафта / вижу ландшафт (м.р. ед. и мн.)
    if (p[1] == "Inanim") != (an == "Inanim"):
        src = "Nom" if an == "Inanim" else "R"
        nums = {"PL", "Sin" if g == "Masc" else "PL"}
        fl = [(f, t) for f, t in fl if not (t.endswith(":V") and t.split(":")[3] in nums)] + [
            (f, t[: -len(src)] + "V") for f, t in fl if t.endswith(":" + src) and t.split(":")[3] in nums
        ]
    return f"NN:{an}:{g}", fl


def verb_kind(fl: list[forms.Form]) -> tuple[list[forms.Form], str]:
    """Вид и переходность глагола -> (формы, середина тега инфинитива для пустых ячеек)."""
    # шкериться — несов. вида, его образец опериться — сов.: настоящее время следует виду
    # вид инфинитива, а у причастия без глагола — его тегов
    asp = next(
        (
            x
            for _, t in sorted(fl, key=lambda r: not r[1].startswith("VB:INF"))
            for x in t.split(":")
            if x in forms.ASPECTS
        ),
        "",
    )
    # у 43 глаголов LT (дрочить, базлать) в теге пустая ячейка вместо вида и переходности: VB:Real::Sin:P3
    bare = not asp and all(t.split(":")[2:3] == [""] for _, t in fl)
    a = ask(f"   вид [{forms.ASPECTS.get(asp, '?')}] (с/н; Enter = как есть): ").lower()
    new = {"с": "PFV", "н": "IMPFV"}.get(a[:1], asp)
    if bare:
        return bare_kind(fl, new)
    if asp and new != asp:
        was, now = ("VB:Fut:", "VB:Real:") if new == "IMPFV" else ("VB:Real:", "VB:Fut:")
        moved = [(f, now + t[len(was) :] if t.startswith(was) else t) for f, t in fl]
        fl = [(f, ":".join(new if x == asp else x for x in t.split(":"))) for f, t in moved]
    # переходность тоже берётся у образца, а правила её видят (VB:IMP:TRANS:PFV); у непереходного нет страд. причастий
    # у 178 глаголов LT оба инфинитива (брызгать), у 124 ни одного (дождить): тогда тег некуда писать, вопроса нет
    trs = {x for _, t in fl if t.startswith("VB:INF") for x in t.split(":") if x in ("TRANS", "INTR")}
    if trs:
        lab = "/".join("да" if x == "TRANS" else "нет" for x in sorted(trs, reverse=True))
        a = ask(f"   переходный? [{lab}] (д/н; Enter = как есть): ").lower()
        new = {"д": "TRANS", "н": "INTR"}.get(a[:1])
        if new and trs != {new}:
            fl = [
                (f, ":".join(new if x in ("TRANS", "INTR") else x for x in t.split(":")))
                for f, t in fl
                if not (new == "INTR" and "STR" in t.split(":"))
            ]
    # max: из двух инфинитивов (брызгать) берётся TRANS, иначе пустые ячейки страд. причастий не предлагаются
    return fl, max((t for _, t in fl if t.startswith("VB:INF")), default="VB:INF:")[len("VB:INF:") :]


def bare_kind(fl: list[forms.Form], asp: str) -> tuple[list[forms.Form], str]:
    """Глагол без вида и переходности (как «дрочить»): оба ответа заполняют пустую ячейку тегов, как у обычных глаголов."""
    a = ask("   переходный? [?] (д/н; Enter = как есть): ").lower()
    tr = {"д": "TRANS", "н": "INTR"}.get(a[:1])
    if not (asp and tr):
        if asp or tr:
            print("   вид и переходность записываются только вместе: теги оставлены без них")
        return fl, ""
    mid = f"{tr}:{asp}"
    # наст. время несов. вида — VB:Real, буд. сов. — VB:Fut (у LT такие глаголы с VB:Real)
    tense = ("VB:Fut:", "VB:Real:") if asp == "IMPFV" else ("VB:Real:", "VB:Fut:")
    out = []
    for f, t in fl:
        p = t.split(":")
        if tr == "INTR" and "STR" in p:
            continue  # у непереходного нет страд. причастий
        t = ":".join(p[:2] + [mid] + p[3:])
        out.append((f, tense[1] + t[len(tense[0]) :] if t.startswith(tense[0]) else t))
    return out, mid


def edit_cell(c: str, title: str, test, fl: list[forms.Form], mid: str) -> list[forms.Form]:
    """Один вопрос edit: формы ячейки title (test — проверка тега) -> новые формы слова."""
    tags = {t for _, t in fl if test(t)}
    # ячейку, которую образец оставил пустой, можно заполнить (шкерящийся, неубиваем)
    if not tags:
        tag = forms.blank(c, title, mid)
        # у непереходного страд. причастий нет: ячейку не предлагаем
        if not tag or ":STR:" in tag and "INTR" in mid.split(":"):
            return fl
        new = ask(f"   {title.replace('|', ' ').strip()} []: ")
        parts = new.split("/") if new and new != "-" else []
        # новый список: показанный вариант не должен сохранить эти формы
        return fl + (decline(parts[0], tag, fl) if parts and tag.startswith("PT") else [(n, tag) for n in parts])
    if c.startswith("NN"):
        # заголовок ячейки существительного: "Sin Р."
        num, _, case = title.partition(" ")
        q = forms.question(c, next(x[0] for x in forms.CASES if x[1] == case))
        hint = f"{case} {'ед.' if num == 'Sin' else 'мн.'} ({q})"
    else:
        hint = title.replace("|", " ").strip()
    old = sorted({f for f, t in fl if t in tags})
    part = title.startswith("прич.")
    # исправленная основа переходит на формы того же склонения: причастия — на все PT, полная форма прилагательного —
    # на все его формы (классный -> класный: класного, класен), краткая — только на краткие (тёмно -> темно,
    # тёмный остаётся); у существительного беглая гласная только в части форм, ему не переносим
    g = next(iter(tags)).split(":")[1]
    grp = ""  # начало тегов группы
    if part:
        grp = "PT"
    elif c == "ADJ":
        grp = "ADJ:" if g == "Posit" else f"ADJ:{g}"
    # у причастия группа — только оно само (то же время и залог): правка изрёкший не трогает изречённый
    pt = {(t.split(":")[1], ":STR" in t) for t in tags}
    group = {t for _, t in fl if grp and t.startswith(grp) and (not part or (t.split(":")[1], ":STR" in t) in pt)}
    while True:
        new = ask(f"   {hint} [{'/'.join(old)}]: ")
        parts = new.split("/") if new and new != "-" else []
        # причастие меняется форма за формой (склонение следует за ним), остальные ячейки принимают любые варианты;
        # часть форм из подсказки оставляет только их ряды
        if not part or not parts or len(parts) == len(old) or set(parts) < set(old):
            break
        print(f"   нужно {len(old)} через '/', как в подсказке, или часть из них")
    if part and parts and set(parts) < set(old):
        # ряд убранной формы (изрекший) уходит со всеми падежами и краткими: формы, начало которых до первого
        # отличия от оставленной совпадает с ней (изрекш-, а не изрёкш-)
        for o in set(old) - set(parts):
            i = max(len(forms.prefix([o, k])) for k in parts)
            heads = [k[: i + 1] for k in parts]
            fl = [
                (f, t)
                for f, t in fl
                if t not in group or not f.startswith(o[: i + 1]) or any(f.startswith(h) for h in heads)
            ]
        return fl
    pairs = dict(zip(old, parts)) if grp and len(parts) == len(old) else {}
    if new == "-" or parts and not pairs:
        fl = [(f, t) for f, t in fl if t not in tags] + [(n, t) for n in parts for t in tags]
    for o, n in pairs.items():
        if o == n:
            continue
        # то же изменение переходит на все формы группы (заигнорённ- -> заигноренн-)
        k = len(forms.prefix([o[::-1], n[::-1]]))
        moved = []
        for f, t in fl:
            if f == o and t in tags:
                f = n
            elif k >= 2 and t in group and f.startswith(o[: len(o) - k]):
                f = n[: len(n) - k] + f[len(o) - k :]
            moved.append((f, t))
        fl = moved
    return fl


def decline(n: str, tag: str, fl: list[forms.Form]) -> list[forms.Form]:
    """Причастие, которого нет у образца (шкерящийся, тег Masc:Nom), склоняется по тому, что у глагола есть (шкерившийся)."""
    noms = [(f, t) for f, t in fl if t.startswith("PT:") and t.endswith(":Masc:Nom")]
    o, ot = next(
        ((f, t) for f, t in noms if t.split(":")[-3] == tag.split(":")[-3]),
        noms[0] if noms else (n, tag),
    )
    k = len(forms.prefix([o[::-1], n[::-1]]))
    if k < 2:
        return [(n, tag)]
    # shortcut: без кратких форм (они есть только у страдательных причастий), при надобности добавить их вручную в tagged.txt
    head, ohead = tag[: -len("Masc:Nom")], ot[: -len("Masc:Nom")]
    return [
        (n[: len(n) - k] + f[len(o) - k :], head + t[len(ohead) :])
        for f, t in fl
        if t.startswith(ohead) and f.startswith(o[: len(o) - k])
    ]


HELP = """
  Enter или номер: записать слово со всеми формами этого варианта.
  рN: пройти формы варианта N по падежам и поправить (Enter оставляет форму, '-' убирает, 'а/б' — две формы).
  Слово вместо номера: известное слово, которое склоняется так же, в любой форме (Магнусон -> Антон,
     перепих -> смех, брумзалом -> окно). Варианты построятся по нему.
  н: несклоняемое слово, спросит род (Гоа, Брум): падежи одинаковые, но согласование проверяется.
  Общий род (сирота, визави: «бедный сирота» и «бедная сирота»): вариант «общ. р.» в меню, по образцу
     такого слова, или ответ «мж» на вопрос о роде (при н и рN) — слово записывается и как м.р., и как ж.р.
  нр: наречие (покадрово)
  0: принимать как есть, проверка без согласования: слово уходит только в орфографию, без разбора
     (частицы, междометия, пары слов: его-то)
  п: пропустить слово, ничего не записывать
  +: в конце любого ответа (1+, р2+, Антон+, н+, нр+): записать вариант и выбрать для того же слова ещё одно
     значение — другой род, склонение, одушевлённость (Тесла: он и машина). Без + выбор слова закончен.
"""


def known_ask(title, can_fix):
    """Слово уже известно: '' — ничего не делать, 'д' — поправить его склонение, 'з' — добавить ещё значение."""
    print(f"= {title}")
    q = (
        "  Enter = ничего"
        + (" · д = поправить это склонение" if can_fix else "")
        + " · з = ещё значение (другое склонение или род): "
    )
    while True:
        a = ask(q).lower()
        if a == "":
            return ""
        if a == "з" or a == "д" and can_fix:
            return a
        print(f"   не понял «{a}»: Enter, {'д, ' if can_fix else ''}з")


def choose(ix, word, warn_yo, preferred=None, listed=(), known=True, pending=None) -> list[Block] | Choice:
    """Спросить, как добавить слово: непустой список размеченных блоков (по блоку на значение) или Choice.
    known=False: слово уже известно, нужно ещё одно значение (меню без вопроса об известном). pending: как у pick."""
    for v in warn_yo:
        print(f"! в словаре есть «{v}»: возможно, нужно ё")
    if warn_yo and not confirm("  всё равно добавить?", False):
        return Choice.SKIP
    drop = ()  # з: известные значения слова не предлагаются снова как «форма известного слова»
    if known and not preferred and ix.known(word):
        paras = known_paras(ix, word)
        lab = para_labels(ix, paras)
        a = known_ask(
            f"{word}: словарь тегов его уже знает{f' ({lab})' if lab else ''}, в орфографию добавится и так",
            bool(paras),
        )
        if a == "д":
            return fix_known(ix, word, paras) or Choice.SPELLING
        if a != "з":
            return Choice.SPELLING
        drop = paras
    elif not known:
        drop = known_paras(ix, word)
    if word[:1].isupper() and ix.known(word.lower(), proper=False):
        print(f"  (есть нарицательное «{word.lower()}»: для имени выберите вариант ниже)")
    got: list[Block] = []
    while True:
        res, more = pick(ix, word, preferred, listed, again=bool(got), drop=drop, pending=pending)
        if isinstance(res, Choice):  # 0 и п после первого значения просто заканчивают выбор
            return got or res
        got.append(res)
        # у LT такие формы — ещё и наречие (быстро: ADV и кратк. от быстрый), но лишь у каждой десятой: спрашиваем
        for adv in short_neut(res[1], listed or [word]):
            if any(rows == [(adv, adv, "ADV")] for _, rows in got):
                continue  # 1+ и 2 с той же краткой формой или нр+: наречие уже есть, второй раз не спрашиваем
            if confirm(f"   {adv} — ещё и наречие, как «быстро» («{adv.lower()} сделал»)?", True):
                got.append(([f"# {adv}: наречие"], [(adv, adv, "ADV")]))
        if not more:
            return got


def menu(ix, word, form, preferred, listed, again, drop, own) -> list[Option]:
    """Собрать и напечатать меню вариантов pick -> варианты по номерам."""
    known = {lem for lem, _ in drop}
    opts = [
        o
        for o in options(ix, word, preferred, listed=listed, own=own)
        if not (o.kind == "form" and o.lemma.lower() in known)
    ]
    if form[:1].isupper() and form[-1:].lower() in "оуюеиэ" and not own:
        # Рэйнбоу, Шерри, Винни: имя на эти гласные не склоняется (на -а/-я склоняется: Мишаня)
        opts.insert(0, Option("indecl", form, "", [], "несклоняемое имя (спросит род)"))
    # указанные формы, а не угаданная лемма группы: после образца у вариантов может быть другая (полугореть)
    print(f"\n{' '.join(listed) or word} — {'ещё значение: ' if again else ''}как склоняется?")
    for i, o in enumerate(opts, 1):
        print(f"  {i}) {o.desc}")
    if again:
        keys = "Enter = готово, больше значений нет · номер = выбрать · р1 = поправить формы варианта 1"
    elif opts:
        keys = "Enter = вариант 1 · номер = выбрать · р1 = поправить формы варианта 1"
    else:
        keys = "Enter = пропустить"
    example = "Антон" if form[:1].isupper() else "стакан"
    print(
        f"  {keys} · ? = справка\n"
        f"  Нет подходящего? Впишите слово, которое склоняется так же, в любой форме (например: {example})\n"
        "  н = несклоняемое, спросит род · нр = наречие\n"
        "  0 = принимать как есть, проверка без согласования · п = пропустить\n"
        "  + в конце ответа (1+, н+) = записать и добавить ещё значение (другой род или склонение)"
    )
    return opts


def model_paras(ix, form, model, pending):
    """[(лемма, pid)] по вписанному слову-образцу (перепих как смех) или [] с объяснением, почему не подошёл."""
    # свои слова тоже годятся в образцы: у теггера LT нет многих глаголов (заебать для наебать)
    own_words = store.read_tagged_all()
    for b in (pending or {}).values():  # размечено в этом же запуске, ещё не записано (rpdict заебать наебать)
        store.put(own_words, b)
    got = ix.like(form, model, own=[(lem, [(f, t) for f, _, t in rows]) for lem, (_, rows) in own_words.items()])
    if not got:
        # открывши для потрясши: общее только -ши, собственные изменения образца (открыть) начинаются раньше
        print(
            f"   «{model}» не подходит как образец для «{form}»: его нет ни в словаре тегов, ни среди ваших слов,"
            f" или ни одна его форма не отличается от «{form}» только началом"
        )
    return got


def indeclinable_block(form) -> Block | None:
    """Вопросы о несклоняемом слове (род, имя, одушевлённость) -> блок или None, если род не понят."""
    g = GENDER.get(ask("   род [м/ж/с/мж = общий]: ").lower())
    if not g:
        return None
    # само указанное слово (ци), а не лемма, угаданная для склонения (ций)
    # Токио, Гоа: топонимы в теггере нарицательные (москва), NN:Name — для людей (правила о запятой при обращении)
    name = form[:1].isupper() and confirm("   имя или фамилия человека?", True)
    anim = "Name" if name else "Anim" if confirm("   одушевлённое?", False) else "Inanim"
    c, fl = forms.indeclinable(form, g, anim)
    return [f"# {form}: несклоняемое, {forms.label(c, fl)}"], [(f, form, t) for f, t in both(fl)]


def pick(ix, word, preferred, listed, again, drop=(), pending=None) -> tuple[Block | Choice, bool]:
    """Меню вариантов склонения: (блок или Choice, more: ответ кончался на '+').
    drop: [(лемма, pid)] значений, которые слово уже имеет: их «форма известного слова» не показывается.
    pending: блоки tagged, ещё не записанные на диск: тоже годятся в образцы."""
    more = False  # Антон+: образец только перестраивает меню, '+' относится к следующему выбору
    # форма, с которой сравнивается слово-образец (перепих, а не угаданное перепий)
    form = listed[0] if listed else word
    show, own = True, ()
    while True:
        if show:
            opts = menu(ix, word, form, preferred, listed, again, drop, own)
            show = False
        raw = ask(f"  выбор [{'1' if opts and not again else 'п'}]: ")
        if raw.endswith("+"):
            more, raw = True, raw[:-1].strip()
        a = raw.lower() or ("1" if opts and not again else "п")
        n = a.removeprefix("р")
        if n.isdigit() and 1 <= int(n) <= len(opts) and opts[int(n) - 1].kind == "indecl":
            a = "н"  # предложенное «несклоняемое»: те же вопросы
        if a == "?":
            print(HELP)
            continue
        if a not in ("н", "нр", "п", "р") and raw.replace("-", "").isalpha():
            # ни одна догадка не подходит (перепих: -их — в основном формы мн. ч.): вписанное слово — образец
            if got := model_paras(ix, form, raw, pending):
                preferred, own, show = got, set(got), True
            continue
        if a == "0":
            return Choice.SPELLING, False
        if a == "п":
            return Choice.SKIP, False
        # покадрово: не краткая форма прилагательного (у покадровый её нет), а отдельное слово
        if a == "нр":
            adv = ask(f"   наречие [{form}]: ") or form
            return ([f"# {adv}: наречие"], [(adv, adv, "ADV")]), more
        if a == "н":
            if block := indeclinable_block(form):
                return block, more
            continue
        if (n.isdigit() or a == "р") and 1 <= int(n or 1) <= len(opts):
            kind, lem, c, fl, desc = opts[int(n or 1) - 1]
            head = desc.split("\n")[0]
            if a.startswith("р") and kind == "para":
                if c == "PT":  # лемма — инфинитив, угаданный по образцу (ёбать вместо ебать): в ячейках его нет
                    lem = ask(f"   инфинитив [{lem}]: ") or lem
                c, fl = edit(c, fl)
                show_table(c, fl)
                # Enter на последней ячейке не должен записать непросмотренное
                if not confirm("  записать так?", True):
                    continue
                # у причастия без глагола лемма — инфинитив, его в ячейках нет
                if c != "PT":
                    # И. ед. / м.р. / инфинитив: лемма могла измениться (одеялко)
                    first = forms.cells(c)[0][1]
                    lem = next((f for f, t in sorted(fl) if first(t)), lem)
                head = f"поправлено, {forms.label(c, fl)}"
            # блок причастия назван им самим (полугорящий), чтобы rpdict -r полугорящий удалил его целиком
            name = next((f for f, t in fl if t.endswith(":Masc:Nom")), lem) if c == "PT" else lem
            return ([f"# {name}: {head}"], [(f, lem, t) for f, t in both(fl)]), more
        print(f"   не понял «{a}»: номер варианта, рN, слово-образец, н, нр, 0, п или ?")


def known_paras(ix, word):
    """[(лемма, pid)] известных теггеру слов открытых классов, у которых word — одна из форм."""
    return list(
        dict.fromkeys(
            (lem, p)
            for _, lem, p, _, _ in ix.analyses(word.lower())
            if p in ix.lemma_pids.get(lem, ())
            and ix.paras[p].cls.startswith(forms.OPEN)
            and word.lower() in {f for f, _ in ix.forms(lem, p)}
        )
    )


def para_labels(ix: forms.Index, paras: list[tuple[str, int]]) -> str:
    """«лемма — класс» через «; » для вариантов known_paras."""
    return "; ".join(f"{lem} — {forms.label(ix.paras[p].cls, ix.forms(lem, p))}" for lem, p in paras)


def fix_known(ix, word, paras) -> list[Block]:
    """Добавить формы или теги, которых не хватает известному слову (огромные глазища: у теггера глазища только как Sin Р.).
    paras: known_paras. -> [размеченный блок только из новых строк] или [] — ничего не добавлять."""
    if len(paras) > 1:
        for i, (lem, p) in enumerate(paras, 1):
            print(f"  {i}) {lem} — {forms.label(ix.paras[p].cls, ix.forms(lem, p))}")
    n = ask("  какое слово [1]: ") if len(paras) > 1 else ""
    n = n or "1"
    if not n.isdigit() or not 1 <= int(n) <= len(paras):
        return []
    lem, pid = paras[int(n) - 1]
    old = [(cased(word, f), t) for f, t in ix.forms(lem, pid)]
    c, fl = edit(ix.paras[pid].cls, old)
    show_table(c, fl)
    new, gone = sorted(set(fl) - set(old)), sorted({f for f, _ in set(old) - set(fl)})
    if gone:
        # shortcut: только добавление, removed_custom.txt из LT не смонтирован; смонтировать, когда понадобится убрать неверную форму
        print(f"  убрать формы общего словаря нельзя, остаются: {', '.join(gone)}")
    if not new or not confirm("  записать новые формы?", True):
        return []
    lem = cased(word, lem)
    return [([f"# {lem}: дополнено, {forms.label(c, fl)}"], [(f, lem, t) for f, t in new])]


def fix_own(tagged, lemmas):
    """Поправить склонение слова из личного списка: значение (класс тегов) блока проходит через edit,
    правка пишется на место его строк. -> лемма или None."""
    groups = []  # (лемма, классы тегов, класс для edit): причастие без глагола правится как PT
    part = lambda rows, k: [(f, t) for f, _, t in rows if forms.cls(t) == k]
    for lemma in lemmas:
        rows = tagged[lemma][1]
        ks = list(dict.fromkeys(forms.cls(t) for _, _, t in rows))
        for k in ks:
            com = com_key("para", lemma, k, part(rows, k))
            twin = next((x for x in ks if x != k and com and com_key("para", lemma, x, part(rows, x)) == com), None)
            if twin and k.endswith(":Fem"):
                continue  # сирота: ж.р. правится вместе с м.р., одним значением общего рода
            pt = k == "V" and not any(t.startswith("VB:INF") for _, _, t in rows)
            groups.append((lemma, (k, twin), k.replace(":Masc", ":Com")) if twin else (lemma, (k,), "PT" if pt else k))

    def old(g):
        fl = part(tagged[g[0]][1], g[1][0])
        return [(f, t.replace(":Masc:", ":Com:", 1)) for f, t in fl] if g[2].endswith(":Com") else fl

    if len(groups) > 1:
        for i, g in enumerate(groups, 1):
            print(f"  {i}) {g[0]} — {forms.label(g[2], old(g))}")
    n = (ask("  какое значение [1]: ") if len(groups) > 1 else "") or "1"
    if not n.isdigit() or not 1 <= int(n) <= len(groups):
        return None
    g = groups[int(n) - 1]
    lem, was = g[0], old(g)
    # shortcut: лемма (первый столбец) остаётся прежней, даже если И. ед. исправлен; тогда удалить слово и добавить заново
    c, fl = edit(g[2], was)
    show_table(c, fl)
    if fl == both(was) or not confirm("  записать так?", True):
        return None
    head, rows = tagged[lem]
    a, b = forms.label(g[2], was), forms.label(c, fl)
    tagged[lem] = (
        [h.replace(a, b) for h in head],  # род или одушевлённость в заголовке значения
        sorted({r for r in rows if forms.cls(r[2]) not in g[1]} | {(f, lem, t) for f, t in fl}),
    )
    return lem


def plural(n, one, few, many):
    """Число со словом в нужной форме: 1 форма, 3 формы, 11 форм, 21 форма."""
    k = 2 if n % 100 in range(11, 15) or n % 10 not in range(1, 5) else 0 if n % 10 == 1 else 1
    return f"{n} {(one, few, many)[k]}"


def report(tagged: dict[str, Block], blocks: list[Block], extra=False):
    """Записать значения в tagged и сказать, сколько их: + tagged: Тесла (2 значения, 13 форм)."""
    lem = ", ".join(dict.fromkeys(store.put(tagged, b) for b in blocks))
    n = sum(len(h) for h, _ in blocks)  # заголовок на значение
    m = f"{'+' if extra else ''}{plural(n, 'значение', 'значения', 'значений')}, " if extra or n > 1 else ""
    print(f"+ tagged: {lem} ({m}{plural(len({r[0] for _, rs in blocks for r in rs}), 'форма', 'формы', 'форм')})")


# заглушки для самопроверок dialog.py и words.py: индекс без вариантов и ответы по тексту вопроса
class NoIndex:
    guess = models = analyses = lambda *a, **k: []
    known = lambda *a, **k: False


def answer(*pairs):
    """Ответ — первый из pairs, чей ключ входит в вопрос; иначе Enter. Список ключа — ответы по очереди."""
    left = {k: list(v) if isinstance(v, list) else [v] for k, v in pairs}
    return lambda p="": next((v.pop(0) for k, v in left.items() if k in p and v), "")


if __name__ == "__main__":
    # самопроверка
    import contextlib
    import io
    import tempfile
    from unittest import mock

    def replies(fn):
        """input() отвечает fn(вопрос)."""
        return mock.patch("builtins.input", fn)

    assert cased("ФСБшника", "фсбшников") == "ФСБшников" and cased("Брум", "брум") == "Брум"
    # род оставлен, И. оставлен, Р. задан, Д. убран
    it = iter(["", "", "Брума", "-"] + [""] * 9)
    with replies(lambda p="": next(it)):
        got = edit(*forms.indeclinable("Брум", "Fem", "Name"))[1]
    assert ("Брума", "NN:Name:Fem:Sin:R") in got and not any(t.endswith(":D") for _, t in got), got
    # неодушевлённый образец сделан именем: В. становится как Р. (вижу Лавкрафта, Лавкрафтов)
    lv = [
        ("Лавкрафт", "NN:Inanim:Masc:Sin:Nom"),
        ("Лавкрафта", "NN:Inanim:Masc:Sin:R"),
        ("Лавкрафт", "NN:Inanim:Masc:Sin:V"),
        ("Лавкрафты", "NN:Inanim:Masc:PL:Nom"),
        ("Лавкрафтов", "NN:Inanim:Masc:PL:R"),
        ("Лавкрафты", "NN:Inanim:Masc:PL:V"),
    ]
    with replies(lambda p="": "и" if p.startswith("   род") else ""):
        c, got = edit("NN:Inanim:Masc", lv)
    assert (
        c == "NN:Name:Masc"
        and len(got) == 6
        and ("Лавкрафта", "NN:Name:Masc:Sin:V") in got
        and ("Лавкрафтов", "NN:Name:Masc:PL:V") in got
    ), got
    # общий род: мж в вопросе о роде даёт формы и м.р., и ж.р.; м.р. и ж.р. с одними формами — одна половина пары
    sir = [("брумза", "NN:Anim:Fem:Sin:Nom"), ("брумз", "NN:Anim:Fem:PL:R")]
    with replies(lambda p="": "мж" if p.startswith("   род") else ""):
        c, got = edit("NN:Anim:Fem", sir)
    assert c == "NN:Anim:Com" and len(got) == 4 and ("брумз", "NN:Anim:Masc:PL:R") in got, got
    assert forms.label(c, got) == "сущ. одуш. общ. р. (м. и ж.)"
    masc = [(f, t.replace(":Fem:", ":Masc:")) for f, t in sir]
    assert com_key("para", "брумза", "NN:Anim:Fem", sir) == com_key("para", "брумза", "NN:Anim:Masc", masc)
    assert com_key("para", "брумза", "NN:Anim:Fem", sir) != com_key("para", "брумза", "NN:Anim:Masc", masc[:1])

    class TwinIndex(NoIndex):  # догадки «как папа» (м.р.) и «как мама» (ж.р.): формы одни
        paras = (forms.Para("NN:Anim:Masc", "", (), []), forms.Para("NN:Anim:Fem", "", (), []))
        guess = lambda *a, **k: [("брумза", 0, 1), ("брумза", 1, 1)]
        forms = lambda self, lem, pid: masc if pid == 0 else sir
        lemma_known = lambda *a: False
        sample = lambda *a: "мама"

    # общий род только по вписанному образцу (сирота); сами догадки остаются м.р. и ж.р. (Маккенна)
    assert [o.cls for o in options(TwinIndex(), "брумза")] == ["NN:Anim:Masc", "NN:Anim:Fem"]
    assert [o.cls for o in options(TwinIndex(), "брумза", own={("брумза", 0), ("брумза", 1)})] == ["NN:Anim:Com"]
    # своё слово общего рода правится одним значением: исправленная форма уходит и к м.р., и к ж.р.
    head = ["# брумза: как «сирота» — сущ. одуш. общ. р. (м. и ж.)"]
    tagged = {"брумза": (head, [(f, "брумза", t) for f, t in sir + masc])}
    with replies(answer(("Р. мн.", "брумзов"))), contextlib.redirect_stdout(io.StringIO()):
        assert fix_own(tagged, ["брумза"]) == "брумза"
    assert tagged["брумза"][0] == head and len(tagged["брумза"][1]) == 4, tagged
    assert {t for f, _, t in tagged["брумза"][1] if f == "брумзов"} == {"NN:Anim:Masc:PL:R", "NN:Anim:Fem:PL:R"}, tagged
    with replies(answer(("род [", "мж"), ("одушевлённое", "д"))), contextlib.redirect_stdout(io.StringIO()):
        blk = indeclinable_block("визави")
    assert blk and len(blk[1]) == 24 and ("визави", "визави", "NN:Anim:Fem:PL:T") in blk[1], blk
    # ячейка прилагательного держит одну форму: краткая м.р., которой нет у образца, добавляется одна, остальные остаются
    adj = [("неубиваемый", "ADJ:Posit:Masc:Nom"), ("неубиваема", "ADJ:Short:Fem"), ("неубиваемо", "ADJ:Short:Neut")]
    with replies(lambda p="": "неубиваем" if "каков? м.р." in p else ""):
        got = edit("ADJ", adj)[1]
    assert got == sorted(adj + [("неубиваем", "ADJ:Short:Masc")]), got
    # основа, исправленная в И. м.р., переходит на все формы; исправленная в краткой — только на краткие
    adj = [
        ("брумменный", "ADJ:Posit:Masc:Nom"),
        ("брумменного", "ADJ:Posit:Masc:R"),
        ("брумменная", "ADJ:Posit:Fem:Nom"),
        ("брумменна", "ADJ:Short:Fem"),
        ("брумменны", "ADJ:Short:PL"),
    ]
    with replies(lambda p="": "брумёный" if "какой? м.р." in p else "брумена" if "какова?" in p else ""):
        got = edit("ADJ", adj)[1]
    assert {f for f, _ in got} == {"брумёный", "брумёного", "брумёная", "брумена", "брумены"}, got
    # исправление причастия распространяется на его падежные и краткие формы, действительное причастие не меняется
    v = [
        ("заигнорить", "VB:INF:TRANS:PFV"),
        ("заигноривший", "PT:Past:TRANS:PFV:DST:Masc:Nom"),
        ("заигнорённый", "PT:Past:TRANS:PFV:STR:Masc:Nom"),
        ("заигнорённого", "PT:Past:TRANS:PFV:STR:Masc:R"),
        ("заигнорён", "PT_Short:Past:TRANS:PFV:STR:Masc"),
    ]
    # вид оставлен, во всех остальных ячейках (и пустых) Enter; страд. прош. исправлено
    with replies(lambda p="": "заигноренный" if "страд. прош." in p else ""):
        got = {f for f, _ in edit("V", v)[1]}
    assert got == {"заигнорить", "заигноривший", "заигноренный", "заигноренного", "заигнорен"}, got
    # правка основы одного причастия не переходит на другое с тем же началом; часть форм из подсказки убирает
    # ряды остальных со всеми падежами
    vv = [
        ("брумечь", "VB:INF:TRANS:PFV"),
        ("брумекший", "PT:Past:TRANS:PFV:DST:Masc:Nom"),
        ("брумекшего", "PT:Past:TRANS:PFV:DST:Masc:R"),
        ("брумёкший", "PT:Past:TRANS:PFV:DST:Masc:Nom"),
        ("брумёкшего", "PT:Past:TRANS:PFV:DST:Masc:R"),
        ("брумеченный", "PT:Past:TRANS:PFV:STR:Masc:Nom"),
        ("брумечен", "PT_Short:Past:TRANS:PFV:STR:Masc"),
    ]
    for ans, want in (("брумёкший", {"брумёкший", "брумёкшего"}), ("брумёкший/брумёкший", {"брумёкший", "брумёкшего"})):
        with replies(lambda p="", a=ans: a if "действ. прош." in p else ""):
            got = {f for f, _ in edit("V", vv)[1]}
        assert got == {"брумечь", "брумеченный", "брумечен"} | want, (ans, got)
    # сделан непереходным: теги меняются, страдательные причастия уходят и пустыми ячейками не предлагаются;
    # у образца с обоими инфинитивами (брызгать) остаётся один
    asked = []
    with replies(lambda p="": asked.append(p) or ("н" if p.startswith("   переходный?") else "")):
        for pat in (v, v + [("заигнорить", "VB:INF:INTR:PFV")]):
            got = edit("V", pat)[1]
            assert sorted(got) == [
                ("заигноривший", "PT:Past:INTR:PFV:DST:Masc:Nom"),
                ("заигнорить", "VB:INF:INTR:PFV"),
            ], got
    tr = [p for p in asked if p.startswith("   переходный?")]
    assert "[да/нет]" in tr[1] and not any("страд." in p for p in asked), asked
    # у образца без переходности (дождить) вопроса нет
    asked = []
    with replies(lambda p="": asked.append(p) or ""):
        edit("V", [("брумить", "VB:INF:IMPFV")])
    assert not any("переходный?" in p for p in asked), asked
    # у образца с обоими инфинитивами Enter оставляет переходность, и пустые ячейки страд. причастий предлагаются
    asked = []
    with replies(lambda p="": asked.append(p) or ""):
        edit("V", [("брумить", "VB:INF:INTR:IMPFV"), ("брумить", "VB:INF:TRANS:IMPFV")])
    assert any("страд." in p for p in asked), asked
    # сделан переходным: теги меняются, пустые ячейки страд. причастий снова предлагаются
    asked = []
    with replies(lambda p="": asked.append(p) or ("д" if p.startswith("   переходный?") else "")):
        got = edit("V", [("брумить", "VB:INF:INTR:IMPFV")])[1]
    assert got == [("брумить", "VB:INF:TRANS:IMPFV")], got
    assert any("страд." in p for p in asked), asked
    # EOF не подделывается ответом: вопрос о переходности его пропускает наверх, к циклу по словам
    with mock.patch("builtins.input", side_effect=EOFError):
        try:
            edit("V", [("брумить", "VB:INF:INTR:IMPFV")])
            raise AssertionError("EOF проглочен")
        except EOFError:
            pass
    # образец без вида и переходности (дрочить): оба ответа заполняют пустую ячейку, наст. время сов. вида -> буд.,
    # страд. причастия непереходного уходят; один ответ теги не трогает
    bare = [
        ("брумить", "VB:INF:"),
        ("брумит", "VB:Real::Sin:P3"),
        ("брумив", "DPT:Past:"),
        ("брумённый", "PT:Past::STR:Masc:Nom"),
    ]
    asked = []
    with replies(lambda p="": asked.append(p) or ("с" if "вид [?]" in p else "н" if "переходный? [?]" in p else "")):
        got = edit("V", bare)[1]
    assert got == [
        ("брумив", "DPT:Past:INTR:PFV"),
        ("брумит", "VB:Fut:INTR:PFV:Sin:P3"),
        ("брумить", "VB:INF:INTR:PFV"),
    ]
    assert not any("страд." in p for p in asked), asked
    with replies(lambda p="": "н" if "вид [?]" in p else ""):
        assert edit("V", bare)[1] == sorted(bare)
    # причастие, которого нет у образца, склоняется по имеющемуся у глагола
    assert decline(
        "шкерящийся",
        "PT:Real:INTR:IMPFV:DST:Masc:Nom",
        [("шкерившийся", "PT:Past:INTR:IMPFV:DST:Masc:Nom"), ("шкерившегося", "PT:Past:INTR:IMPFV:DST:Masc:R")],
    ) == [("шкерящийся", "PT:Real:INTR:IMPFV:DST:Masc:Nom"), ("шкерящегося", "PT:Real:INTR:IMPFV:DST:Masc:R")]
    # confirm: подсказка по умолчанию, Enter = умолчание
    asked = []
    with replies(lambda p="": asked.append(p) or ""):
        assert confirm("  записать?", True) and not confirm("  добавить?", False)
    assert asked == ["  записать? [Д/н]: ", "  добавить? [д/Н]: "]

    # participles: одна цепочка причастия с м.р. И., образец — его форма с тем же тегом
    class PartIndex(NoIndex):
        sample = lambda *a: "горящий"
        forms = lambda *a: [("горящий", "PT:Real:INTR:IMPFV:DST:Masc:Nom")]

    vfl = [
        ("брумзящий", "PT:Real:INTR:IMPFV:DST:Masc:Nom"),
        ("брумзящая", "PT:Real:INTR:IMPFV:DST:Fem:Nom"),
        ("брумзю", "VB:Real:INTR:IMPFV:Sin:P1"),
        ("брумзить", "VB:INF:INTR:IMPFV"),
    ]
    seen = set()
    [pt] = participles(PartIndex(), "брумзить", 0, vfl, {"брумзящая"}, seen)
    assert pt.cls == "PT" and pt.lemma == "брумзить" and pt.forms == vfl[:2] and len(seen) == 1
    assert pt.desc.startswith("только причастие, без глагола: брумзящий, брумзящая…") and "«брумзю»" in pt.desc
    assert "инф. «брумзить», несов. вид" in pt.desc, pt.desc
    assert not participles(PartIndex(), "брумзить", 0, vfl, {"брумзящая"}, seen)  # уже показано
    # р1 у причастия без глагола: инфинитив и вид, угаданные по образцу, правятся (брумзанный не от брумзать сов.)
    pfl = [("брумзанный", "PT:Past:TRANS:PFV:STR:Masc:Nom"), ("брумзан", "PT_Short:Past:TRANS:PFV:STR:Masc")]
    with (
        mock.patch(f"{__name__}.options", lambda *a, **k: [Option("para", "брумзать", "PT", pfl, "только причастие")]),
        replies(answer(("выбор", "р1"), ("инфинитив [брумзать]", "брумзить"), ("вид [сов.]", "н"))),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        res, _ = pick(NoIndex(), "брумзанный", None, (), False)
    assert not isinstance(res, Choice) and res[1] == [
        ("брумзан", "брумзить", "PT_Short:Past:TRANS:IMPFV:STR:Masc"),
        ("брумзанный", "брумзить", "PT:Past:TRANS:IMPFV:STR:Masc:Nom"),
    ], res
    # несколько значений: заглушка индекса (вариантов нет, слово неизвестно)
    with (
        replies(answer(("выбор", ["н+", "н"]), ("род [", ["м", "ж"]), ("имя или", ["", "н"]))),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        res = choose(NoIndex(), "Брумза", [])
    assert isinstance(res, list) and len(res) == 2, res
    tagged = {}
    for b in res:
        store.put(tagged, b)
    ((head, rows),) = tagged.values()
    assert (
        head == ["# Брумза: несклоняемое, сущ. имя м.р.", "# Брумза: несклоняемое, сущ. неодуш. ж.р."]
        and len(rows) == 12
        and ("Брумза", "Брумза", "NN:Inanim:Fem:Sin:T") in rows
    ), tagged
    # з у известного слова: его же значение не возвращается в меню «формой известного слова» (электрика от электрик)
    menu_opts = [
        Option("form", "Электрик", "", [], "форма известного слова «электрик»"),
        Option("form", "электричка", "", [], "форма известного слова «электричка»"),
        Option("para", "электрика", "", [], "как «диоптрика»"),
    ]
    out = io.StringIO()
    with (
        mock.patch(f"{__name__}.options", lambda *a, **k: menu_opts),
        replies(answer(("выбор", "п"))),
        contextlib.redirect_stdout(out),
    ):
        assert pick(NoIndex(), "электрика", None, (), False, drop=[("электрик", 0)]) == (Choice.SKIP, False)
    assert "«электрик»" not in out.getvalue() and "1) форма известного слова «электричка»" in out.getvalue(), (
        out.getvalue()
    )
    # образец из блока, ещё не записанного на диск (rpdict брумкать пробрумкать): like его видит
    liked = []

    class LikeIndex(NoIndex):
        def like(self, word, model, own=()):
            liked.extend(lem for lem, _ in own)
            return []

    pending = {"брумкать": (["# брумкать: x"], [("брумкать", "брумкать", "VB:INF:TRANS:IMPFV")])}
    with (
        mock.patch(f"{__name__}.options", lambda *a, **k: menu_opts),
        replies(answer(("выбор", ["брумкал", "п"]))),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        pick(LikeIndex(), "пробрумкать", None, (), False, pending=pending)
    assert "брумкать" in liked, liked
    # брумно брумный: вариант без одного из введённых слов не показывается; краткая ср.р. — ещё и наречие (Enter = да)
    adj = [("брумный", "ADJ:Posit:Masc:Nom"), ("брумно", "ADJ:Short:Neut"), ("брумна", "ADJ:Short:Fem")]
    assert covers(adj, ["Брумно", "брумный"]) and not covers(adj[1:], ["брумно", "брумный"])
    assert short_neut([(f, "брумный", t) for f, t in adj], ["брумно", "брумна"]) == ["брумно"]
    assert short_neut([(f, "брумный", t) for f, t in adj], ["брумный"]) == []
    with (
        mock.patch(f"{__name__}.options", lambda *a, **k: [Option("para", "брумный", "ADJ", adj, "как «плёвый»")]),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        for reply, n in (("", 2), ("н", 1)):
            with replies(answer(("выбор", "1"), ("наречие", reply))):
                got = choose(NoIndex(), "брумный", [], listed=["брумно", "брумный"])
            assert (
                isinstance(got, list)
                and len(got) == n
                and (n == 1 or got[1] == (["# брумно: наречие"], [("брумно", "брумно", "ADV")]))
            ), got
        # 1+ и снова 1: наречие уже выбрано, второй раз вопроса нет (иначе Enter добавил бы его ещё раз)
        with replies(answer(("выбор", ["1+", "1"]), ("наречие", [""]))):
            got = choose(NoIndex(), "брумный", [], listed=["брумно", "брумный"])
        assert isinstance(got, list) and len(got) == 3, got
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        report({}, res)
        report({}, res[:1], extra=True)
        # д без поправимого склонения и непонятный ответ спрашиваются заново
        with replies(answer(("Enter = ничего", ["д", "к", "з"]))):
            assert known_ask("x", False) == "з"
    assert out.getvalue().splitlines()[:2] == [
        "+ tagged: Брумза (2 значения, 1 форма)",
        "+ tagged: Брумза (+1 значение, 1 форма)",
    ], out.getvalue()
    assert [plural(n, "форма", "формы", "форм") for n in (1, 3, 5, 11, 14, 21, 22, 112)] == [
        "1 форма",
        "3 формы",
        "5 форм",
        "11 форм",
        "14 форм",
        "21 форма",
        "22 формы",
        "112 форм",
    ]
    # -a: ответы по порядку с эхом; кончились — выход до записи
    ans = Path(tempfile.mkdtemp()) / "answers.txt"
    ans.write_text("з\n\n", encoding="utf-8")
    out = io.StringIO()
    with mock.patch("builtins.input"), contextlib.redirect_stdout(out):  # scripted подменяет input: вернуть после
        left = scripted(ans)
        assert known_ask("x", False) == "з" and input("q? ") == ""
        try:
            input("ещё? ")
            raise AssertionError("ответы кончились, а вопрос прошёл")
        except SystemExit as e:
            assert "ещё?" in str(e), e
    assert left == [] and "з = ещё значение (другое склонение или род): з" in out.getvalue(), out.getvalue()
