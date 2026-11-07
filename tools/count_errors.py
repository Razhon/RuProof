#!/usr/bin/env python3
"""Подсчитать повторяющиеся ошибки LanguageTool по категориям.

запуск: count_errors.py [-u URL] [-t N] [-l] ФАЙЛ_ИЛИ_КАТАЛОГ...   (или текст на stdin)
Свои категории добавляются в RULES ниже.
"""

import argparse
import collections
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request

URL = "http://localhost:8081/v2/check"
LANG = "ru-RU"
CHUNK = 4000  # символов на запрос; сервер прерывает долгие проверки (maxCheckTimeMillis)


sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

# название -> предикат(исходное, вариант). Добавьте свои, например
# "тире": lambda o, f: "—" in f and "—" not in o and f.replace("—", "-") == o
RULES = {
    "ё": lambda o, f: o != f and o.lower() == f.lower().replace("ё", "е") and "ё" in f.lower(),
    "дефис": lambda o, f: o != f and "-" in f and "-" not in o and f.replace("-", "") == o.replace(" ", ""),
}


def texts(paths):
    if not paths:
        yield "stdin", sys.stdin.read()
        return
    for p in map(pathlib.Path, paths):
        for f in [p] if p.is_file() else sorted(p.rglob("*.txt")):
            yield str(f), f.read_text(encoding="utf-8", errors="replace")


def chunks(text):
    buf = ""
    for para in text.splitlines(keepends=True):
        if buf and len(buf) + len(para) > CHUNK:
            yield buf
            buf = ""
        buf += para
    if buf:
        yield buf


def check(text, url):
    data = urllib.parse.urlencode({"text": text, "language": LANG, "level": "picky"}).encode()
    with urllib.request.urlopen(
        url, data, timeout=90
    ) as r:  # больше 60 с сервера, чтобы его ответ с ошибкой пришёл раньше
        return json.load(r)["matches"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("-u", "--url", default=URL)
    ap.add_argument("-t", "--top", type=int, default=10, help="первые N пар на правило")
    ap.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="печатать каждое срабатывание с файлом",
    )
    a = ap.parse_args()
    total = collections.Counter()
    pairs = {r: collections.Counter() for r in RULES}
    for name, text in texts(a.paths):
        for part in chunks(text):
            try:
                matches = check(part, a.url)
            except (
                OSError,
                ValueError,
            ) as e:  # таймаут / ошибка HTTP: пропустить кусок, счёт сохранить
                print(f"{name}: кусок пропущен: {e}", file=sys.stderr)
                continue
            u = part.encode("utf-16-le")  # смещения LanguageTool — единицы UTF-16 (Java), а не символы
            for m in matches:
                o = u[2 * m["offset"] : 2 * (m["offset"] + m["length"])].decode("utf-16-le")
                for fix in (r["value"] for r in m["replacements"]):
                    hit = next((r for r, p in RULES.items() if p(o, fix)), None)
                    if hit:
                        total[hit] += 1
                        pairs[hit][(o, fix)] += 1
                        if a.list:
                            print(f"{name}: [{hit}] {o} -> {fix}")
                        break
    for r in RULES:
        print(f"\n{r}: {total[r]}")
        for (o, f), n in pairs[r].most_common(a.top):
            print(f"  {n:5}  {o} -> {f}")


if __name__ == "__main__":
    # самопроверка
    assert RULES["ё"]("еще", "ещё") and not RULES["ё"]("мама", "мамы")
    assert RULES["дефис"]("по русски", "по-русски") and RULES["дефис"]("почемуто", "почему-то")
    if os.environ.get("SELFCHECK"):  # CI: только самопроверка
        sys.exit(0)
    main()
