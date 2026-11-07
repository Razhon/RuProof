#!/usr/bin/env python3
"""Регрессионный набор прокси: тексты и ожидания по замечаниям, против запущенного прокси (нужен data/words.raw).

запуск: regress.py [URL]      по умолчанию http://localhost:8081
"""

import importlib.util
import json
import os
import sys
import time
import urllib.parse
import urllib.request

# константы правил берутся из самого прокси, чтобы идентификаторы не разошлись
_spec = importlib.util.spec_from_file_location(
    "proxy", os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy.py")
)
assert _spec and _spec.loader
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)


def spell(ms):
    return [m for m in ms if m["rule"]["id"] == P.SPELL]


def hard(ms):
    return [m for m in spell(ms) if m["rule"].get("issueType") != "style"]


def clean(ms):
    return not spell(ms)


def soft(ms):
    return bool(spell(ms)) and not hard(ms)


def firm(ms):
    return bool(spell(ms)) and hard(ms) == spell(ms)


def rule(rid):
    return lambda ms: any(m["rule"]["id"] == rid for m in ms)


def styled(rid):
    """Замечание правила rid есть, и все его замечания — стиль."""
    return lambda ms: rule(rid)(ms) and all(m["rule"]["issueType"] == "style" for m in ms if m["rule"]["id"] == rid)


def quotes(ms):
    return [m for m in ms if m["rule"]["id"] == P.GUILLEMETS]


def inner(ms):
    return [(m["offset"], m["replacements"][0]["value"]) for m in ms if m["rule"]["id"] == P.NESTED]


CASES = [
    # слова вне нормы и talk из образа в prose не замечание, и в авторском тексте тоже
    (
        "Йей, чесслово, Иван Иваныч пришёл.",
        lambda ms: not rule("RU_NONSTANDARD")(ms) and not rule("talk")(ms),
    ),
    # просторечие из replace.txt LT и слово ЗАГЛАВНЫМИ в prose не замечание
    ("Ну и чё ты стоишь? Он был ОЧЕНЬ зол.", lambda ms: not rule("RU_SIMPLE_REPLACE")(ms) and not rule("AllCaps")(ms)),
    ("Брумзик купил девайс.", lambda ms: not rule("RU_SIMPLE_REPLACE")(ms)),  # жаргон: пометка «Жаргон» в replace.txt
    ("Он тебе как бы нравится?", lambda ms: not rule("kak_bi")(ms)),  # слова-паразиты в prose не замечание
    ("Я хочу придти.", rule("RU_PROHIBITED")),  # ошибка из replace.txt остаётся ошибкой
    ("Брумзик пришёл. Потом Брумзик ушёл.", soft),
    ("Зербокс пришёл.", lambda ms: hard(ms)),
    ("П-прямо сюда, п-п-пожалуйста.", clean),
    ("— Ко-ко-конечно, — сказал он.", clean),
    ("П-првмо сюда.", lambda ms: hard(ms)),
    (
        "Нееет, не уходи, дааа!",
        lambda ms: len(hard(ms)) == 2 and hard(ms)[0]["replacements"][0]["value"] == "Не-е-ет",
    ),
    ("— Не-е-ет, — сказал он.", clean),
    ("— Ну-ну-ну-у, ха-ха-ха-а, — сказал он.", clean),  # повтор с растяжкой: части словарные
    ("— Ха-ха-ха-а! — сказал он.", clean),  # с заглавной: «Ха» тоже словарное
    ("Он сказал не-е-ет и ушёл.", clean),
    ("Он сказал нее-ет и ушёл.", lambda ms: hard(ms)),
    ("— Это не чел-овек, а Ком-пью-тер.", clean),
    ("Это не чел-овек, а Ком-пью-тер.", soft),
    ("— Ну, — Семён всё глядя на чел-овека.", soft),
    ("— Нет, я не тобо… Я пон...", clean),
    ("Он замолчал, не договорив: тобо…", soft),
    (
        "— Превет… — сказал он.",
        lambda ms: hard(ms),
    ),  # опечатка перед многоточием остаётся ошибкой
    (
        "— Мне надо подум… Я не понимае...",
        clean,
    ),  # нужен data/words.raw (сервис compose `words`)
    (
        "Брумзиллоп ушёл.\n— Брумзил… — позвал он.",
        lambda ms: not any(m["offset"] > 17 for m in spell(ms)),
    ),  # после тире нет подсказки: считается авторским текстом
    ("Я пришёл что-бы помочь.", lambda ms: hard(ms)),
    ("Он надел темно-синий свитер.", lambda ms: hard(ms)),
    ("Он говорил по-Русски.", lambda ms: hard(ms)),  # подсказка только в другом регистре
    ("Новый ресторан-лошадка.", clean),
    ("— Безоб Разие, — сказал он.", clean),
    ("Мы пошли в «Брумзи кул пекарня» вечером.", soft),
    ("Мы пошли в «Превет» вечером.", lambda ms: hard(ms)),
    ("Он сказал «превет».", lambda ms: hard(ms)),
    (
        "Брумзиллоп пришёл. Потом Брумзиллоп ушёл, а Брумзилоп остался.",
        lambda ms: [m["replacements"][0]["value"] for m in hard(ms)] == ["Брумзиллоп"],
    ),
    ("Брумзик Хворлип пришёл. Потом Брумзик Хворлип ушёл.", soft),
    (
        "Брумзилоп пришёл. Потом Брумзилоп ушёл.",
        soft,
    ),  # опечатка по всему тексту без правильного варианта: прокси не знает правды, только смягчает
    (
        "Он видел Наташю. Потом видел Наташю.",
        firm,
    ),  # LT предлагает словарное имя на букву дальше (Наталю): опечатка, не новое имя
    (
        "…Ва… ва… ва… ваше превосходительство, — шептал Попов.",
        lambda ms: not any(m["rule"]["id"] == "V.А" for m in ms),
    ),
    (
        "Что бы она ни хотела мне сказать, я этого уже не узнаю.",
        lambda ms: not any(m["rule"]["id"] == "CONFUSION_RULE_НИ_НЕ" for m in ms),
    ),
    (
        "Она ни хотела уходить.",
        lambda ms: any(m["rule"]["id"] == "CONFUSION_RULE_НИ_НЕ" for m in ms),
    ),
    (
        "Кому бы она, наверное, ни хотела помочь, всё зря.",
        lambda ms: not any(m["rule"]["id"] == "CONFUSION_RULE_НИ_НЕ" for m in ms),
    ),
    (
        "Что бы, конечно, кажется, она ни хотела, неважно.",
        lambda ms: not any(m["rule"]["id"] == "CONFUSION_RULE_НИ_НЕ" for m in ms),
    ),
    (
        "Я сделал бы всё, что она ни хотела.",
        lambda ms: not any(m["rule"]["id"] == "CONFUSION_RULE_НИ_НЕ" for m in ms),
    ),
    (
        "Кто бы мог подумать, что она ни хотела уходить.",
        lambda ms: any(m["rule"]["id"] == "CONFUSION_RULE_НИ_НЕ" for m in ms),
    ),
    ("«привет и ушёл", lambda ms: [m["offset"] for m in quotes(ms)] == [0]),
    ("привет» и ушёл", lambda ms: [m["offset"] for m in quotes(ms)] == [6]),
    ("«да» и «нет»", lambda ms: not quotes(ms)),
    ("«Первый.\n«Второй.»", lambda ms: not quotes(ms)),
    ("«Он ушёл. Потом пришёл.»", lambda ms: not quotes(ms)),
    (
        "«Он сказал: «Я приду. Жди». И ушёл».",
        lambda ms: inner(ms) == [(12, "„"), (25, "“")] and not quotes(ms),
    ),
    ("«Он сказал: „Я приду. Жди“. И ушёл».", lambda ms: not inner(ms)),
    ("Это статья «С кем вы, «мастера культуры»?».", lambda ms: not inner(ms)),
    (
        (
            "— Я не она. Но да, ты прав, — хоть я и не уверен насчёт того, что я — это он, "
            "отрицать наше сходство было бы глупо."
        ),
        lambda ms: not any(m["rule"]["id"] == "Many_PNN" for m in ms),
    ),
    (
        "— Ты прав, — хоть я и не уверен насчёт того, что я — это он, и что он — это я.",  # авторская часть и сама по себе перегружена
        lambda ms: [m["offset"] >= 13 for m in ms if m["rule"]["id"] == "Many_PNN"] == [True],
    ),
    (
        "Я видел блёдно‑серую стену.",
        lambda ms: hard(ms) and all(P.NBH in r["value"] for r in hard(ms)[0]["replacements"][:1]),
    ),
    (
        "Я видел тёмно‑синюю дом.",
        lambda ms: any(m["rule"]["id"] != P.SPELL for m in ms),
    ),
    (
        "Маркс писал, что «язык… есть самое».",
        lambda ms: any(m["rule"]["id"] == "kosvennaja_rech" for m in ms),
    ),
]

# режим neutral: приёмы прозы остаются ошибками, общие правила работают
NEUTRAL = [
    # слово вне нормы (build/words/nonstandard.txt): замечание стиля; замену пользователь мог сменить, её не проверяем
    ("Чесслово, Брумзик не брал.", rule("RU_NONSTANDARD")),
    # просторечие (LT шлёт его как опечатку) и ЗАГЛАВНЫЕ: замечание стиля
    ("Ну и чё ты стоишь?", styled("RU_SIMPLE_REPLACE")),
    ("Он был ОЧЕНЬ зол.", styled("AllCaps")),
    ("Брумзик пришёл. Потом Брумзик ушёл.", firm),  # имена не смягчаются
    # растяжка и заикание через дефис: подсказка стиля, словарная форма первой
    ("— Не-е-ет, — сказал он.", lambda ms: soft(ms) and spell(ms)[0]["replacements"][0]["value"] == "Нет"),
    ("— П-прямо сюда.", soft),
    ("— Ну-ну-ну-у.", lambda ms: soft(ms) and spell(ms)[0]["replacements"][0]["value"] == "Ну-ну-ну"),
    ("— Нее-ет, — сказал он.", firm),  # смешанная форма остаётся ошибкой
    ("— Это не чел-овек.", soft),  # речи нет: разбиение — подсказка
    ("— Нет, я не тобо… Я пон...", soft),
    ("Мы пошли в «Брумзи кул пекарня» вечером.", firm),
    ("Новый ресторан-лошадка.", clean),
    (
        "Брумзиллоп пришёл. Потом Брумзиллоп ушёл, а Брумзилоп остался.",
        lambda ms: [m["replacements"][0]["value"] for m in hard(ms) if m["offset"] == 44] == ["Брумзиллоп"],
    ),
    ("«привет и ушёл", lambda ms: [m["offset"] for m in quotes(ms)] == [0]),
    (
        "«Он сказал: «Я приду. Жди». И ушёл».",
        lambda ms: inner(ms) == [(12, "„"), (25, "“")],
    ),
    (
        "Что бы она ни хотела мне сказать, я этого уже не узнаю.",
        lambda ms: not rule("CONFUSION_RULE_НИ_НЕ")(ms),
    ),
    ("…Ва… ва… ва… ваше превосходительство, — шептал Попов.", styled("V.А")),  # запинка: подсказка, не ошибка
]


def first(ms):
    return [m["replacements"][0]["value"] for m in hard(ms) if m["replacements"]]


# каждый ключ по отдельности: (X-Proxy-Mode, текст, ожидание); пресет, где ключ включён, проверен выше
KEYS = [
    ("neutral compound=no", "Новый ресторан-лошадка.", firm),
    ("prose split=no", "— Это не чел-овек, а Ком-пью-тер.", firm),
    ("prose split=no", "— Безоб Разие, — сказал он.", firm),
    ("neutral split=no", "Это не чел-овек.", firm),  # и подсказкой не становится
    ("prose cut=no", "— Мне надо подум… Я не понимае...", firm),
    (
        "neutral stretch_hint=no",
        "Нееет, не уходи, дааа!",
        lambda ms: len(hard(ms)) == 2 and "Не-е-ет" not in first(ms),
    ),
    (
        "neutral variant=no",
        "Брумзиллоп пришёл. Потом Брумзиллоп ушёл, а Брумзилоп остался.",
        lambda ms: any(m["offset"] == 44 for m in hard(ms)) and "Брумзиллоп" not in first(ms),
    ),
    (
        "neutral concessive=no",
        "Что бы она ни хотела мне сказать, я этого уже не узнаю.",
        rule("CONFUSION_RULE_НИ_НЕ"),
    ),
    ("neutral guillemets=no", "«привет и ушёл", lambda ms: not quotes(ms)),
    (
        "neutral nested=no",
        "«Он сказал: «Я приду. Жди». И ушёл».",
        lambda ms: not inner(ms) and not quotes(ms),
    ),
    (
        "prose stretch=no",
        "П-прямо сюда, п-п-пожалуйста.",
        lambda ms: soft(ms) and len(spell(ms)) == 2,
    ),  # обе подсказки стиля (не снимаются)
    (
        "prose stammer=no",
        "…Ва… ва… ва… ваше превосходительство, — шептал Попов.",
        styled("V.А"),
    ),
    ("prose titles=no", "Мы пошли в «Брумзи кул пекарня» вечером.", firm),
    ("prose names=no", "Брумзик пришёл. Потом Брумзик ушёл.", firm),
    (
        "neutral names=yes",
        "Брумзик пришёл. Потом Брумзик ушёл.",
        soft,
    ),  # включение поверх пресета
    ("prose dialogue=no", "— Это не чел-овек, а Ком-пью-тер.", soft),
    ("prose nonstandard=no", "Йей, Брумзик пришёл!", rule("RU_NONSTANDARD")),
    ("prose nonstandard=no", "Ну и чё ты стоишь?", styled("RU_SIMPLE_REPLACE")),
    ("prose caps=no", "Он был ОЧЕНЬ зол.", styled("AllCaps")),
    ("prose fillers=no", "Он тебе как бы нравится?", rule("kak_bi")),
    (
        "prose dialogue=no",
        (
            "— Я не она. Но да, ты прав, — хоть я и не уверен насчёт того, что я — это он, "
            "отрицать наше сходство было бы глупо."
        ),
        rule("Many_PNN"),
    ),
]


def run(url, text, mode):
    data = urllib.parse.urlencode({"text": text, "language": "ru-RU", "level": "picky"}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/v2/check", data, {"X-Proxy-Mode": mode})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["matches"]


def regress(url):
    """Прогнать CASES (режим prose), NEUTRAL и KEYS против прокси на url, напечатать каждый случай; вернуть число
    провалов. Печатаются только придуманные тексты наборов, не текст пользователя."""
    for _ in range(60):  # LT за прокси только что (пере)запущен: ~30 с прокси отвечает 502; не дольше ~4 мин
        try:
            urllib.request.urlopen(url.rstrip("/") + "/v2/languages", timeout=2)
            break
        except OSError:
            time.sleep(2)
    else:
        sys.exit(f"FAIL прокси не отвечает на {url}: podman logs ruproof-proxy-1")
    bad = total = 0
    sets = [("prose", [("prose", *c) for c in CASES])]
    sets += [("neutral", [("neutral", *c) for c in NEUTRAL]), ("ключи", KEYS)]
    for name, cases in sets:
        print(f"--- {name}")
        for mode, text, want in cases:
            ms = run(url, text, mode)
            good = bool(want(ms))
            bad += not good
            total += 1
            print(
                f"{'ok  ' if good else 'FAIL'} {'' if mode == name else f'[{mode}] '}{text}   "
                f"{[(m['rule']['id'][:12], m['rule'].get('issueType'), m['replacements'][0]['value'] if m['replacements'] else '') for m in ms]}"
            )
    print(f"пройдено {total - bad}/{total}")
    return bad


if __name__ == "__main__":
    # самопроверка предикатов на готовых замечаниях
    sp = {"rule": {"id": P.SPELL}, "replacements": []}
    st = {"rule": {"id": P.SPELL, "issueType": "style"}, "replacements": []}
    q = {"rule": {"id": P.NESTED}, "offset": 3, "replacements": [{"value": "„"}]}
    assert clean([]) and clean([q]) and not clean([sp])
    assert soft([st]) and not soft([sp, st]) and not soft([])
    assert hard([sp, st]) == [sp] and inner([q, sp]) == [(3, "„")] and not quotes([q])
    assert firm([sp]) and not firm([sp, st]) and not firm([])
    assert rule(P.NESTED)([sp, q]) and not rule(P.NESTED)([sp])
    assert first([sp, st, {**sp, "replacements": [{"value": "а"}]}]) == ["а"]
    # у каждого ключа есть случай в KEYS, и заголовки KEYS принимает сам прокси
    assert {k.split("=")[0] for h, _, _ in KEYS for k in h.split()[1:]} == set(P.RULES)
    for h, _, _ in KEYS:
        P.header_mode(h)
    if os.environ.get("SELFCHECK"):  # CI: только самопроверка, без прокси
        sys.exit(0)
    args = sys.argv[1:]
    if len(args) > 1 or (args and args[0].startswith("-")):
        sys.exit(__doc__)
    sys.exit(1 if regress(args[0] if args else "http://localhost:8081") else 0)
