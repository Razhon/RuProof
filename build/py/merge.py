#!/usr/bin/env python3
"""Слить Лебедева (ё обязательна) + JetBrains + частоты AOT во входные файлы для SpellDictionaryBuilder.

запуск: merge.py WORKDIR
  нужны WORKDIR/{aot,tags}.raw, build/data/{io,jb}.txt.gz; пишет merged.txt, freq.xml, report-*.txt
Входы не менялись с прошлой сборки (отметка merged.stamp) и merged.txt на месте — выход сразу: rpdict пересобирает
ru_RU.dict, только когда merged.txt новее его.
"""

import gzip
import hashlib
import inspect
import os
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

import store
from store import PO, body, key, lower_only, read_all  # одно правило для словаря и для личных слов

B = store.B


def stamp():
    """Отпечаток входов: при совпадении с merged.stamp сборка пропускается."""
    # aot.raw/tags.raw не входят: их меняет только новый образ, а rpdict тогда удаляет и merged.txt
    # из store.py — только то, что влияет на merged.txt: правка остального store.py не пересобирает словарь
    used = PO.pattern + "".join(
        inspect.getsource(f) for f in (body, key, store.head, lower_only, read_all, store.read_list)
    )
    inputs = [
        Path(__file__).read_bytes(),
        used.encode(),
        *(p.read_bytes() for p in sorted((B / "data").glob("*.gz"))),
        # только строчные слова prohibited: правка замены, ссылки или слова с заглавной словарь не пересобирает
        *(
            "\n".join(sorted(lower_only({key(line) for line in body(store.read_list("prohibited", layer))}))).encode()
            for layer in (store.SHARED, store.LOCAL)
        ),
    ]
    return "".join(hashlib.sha256(x).hexdigest() for x in inputs)


def read_gz(name):
    """Слова build/data/{name}, по строке на слово."""
    text = gzip.decompress((B / "data" / name).read_bytes()).decode("utf-8")
    return {line for line in text.splitlines() if line}


def read_aot(work):
    """Буква частоты AOT для каждой точной словоформы (A=0 ... Z=25)."""
    aot = {}
    for line in (work / "aot.raw").read_text(encoding="koi8_r").splitlines():
        word, _, f = line.rpartition("+")
        aot[word] = ord(f) - 65
    return aot


def tag_pairs(work):
    """[(форма, тег)] повелительных, местоимений и прилагательных из словаря теггера."""
    raw = subprocess.run(
        ["grep", "-aE", r"\+(VB:IMP|PNN|ADJ)", str(work / "tags.raw")], capture_output=True, check=True
    ).stdout
    return [line.split("+")[1:3] for line in raw.decode("koi8_r").splitlines()]


def yo2e(s):
    return s.replace("ё", "е").replace("Ё", "Е")


def has_yo(s):
    return "ё" in s or "Ё" in s


def bogus_short(jb, base):
    """В JetBrains ё необязательна, и краткие причастия везде написаны с ё (повреждёны, возмущёна, ...),
    хотя ё бывает только в мужском роде (повреждён, повреждены). У Лебедева этих форм нет: -> ложные формы JetBrains."""
    known = base | jb
    return {x for x in jb - base if x[0].islower() and x[-3:-1] == "ён" and x[-1] in "аоы" and x[:-1] in known}


def yo_split(extra, vocab):
    """Слова нижних слоёв, которых нет у Лебедева: -> (added, dropped). е-формы каждого слова с ё из vocab
    отвергаются: их приводит только сам Лебедев (все/всё, небо/нёбо), а его слов в extra нет."""
    yo_keys = {yo2e(v) for v in vocab if has_yo(v)}
    dropped = {x for x in extra if not has_yo(x) and x in yo_keys}
    return extra - dropped, dropped


def yoify(x, ymap):
    """В каждой части слова через дефис с однозначной формой на ё (тёмно) ставит ё; ymap: е-написание -> с ё."""
    out = []
    for p in x.split("-"):
        y = ymap.get(p.lower(), p)
        out.append(y[:1].upper() + y[1:] if p[:1].isupper() else y)
    return "-".join(out)


def yoify_hyphenated(words, ymap):
    """Составные слова через дефис есть в AOT только с е (темно-бурый), а у Лебедева/JetBrains дефисных слов нет
    (и части вроде темно/тёмно существуют отдельно в обоих написаниях: в составе слова верна только форма с ё).
    -> {е-написание: с ё} для слов, которые меняются."""
    pairs = {x: yoify(x, ymap) for x in words if "-" in x}
    return {x: y for x, y in pairs.items() if y != x}


def particle_words(pairs, merged):
    """LT считает слово через дефис одним (подождите-ка, нас-то, по-русски): к повелительным -ка, к местоимениям -то,
    от прилагательных — наречия на по-. Только от форм из merged, где ё обязательна (её-то, но не ее-то);
    остальные частицы rpdict добавляет по одной, наречия на по- от личных прилагательных — store.py generate()."""
    return (
        {f + "-ка" for f, t in pairs if t.startswith("VB:IMP") and f in merged}
        | {f + "-то" for f, t in pairs if t.startswith("PNN") and f in merged}
        | {"по-" + f for f, t in pairs if PO.fullmatch(f"{t} {f}") and f in merged}
    )


def freq(word, aot, merged):
    """Частота для freq.xml. е-написание из словаря убрано, поэтому его (более высокая) частота переходит к ё-форме."""
    f = aot.get(word, 0)
    e = yo2e(word)
    if e != word and e not in merged:
        f = max(f, aot.get(e, 0))
    return f * 10


def verify(merged, prohibited):
    """У слов с обязательной ё не должна просочиться е-форма, пары Лебедева должны остаться. Вызывается до любой
    записи: проваленная проверка не должна оставить merged.txt, которому поверит следующий запуск rpdict."""
    for must_out in ("еще", "ее", "еж"):
        assert must_out not in merged, must_out
    assert "темно-бурый" not in merged and "тёмно-бурый" in merged
    assert "повреждены" in merged and "повреждёны" not in merged and "повреждён" in merged
    for must_in in ("ещё", "её", "ёж", "все", "всё", "небо", "нёбо"):
        assert must_in in merged, must_in
    assert not (prohibited & merged)
    assert {"подождите-ка", "смотрите-ка", "нас-то", "её-то"} <= merged and "ее-то" not in merged
    po = {"по-юлиански", "по-немецки", "по-волчьи", "по-новому", "по-зимнему", "по-своему"}
    assert po <= merged and "по-новое" not in merged
    print("самопроверка: ок")


def dump(path, words):
    path.write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")


def write(work, merged, aot):
    """freq.xml и merged.txt."""
    ordered = sorted(merged)  # один раз: сортировка 4,5 млн строк — самый медленный шаг
    with open(work / "freq.xml", "w", encoding="utf-8") as out:
        out.write('<wordlist locale="ru" description="ru" version="3">\n')
        for x in ordered:
            f = freq(x, aot, merged)
            if f:  # A (0) — значение по умолчанию у сборщика
                out.write(f' <w f="{f}" flags="">{escape(x)}</w>\n')
        out.write("</wordlist>\n")
    # merged.txt последним и через временный файл: rpdict доверяет любому найденному merged.txt,
    # оборванный (Ctrl+C) появиться не должен
    tmp = work / "merged.txt.tmp"
    tmp.write_text("\n".join(ordered) + "\n", encoding="utf-8")
    tmp.replace(work / "merged.txt")


def main(work):
    st, stamp_file = stamp(), work / "merged.stamp"
    if (work / "merged.txt").exists() and stamp_file.exists() and stamp_file.read_text() == st:
        return
    base, jb = read_gz("io.txt.gz"), read_gz("jb.txt.gz")
    jb -= bogus_short(jb, base)
    aot = read_aot(work)
    # нижние слои: JetBrains, затем AOT (сохраняют лексику, которой нет у Лебедева: формы глаголов, фамилии)
    layers = jb | set(aot)
    extra = layers - base
    added, dropped = yo_split(extra, base | layers)
    hy = yoify_hyphenated(added, {yo2e(v): v for v in base | jb if yo2e(v) != v})
    dropped |= hy.keys()
    added = (added - hy.keys()) | set(hy.values())
    merged = base | added
    particles = particle_words(tag_pairs(work), merged)
    merged |= particles

    # личные слова обоих слоёв: spelling/ignore/tagged LT читает при старте (store.py -> dict/*_custom.txt, без
    # пересборки), только prohibited (отвергается в любом регистре) требует бинарного словаря
    spelling, ignore, prohibited = (
        {key(line) for line in body(read_all(n))} for n in ("spelling", "ignore", "prohibited")
    )
    # личные слова, которые уже есть в базовом словаре (rpdict -c их убирает)
    dump(work / "report-redundant-words.txt", (spelling | ignore) & merged)
    prohibited = lower_only(prohibited)
    merged -= prohibited

    verify(merged, prohibited)
    write(work, merged, aot)
    stamp_file.write_text(st)
    dump(work / "report-dropped-e-forms.txt", dropped)
    dump(work / "report-added-from-jb-aot.txt", added)
    print(
        f"lebedev-io={len(base)} jb={len(jb)} aot={len(aot)} extra={len(extra)} dropped(e-alias)={len(dropped)} "
        f"added={len(added)} particles={len(particles)} merged={len(merged)}"
    )


if __name__ == "__main__":
    # самопроверка (данные не нужны)
    assert bogus_short({"повреждёны", "повреждён", "Петрёна"}, {"повреждены"}) == {"повреждёны"}
    assert yo_split({"еще", "ещё", "кот"}, {"еще", "ещё", "кот"}) == ({"ещё", "кот"}, {"еще"})
    ymap = {"темно": "тёмно", "еж": "ёж"}
    assert yoify("темно-бурый", ymap) == "тёмно-бурый" and yoify("Темно-Бурый", ymap) == "Тёмно-Бурый"
    assert yoify("а--б", ymap) == "а--б"
    assert yoify_hyphenated({"темно-бурый", "кот-пес", "еж"}, ymap) == {"темно-бурый": "тёмно-бурый"}
    pairs = [("подождите", "VB:IMP:PL"), ("нас", "PNN:PL:R"), ("ее", "PNN:Fem:R"), ("новому", "ADJ:Posit:Masc:D")]
    assert particle_words(pairs, {"подождите", "нас", "новому"}) == {"подождите-ка", "нас-то", "по-новому"}
    aot = {"еще": 5, "ёж": 2, "все": 9, "всё": 3}
    assert freq("ещё", aot, {"ещё"}) == 50 and freq("всё", aot, {"все", "всё"}) == 30 and freq("кот", aot, set()) == 0
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "aot.raw").write_text("ещё+F\nкот+A\nпо+да+C\n", encoding="koi8_r")
        aot = read_aot(work)
        assert aot == {"ещё": 5, "кот": 0, "по+да": 2}, aot
        write(work, {"кот", "ещё", "a<b"}, aot | {"a<b": 1})
        assert (work / "merged.txt").read_text(encoding="utf-8") == "a<b\nещё\nкот\n"
        xml = (work / "freq.xml").read_text(encoding="utf-8")
        assert ' <w f="10" flags="">a&lt;b</w>\n <w f="50" flags="">ещё</w>\n</wordlist>' in xml and "кот" not in xml
        assert not (work / "merged.txt.tmp").exists()
        (work / "tags.raw").write_text("смотреть+смотрите+VB:IMP:PL\nкот+кот+NN:Anim:Masc:Sin:Nom\n", encoding="koi8_r")
        assert tag_pairs(work) == [["смотрите", "VB:IMP:PL"]]
    assert len(stamp()) == 64 * 6 and stamp() == stamp()  # merge.py, нужное из store.py, два .gz, два prohibited.txt
    try:
        verify({"еще"}, set())
    except AssertionError as e:
        assert str(e) == "еще"
    else:
        raise AssertionError("verify пропустил е-форму")
    if os.environ.get("SELFCHECK"):  # CI: только самопроверка
        sys.exit(0)
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
