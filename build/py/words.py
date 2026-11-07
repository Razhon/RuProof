#!/usr/bin/env python3
"""Личные списки слов: добавить / удалить слова, разметить новые слова по аналогии, записать файлы, которые LanguageTool читает при старте.

запуск: [WORDS_ANSWERS=файл] words.py spelling|ignore|prohibited CLEAN [слово...]  добавить (spelling, ignore: спросит, как слово склоняется; prohibited: замену и ссылку)
        words.py remove слово...                              удалить из всех списков и из tagged.txt
        words.py migrate [ignore]                             разметить склоняемые слова, уже лежащие в spelling.txt (ignore.txt)
        words.py move слово...                                перенести слова (с блоками tagged) из другого слоя в этот
  WORDS_ANSWERS (rpdict -a): ответы на вопросы из файла, по строке на вопрос, пустая строка = Enter
  WORDS_LAYER=shared (rpdict -s): писать в общий слой build/words/ (в git); по умолчанию — в свой words/ (вне git)
  WORDS_NONSTD=1 (rpdict -u): после добавления пометить слова как слова вне нормы (nonstandard.txt) и спросить замену и ссылку
  CLEAN=1: убрать из spelling/ignore слова, которые уже есть в базовом словаре (отчёт последней сборки)
Каждый запуск сортирует списки выбранного слоя, убирает повторы и заново создаёт dict/{spelling_custom,ignore,added}.txt
из обоих слоёв.
Код выхода 3: ни один из этих файлов не изменился.
"""

import os
import sys
from collections import defaultdict

import forms
import store
from dialog import Choice, ask, cased, choose, fix_known, fix_own, known_ask, known_paras, para_labels, report, scripted
from store import (
    body,
    in_speller,
    mark,
    particle_base,
    put,
    read_list,
    read_tagged,
    write_list,
    write_tagged,
    yo_variants,
)


def add_spelling(words, clean_drop, have, target="spelling"):
    """Для каждого нового слова спросить: разметить (tagged.txt) или записать как есть (target: spelling.txt или ignore.txt).
    У ignore значения tagged получают метку IGNORE."""
    sp = read_list(target)
    tagged = read_tagged()
    # слов нет: индекс не загружаем
    interactive = (sys.stdin.isatty() or "WORDS_ANSWERS" in os.environ) and bool(words)
    if words and not interactive:
        print(f"! ввод не из терминала: слова записываются только в {target}.txt, без вопросов о склонении")
    ix = forms.Index() if interactive else None
    try:
        for w in words:
            # любая форма, не только лемма (Лавкрафта)
            lemmas = [lem for lem, (_, rs) in tagged.items() if any(f == w for f, _, _ in rs)]
            if lemmas or w in body(sp):
                heads = [h[2:] for lem in lemmas for h in tagged[lem][0]] or [
                    "только орфография" if target == "spelling" else "ignore, без склонения"
                ]
                title = f"уже в личном списке: {w} ({'; '.join(heads)})"
                if not interactive:
                    print(f"= {title}")
                a = known_ask(title, bool(lemmas)) if interactive else None
                if a == "д":
                    lem = fix_own(tagged, lemmas)
                    if lem:
                        print(f"+ tagged: {lem} (поправлено)")
                elif a == "з":
                    res = choose(ix, w, [], known=False, pending=tagged)
                    if isinstance(res, list):
                        report(tagged, mark(res, target), extra=bool(lemmas))
                        got = {f for _, rs in res for f, _, _ in rs}
                        sp = [line for line in sp if line.strip() not in got]  # теперь размечено
                continue
            # Лавкрафт: в speller есть, в теггере нет
            if w in have and not (ix and not ix.known(w)):
                paras = known_paras(ix, w) if ix else []
                lab = para_labels(ix, paras) if ix else ""
                title = f"уже есть в словаре: {w}" + (f" ({lab})" if lab else "")
                if not interactive:
                    print(f"= {title}")
                a = known_ask(title, bool(paras)) if interactive else None
                if a == "д":  # глазища: множественное число, которого нет в теггере
                    for block in mark(fix_known(ix, w, paras), target):
                        print(f"+ tagged: {put(tagged, block)} (добавлено форм: {len(block[1])})")
                elif a == "з":
                    res = choose(ix, w, [], known=False, pending=tagged)
                    if isinstance(res, list):
                        report(tagged, mark(res, target), extra=True)
                continue
            # основа должна быть в speller с обязательной ё, а не только в теггере (еще-то должно остаться ошибкой)
            if interactive and (base := particle_base(w)) and in_speller({base, base.lower()}):
                print(f"  {w}: известное слово с частицей или повтором, склонять нечего")
                res = Choice.SPELLING
            else:
                res = choose(ix, w, sorted(yo_variants(w) & have), pending=tagged) if interactive else Choice.SPELLING
            match res:
                case Choice.SKIP:
                    print(f"- пропущено: {w}")
                case Choice.SPELLING if w in have:
                    print(f"= уже есть в словаре: {w}")
                case Choice.SPELLING:
                    sp.append(w)
                    print(f"+ {target}: {w}")
                case blocks:
                    report(tagged, mark(blocks, target))
                    if w not in have and w not in {f for _, rs in blocks for f, _, _ in rs}:
                        # теггер знал слово (д дописал лишь недостающие формы), а орфография нет
                        sp.append(w)
    except EOFError:
        print("\n! ввод закончился (Ctrl+D): размеченное до этого слова записывается, остальные слова пропущены")
    write_tagged(tagged)
    write_list(target, sp, clean_drop)


def migrate(target="spelling"):
    """Сгруппировать слова списка target (spelling.txt или ignore.txt), являющиеся формами одного слова,
    спросить по разу на группу, заменить их размеченным блоком (у ignore — с меткой IGNORE)."""
    ix = forms.Index()
    sp = read_list(target)
    # слова с U+2011 LT пропускает (прокси превращает его в '-')
    fixed = [line.replace("‑", "-") for line in sp]
    if fixed != sp:
        print(f"U+2011 -> '-': {sum(a != b for a, b in zip(sp, fixed))} слов")
        sp = fixed
        write_list(target, sp)
    skipf = store.W / "migrate-skip.txt"
    skipped = set(skipf.read_text(encoding="utf-8").splitlines()) if skipf.exists() else set()
    words = sorted(w for w in body(sp) if w not in skipped and not ix.known(w))
    base = {w: b for w in words if (b := particle_base(w))}
    bases = in_speller({x for b in base.values() for x in (b, b.lower())})
    # они-то: остаётся в списке
    words = [w for w in words if not (w in base and {base[w], base[w].lower()} & bases)]
    cover, score = defaultdict(set), defaultdict(int)
    for w in words:
        for lem, pid, n in ix.guess(w, top=15):
            cover[(lem, pid)].add(w)
            score[(lem, pid)] += n
    left, groups = set(words), []
    while left:
        k = max(cover, key=lambda k: (len(cover[k] & left), score[k]), default=None)
        if k is None or not cover[k] & left:
            break
        groups.append((k, sorted(cover[k] & left)))
        left -= cover[k]
    groups += [((None, None), [w]) for w in sorted(left)]
    print(f"{len(words)} слов -> {len(groups)} групп; q = выйти (сделанное сохраняется)")
    try:
        for i, ((lem, pid), ws) in enumerate(groups, 1):
            # их могла разметить предыдущая группа (исекай)
            ws = [w for w in ws if w in body(read_list(target))]
            if not ws:
                continue
            print(f"\n[{i}/{len(groups)}]", end="")
            word = cased(ws[0], lem) if lem else ws[0]
            if ask(" Enter = разобрать, q = выйти: ").lower() == "q":
                break
            res = choose(ix, word, [], preferred=[(lem, pid)] if lem else None, listed=ws)
            if isinstance(res, Choice):
                with open(skipf, "a", encoding="utf-8") as f:
                    f.write("".join(w + "\n" for w in ws))
                continue
            tagged = read_tagged()
            lemma = ", ".join(dict.fromkeys(put(tagged, b) for b in mark(res, target)))
            write_tagged(tagged)
            got = {f for _, rs in res for f, _, _ in rs}
            write_list(target, [line for line in read_list(target) if line.strip() not in got])
            rest = [w for w in ws if w not in got]
            print(f"+ tagged: {lemma}" + (f"; не покрыты, остаются в {target}: {' '.join(rest)}" if rest else ""))
            store.generate()
    except EOFError:
        print("\n! ввод закончился (Ctrl+D): сделанное сохранено")


def valid_args(a: list[str]) -> bool:
    """Аргументы подходят под строку «запуск:» (аргументы migrate проверяет его ветка)."""
    match a:
        case ["migrate", *_]:
            return True
        case ["remove" | "move", _, *_]:
            return True
        case [target, "0" | "1", *_]:
            return target in store.LISTS
    return False


def main(target, clean, words):
    have = set()  # слова, которые уже есть в последнем собранном словаре (для prohibited не проверяется)
    if words and target != "prohibited":
        # что с ними делать, решает add_spelling: у слова, известного speller, может не быть тегов
        have = in_speller({v for w in words for v in (w, *yo_variants(w))})
    rep = store.W / "report-redundant-words.txt"
    if clean and not rep.exists():
        sys.exit("нет отчёта: сначала запустите rpdict один раз без -c")
    redundant = set(rep.read_text(encoding="utf-8").splitlines()) if clean else set()
    new = list(words)
    if target != "prohibited":
        # prohibited любого слоя вычитается из словаря (generate, merge.py) в любом регистре: молча записанное слово
        # LT всё равно отвергнет
        for layer in (store.OWN, store.OTHER):
            pr = store.lower_only({store.key(w) for w in store.read_pairs("prohibited", layer)})
            flag = "-s " if layer == store.SHARED else ""
            for w in new:
                if w.lower() in pr:
                    print(f"! {w}: есть в {layer.name} prohibited.txt, LT его отвергает; сначала rpdict {flag}-r {w}")
            new = [w for w in new if w.lower() not in pr]
        # слово другого слоя LT уже принимает: второй раз его не записывать
        there = store.other_words()
        for w in new:
            if w in there:
                print(f"= уже есть в {store.OTHER.name} списке: {w}")
        new = [w for w in new if w not in there]
    for n in store.LISTS:
        drop = redundant if n != "prohibited" else frozenset()
        if n == target != "prohibited":
            add_spelling(new, drop, have, target)
            continue
        if n == target:  # prohibited: spelling и ignore ушли в add_spelling
            mark_prohibited(new)
        else:
            write_list(n, read_list(n), drop)
    if os.environ.get("WORDS_NONSTD"):
        if target == "prohibited":
            print("! -u не действует с prohibited: слово не помечено")
        else:
            mark_nonstd(words, have)


def mark_nonstd(words, have):
    """rpdict -u: пометить слова, которые LT теперь принимает, как слова вне нормы (nonstandard.txt своего слоя) и
    спросить замену для нейтрального текста. Пропущенное в диалоге слово не помечается."""
    own = {f for _, rs in read_tagged().values() for f, _, _ in rs}
    known = have | store.other_words() | own | {w for n in store.LISTS[:2] for w in body(read_list(n))}
    interactive = sys.stdin.isatty() or "WORDS_ANSWERS" in os.environ
    ns, shared = store.read_pairs(store.NONSTD), store.read_pairs(store.NONSTD, store.OTHER)
    try:
        for w in words:
            if w not in known:
                print(f"! {w}: нет в словаре, не помечено как слово вне нормы")
                continue
            old = ns.get(w, shared.get(w, ""))
            ns[w] = ask_pair(w, old, " в нейтральном тексте") if interactive else old
            print(f"+ {store.NONSTD}: {w}" + (f" = {ns[w]}" if ns[w] else ""))
    except EOFError:
        print("\n! ввод закончился (Ctrl+D): помеченное до этого слова записывается")
    store.write_pairs(store.NONSTD, ns)


def mark_prohibited(words):
    """rpdict -p: записать слова в prohibited.txt своего слоя и спросить замену для подсказки и ссылку на неё.
    Слово, уже записанное, можно так же переспросить: Enter оставляет прежнее."""
    interactive = sys.stdin.isatty() or "WORDS_ANSWERS" in os.environ
    pr = store.read_pairs("prohibited")
    try:
        for w in words:
            if " " in w and w.endswith("*"):  # до pop: иначе прежняя запись фразы пропала бы вместе с этой
                print(f"! {w}: у фразы нет форм, метка * к ней не относится; не записано")
                continue
            # то же слово с другой меткой (Лавкрафтовский <-> Лавкрафтовский*) заменяется, ссылка сохраняется
            old = next((pr.pop(k) for k in list(pr) if store.key(k) == store.key(w) and k != w), pr.get(w, ""))
            rep = ask_pair(w, old, "") if interactive else old
            if " " in w and not store.split_url(rep)[0]:  # фразу ловит только правило с заменой (rules.py, prohibited)
                print(f"! {w}: у фразы нужна замена, без неё её ничто не отметит; не записано")
                continue
            pr[w] = rep
            print(f"+ prohibited: {w}" + (f" = {pr[w]}" if pr[w] else ""))
    except EOFError:
        print("\n! ввод закончился (Ctrl+D): записанное до этого слова сохраняется")
    store.write_pairs("prohibited", pr)


def ask_pair(w, old, where):
    """Замена и ссылка-подтверждение для строки «слово = замена ссылка»: Enter оставляет прежнее, «-» убирает."""
    rep, url = store.split_url(old)
    if w.endswith("*"):  # все формы: подсказка — найденная форма строчными, замена не нужна
        rep = ""
    else:
        while True:
            if " " in w:
                keep = f"Enter — оставить «{rep}»" if rep else "обязательно"
            else:
                keep = f"Enter — оставить «{rep}», - — без замены" if rep else "Enter — без замены"
            a = ask(f"  Чем заменить «{w}»{where} ({keep}): ")
            rep = "" if a == "-" else a or rep
            if rep or " " not in w:
                break
            print("  ! у фразы замена обязательна: её слова верны по отдельности, без замены её ничто не отметит")
    while True:
        keep = "Enter — оставить, - — без ссылки" if url else "Enter — без ссылки"
        a = ask(f"  Ссылка-подтверждение замены, http(s)://… ({keep}): ")
        if not a or a == "-" or (a.startswith(("http://", "https://")) and " " not in a):
            break
        print("  ! нужна ссылка, начинающаяся с http:// или https://, без пробелов")
    url = "" if a == "-" else a or url
    return f"{rep} {url}".strip()


if __name__ == "__main__":
    # самопроверка; свой слой и W — во временном каталоге: настоящие файлы не затрагиваются
    import contextlib
    import io
    import tempfile
    from pathlib import Path
    from unittest import mock

    from dialog import NoIndex, answer

    assert valid_args(["spelling", "0"]) and valid_args(["ignore", "1", "брум"]) and valid_args(["migrate"])
    assert valid_args(["remove", "брум"]) and not valid_args(["remove"]) and not valid_args([])
    assert not valid_args(["spelling"]) and not valid_args(["foo", "0"]) and not valid_args(["spelling", "да"])
    tmp, tmp2 = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())

    class Tty:
        def isatty(self):
            return True

    with (
        mock.patch.multiple(store, OWN=store.Layer(tmp, "своём"), OTHER=store.Layer(tmp2, "общем"), W=tmp),
        mock.patch("sys.stdin", Tty()),
        mock.patch("forms.Index", NoIndex),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        # Enter на вопросе об известном слове ничего не меняет; з дописывает значение к блоку, а не заменяет его
        one = {"Брумзик": (["# Брумзик: x"], [("Брумзик", "Брумзик", "NN:Name:Masc:Sin:Nom")])}
        write_tagged(one)
        with mock.patch("builtins.input", answer()):
            add_spelling(["Брумзик"], frozenset(), set())
        assert read_tagged() == one
        with mock.patch(
            "builtins.input", answer(("Enter = ничего", "з"), ("выбор", "н"), ("род [", "ж"), ("имя или", "н"))
        ):
            add_spelling(["Брумзик"], frozenset(), set())
        ((head, rows),) = read_tagged().values()
        assert len(head) == 2 and len(rows) == 7, rows
        # д: правится одно значение (неодуш. ж.р., оно первое), другое остаётся
        with mock.patch("builtins.input", answer(("Enter = ничего", "д"), ("какое", "1"), ("Р. ед.", "Брумзика"))):
            add_spelling(["Брумзик"], frozenset(), set())
        ((head, rows),) = read_tagged().values()
        assert (
            ("Брумзика", "Брумзик", "NN:Inanim:Fem:Sin:R") in rows
            and ("Брумзик", "Брумзик", "NN:Name:Masc:Sin:Nom") in rows
            and len(rows) == 7
        ), rows
        # Ctrl+D на втором слове: первое, уже размеченное, записано; второе не попадает ни в tagged, ни в список
        first, picks = answer(("выбор", "н"), ("род [", "ж"), ("имя или", "н")), []

        def eof_on_second(p=""):
            if "выбор" in p and picks.append(p) is None and len(picks) > 1:
                raise EOFError
            return first(p)

        was = read_tagged()
        with mock.patch("builtins.input", eof_on_second):
            add_spelling(["Брумза", "Брумзило"], frozenset(), set())
        now = read_tagged()
        assert len(picks) == 2 and now.keys() == was.keys() | {"Брумза"}, now.keys()
        assert not {"Брумза", "Брумзило"} & set(read_list("spelling"))
        # -i: размеченное слово получает метку, 0 пишет плоскую строку в ignore.txt
        with mock.patch("builtins.input", answer(("выбор", "н"), ("род [", "м"), ("имя или", "н"))):
            add_spelling(["брумзяк"], frozenset(), set(), "ignore")
        with mock.patch("builtins.input", answer(("выбор", "0"))):
            add_spelling(["брумс-брумс"], frozenset(), set(), "ignore")
        head = read_tagged()["брумзяк"][0]
        assert store.ignored(head) and head[0].endswith(store.IGNORE), head
        assert body(read_list("ignore")) == {"брумс-брумс"}, read_list("ignore")
        # -u: помечается только слово, которое LT принимает; Enter оставляет замену, «-» её убирает
        with mock.patch("builtins.input", answer(("Чем заменить", "брумс"))):
            mark_nonstd(["брумс-брумс", "зыкс"], set())
        assert store.read_pairs(store.NONSTD) == {"брумс-брумс": "брумс"}, store.read_pairs(store.NONSTD)
        with mock.patch("builtins.input", answer()):
            mark_nonstd(["брумс-брумс"], set())
        assert store.read_pairs(store.NONSTD) == {"брумс-брумс": "брумс"}
        with mock.patch("builtins.input", answer(("Чем заменить", "-"))):
            mark_nonstd(["брумс-брумс"], set())
        assert store.read_pairs(store.NONSTD) == {"брумс-брумс": ""}
        # слово из prohibited любого слоя (в любом регистре) не записывается ни в spelling, ни в ignore
        write_list("prohibited", ["брумц"])
        (tmp2 / "prohibited.txt").write_text("брумщ\n", encoding="utf-8")
        was = read_tagged()
        main("spelling", False, ["Брумц", "брумщ"])
        main("ignore", False, ["брумщ"])
        assert read_tagged() == was and body(read_list("ignore")) == {"брумс-брумс"}
        assert not {"Брумц", "брумщ"} & body(read_list("spelling"))
        # -p: замена и ссылка в строке; не-ссылка переспрашивается; Enter при повторе оставляет всё
        ans = answer(("Чем заменить", "брум"), ("Ссылка", ["x.org", "https://x.org"]))
        with mock.patch("builtins.input", ans):
            main("prohibited", False, ["брумц"])
        assert read_list("prohibited")[-1] == "брумц = брум https://x.org", read_list("prohibited")
        with mock.patch("builtins.input", answer()):
            main("prohibited", False, ["брумц"])
        assert store.read_pairs("prohibited") == {"брумц": "брум https://x.org"}
        # слово с заменой в prohibited всё так же не записывается в spelling
        main("spelling", False, ["брумц"])
        assert "брумц" not in body(read_list("spelling"))
        # слово с заглавной: метка * сменяет строку без неё (ссылка остаётся, замену не спрашивает)
        with mock.patch("builtins.input", answer(("Чем заменить", "-"), ("Ссылка", "https://x.org"))):
            main("prohibited", False, ["Брумзяк"])
        with mock.patch("builtins.input", answer(("Ссылка", ""))):
            main("prohibited", False, ["Брумзяк*"])
        assert store.read_pairs("prohibited") == {"Брумзяк*": "https://x.org", "брумц": "брум https://x.org"}
        # фраза: пустая замена и «-» переспрашиваются, без замены фраза не записывается
        with mock.patch("builtins.input", answer(("Чем заменить", ["", "-", "брумщ"]))):
            main("prohibited", False, ["брум щ"])
        assert store.read_pairs("prohibited")["брум щ"] == "брумщ"
        # фраза с меткой * не записывается и прежнюю запись не стирает
        main("prohibited", False, ["брум щ*"])
        assert store.read_pairs("prohibited")["брум щ"] == "брумщ"
    if os.environ.get("SELFCHECK"):  # CI: только самопроверка
        sys.exit(0)
    store.WRITES.clear()  # записи самопроверки (во временный каталог) не в счёт
    a = sys.argv[1:]
    if not valid_args(a):
        sys.exit(__doc__)
    words = [w.strip() for w in a[2:] if w.strip()]
    left = scripted(os.environ["WORDS_ANSWERS"]) if "WORDS_ANSWERS" in os.environ else []
    if a[:1] == ["remove"]:
        store.remove({w.strip() for w in a[1:] if w.strip()})
        flag = "" if store.OWN == store.SHARED else "-s "
        for w in sorted({w.strip() for w in a[1:]} & store.other_words()):
            print(f"! {w} есть и в {store.OTHER.name} списке: rpdict {flag}-r {w}")
    elif a[:1] == ["move"]:
        store.move({w.strip() for w in a[1:] if w.strip()})
    elif a[:1] == ["migrate"]:
        if a[1:] not in ([], ["ignore"]):
            sys.exit(__doc__)
        migrate(*a[1:])
    else:
        main(a[0], a[1] == "1", words)
    store.generate()
    if left:
        sys.exit(f"! лишние ответы ({len(left)}): вопросов было меньше, ответы могли уйти не в те вопросы")
    if not store.WRITES:
        sys.exit(3)  # ни один файл не изменился: rpdict пропускает rules и перезапуск
