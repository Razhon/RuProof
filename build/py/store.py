#!/usr/bin/env python3
"""Слои личных слов: списки spelling/ignore/prohibited и tagged.txt, общий слой build/words/ и свой words/;
файлы dict/, которые LanguageTool читает при старте. Читают words.py (rpdict) и merge.py.

запуск: store.py — только самопроверка (модуль импортируют words.py, dialog.py и merge.py)
  WORDS_LAYER=shared (rpdict -s): свой слой — общий build/words/ (в git); по умолчанию — words/ в корне (вне git)
"""

import os
import re
import subprocess
import sys
import time
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import NamedTuple

B = Path(__file__).parent.parent  # build/: скрипты лежат в build/py/
W, D = B / ".work", B.parent / "dict"
LISTS = ("spelling", "ignore", "prohibited")


# общий слой (в git, правится через rpdict -s) и свой (words/ в корне, в .gitignore): обновление проекта не конфликтует со своими словами
class Layer(NamedTuple):
    """Слой слов: каталог со списками и tagged.txt; name — как слой назван в сообщениях («есть в общем списке»)."""

    dir: Path
    name: str

    @property
    def tagged(self) -> Path:
        return self.dir / "tagged.txt"


SHARED, LOCAL = Layer(B / "words", "общем"), Layer(B.parent / "words", "своём")
# свой слой (OWN) пишется, другой (OTHER) только читается; функции без layer берут OWN в момент вызова
OWN, OTHER = (SHARED, LOCAL) if os.environ.get("WORDS_LAYER") == "shared" else (LOCAL, SHARED)
# метка в конце заголовка значения (rpdict -i): формы блока идут в ignore.txt — принимаются, но не предлагаются
IGNORE = " (ignore)"

_MORE = "# Подробнее: build/README.md, «Какой файл выбрать»."
_LIST = "# По слову на строку. Строки с # остаются наверху, остальные rpdict сортирует."
# шапка файла слов: пишется, когда в файле её нет (новый файл своего слоя); написанную руками rpdict не трогает
HEADS = {
    "spelling": (
        "# Слова, которые LT принимает и предлагает как исправление опечатки (rpdict, выбор 0).",
        "# Сюда: несклоняемые слова и слова, которые не размечаются (атас, чем-нибудь).",
        "# Склоняемые — в tagged.txt: тогда принимаются все формы и работает согласование.",
        _LIST,
        _MORE,
    ),
    "ignore": (
        "# Слова, которые LT принимает, но не предлагает как исправление (rpdict -i, выбор 0).",
        "# Сюда: междометия, растянутые звуки, сокращения, намеренные искажения (кхм, э-э-э, досл).",
        "# Короткое слово здесь не всплывает в подсказках к чужим опечаткам. Склоняемые — в tagged.txt с меткой (ignore).",
        _LIST,
        _MORE,
    ),
    "prohibited": (
        "# Формы, которые есть в словаре LT, но неверны (rpdict -p): они удаляются из словаря, и LT их отмечает",
        "# в любом регистре (распросы). Строка «слово», «слово = замена» или «слово = замена https://…»: замена",
        "# идёт в подсказку (нахер = на хер), ссылка подтверждает её. Новое слово пересобирает словарь (~2 мин).",
        "# Слово с заглавной (Лавкрафтовский) остаётся в словаре: LT отмечает его только в середине предложения",
        "# и подсказывает строчное; с меткой * (Лавкрафтовский*) — все формы слова. Слово не из словаря с заменой —",
        "# точная подсказка вместо догадки speller (оплоченный = оплаченный). Фраза (во внутрь = внутрь) — только",
        "# с заменой: её слова верны по отдельности. Сюда же — ошибки, убранные из replace.txt LT (rules.py, REPLACE_DROP).",
        _LIST,
        _MORE,
    ),
    "nonstandard": (
        "# Слова вне литературной нормы (rpdict -u): разговорные, просторечные, жаргонные (оу, кхм, чувак).",
        "# Строка «слово», «слово = замена» или «слово = замена https://…». В режиме neutral — замечание стиля (с заменой в подсказке),",
        "# в prose замечание снимается. Пометка словарь не меняет: само слово лежит в другом списке или в tagged.txt.",
        _LIST,
        _MORE,
    ),
    "tagged": (
        "# Склоняемые слова с тегами (rpdict, выбор 1–3/н/нр): LT принимает все формы, знает их для согласования",
        "# и подсказок. Блок на слово, блоки через пустую строку: «# лемма: комментарий», затем строки",
        "# «форма<TAB>лемма<TAB>тег». Блок, у которого каждый заголовок кончается на « (ignore)» (rpdict -i),",
        "# принимается, но не предлагается как исправление.",
        "# Этот абзац — шапка файла: rpdict держит его наверху, отдельно от блоков.",
        _MORE,
    ),
}

type Row = tuple[str, str, str]  # строка tagged.txt: форма, лемма, тег
type Block = tuple[list[str], list[Row]]  # значение: строки-комментарии над ним и его строки


def ignored(head):
    """Блок только принимается, если все его значения с меткой: одно обычное значение — и слово предлагается."""
    return bool(head) and all(h.endswith(IGNORE) for h in head)


def mark(blocks: list[Block], target: str) -> list[Block]:
    """Значения из choose/fix_known для rpdict -i получают метку."""
    if target != "ignore":
        return blocks
    return [([h + IGNORE for h in head], rows) for head, rows in blocks]


def tidy(lines, drop: AbstractSet[str] = frozenset()):
    head = [line for line in lines if line.startswith("#")]
    # порядок кодовых точек = sort при LC_ALL=C
    return head + sorted(body(lines) - drop)


def read_list(n, layer: Layer | None = None):
    p = (layer or OWN).dir / f"{n}.txt"
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def read_all(n):
    """Строки списка из обоих слоёв: их читают генерация dict/ и merge.py."""
    return read_list(n, SHARED) + read_list(n, LOCAL)


WRITES: list[Path] = []  # файлы, которые save() действительно переписал: пусто — rpdict пропускает rules и перезапуск


def save(p, text):
    """Запись через временный файл: сбой записи (ответ, который нельзя закодировать) не должен оставить список пустым.
    Тот же текст не пишется: mtime не меняется, и прокси не перечитывает файл зря."""
    data = text.encode("utf-8")
    if p.exists() and p.read_bytes() == data:
        return
    p.parent.mkdir(parents=True, exist_ok=True)  # words/ появляется при первой записи
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    WRITES.append(p)


def write_list(n, lines, drop: AbstractSet[str] = frozenset(), layer: Layer | None = None):
    p = (layer or OWN).dir / f"{n}.txt"
    if lines or p.exists():
        if not any(line.startswith("#") for line in lines):
            lines = [*HEADS[n], *lines]
        save(p, "\n".join(tidy(lines, drop)) + "\n")


def body(lines):
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


# nonstandard.txt (rpdict -u): слова вне литературной нормы. Слово остаётся в словаре как есть, отмечает его правило
# RU_NONSTANDARD (rules.py): так в его тегах ничего не меняется. У nonstandard.txt и prohibited.txt строка «слово»,
# «слово = замена» или «слово = замена https://…» (ссылка-подтверждение: последний токен с http:// или https://)
NONSTD = "nonstandard"


def key(line):
    """Слово строки списка: «мда = м-да» -> мда, «Лавкрафтовский*» -> Лавкрафтовский (метка * — все формы)."""
    return head(line).rstrip("*")


def head(line):
    """Слово строки как записано, с меткой *."""
    return line.partition("=")[0].strip()


def lower_only(words):
    """Из словаря вычитаются только строчные слова prohibited: слово с заглавной (Лавкрафтовский) отмечает правило
    RU_PROHIBITED только в середине предложения, строчное и имя (Москва) остаются в словаре. Фразы (во внутрь) в
    словаре нет: её ловит только правило, и словарь из-за неё не пересобирается."""
    return {w for w in words if w == w.lower() and " " not in w}


def split_url(v):
    """Значение «замена ссылка» -> (замена, ссылка); замена может содержать пробел (на хер)."""
    head, _, last = v.rpartition(" ")
    return (head.strip(), last) if last.startswith(("http://", "https://")) else (v, "")


def pairs(lines) -> dict[str, str]:
    """Строки «слово = замена ссылка» -> слово -> «замена ссылка» ("" — без замены)."""
    return {head(line): line.partition("=")[2].strip() for line in lines}


def read_pairs(n, layer: Layer | None = None) -> dict[str, str]:
    return pairs(body(read_list(n, layer)))


def read_pairs_all(n) -> dict[str, str]:
    """Оба слоя; замена из своего слоя важнее общей."""
    return read_pairs(n, SHARED) | read_pairs(n, LOCAL)


def write_pairs(n, d: dict[str, str], layer: Layer | None = None):
    head = [line for line in read_list(n, layer) if line.startswith("#")]
    write_list(n, head + [f"{k} = {v}" if v else k for k, v in d.items()], layer=layer)


# tagged.txt: по блоку на слово, «# лемма: комментарий», затем строки «форма<TAB>лемма<TAB>тег» (формат added_custom.txt)
def read_tagged(layer: Layer | None = None) -> dict[str, Block]:
    path = (layer or OWN).tagged
    blocks = {}
    if path.exists():
        for chunk in path.read_text(encoding="utf-8").split("\n\n"):
            lines = [line for line in chunk.splitlines() if line.strip()]
            if bad := next((line for line in lines if not line.startswith("#") and line.count("\t") != 2), None):
                sys.exit(f"{path}: нужно форма<TAB>лемма<TAB>тег, а строка: {bad!r}")
            # каждая строка и комментарий над ней относятся к лемме этой строки: если между блоками нет пустой строки,
            # -r одного не должен удалить другой; пустая строка внутри блока или второй блок той же леммы — объединяются
            head = []
            for line in lines:
                if line.startswith("#"):
                    head.append(line)
                else:
                    form, lem, tag = line.split("\t")  # три поля проверены выше
                    put(blocks, (head, [(form, lem, tag)]))
                    head = []
    return blocks


def read_tagged_all() -> dict[str, Block]:
    """Блоки tagged.txt обоих слоёв (общий, затем свой)."""
    tagged = read_tagged(SHARED)
    for b in read_tagged(LOCAL).values():
        put(tagged, b)
    return tagged


def put(blocks: dict[str, Block], block: Block) -> str:
    """Добавить блок; ещё одна недостающая форма того же известного слова присоединяется к его блоку."""
    head, rows = block
    lemma = rows[0][1]
    old = blocks.get(lemma, ([], []))
    blocks[lemma] = (
        old[0] + [h for h in head if h not in old[0]],
        sorted(set(old[1]) | set(rows)),
    )
    return lemma


def tagged_head(path: Path) -> list[str]:
    """Шапка tagged.txt: первый абзац из одних комментариев (read_tagged его пропускает: у него нет строк)."""
    first = path.read_text(encoding="utf-8").split("\n\n", 1)[0].splitlines() if path.exists() else []
    return first if first and all(line.startswith("#") for line in first) else list(HEADS["tagged"])


def write_tagged(blocks: dict[str, Block], layer: Layer | None = None):
    path = (layer or OWN).tagged
    out = [
        "\n".join(head + ["\t".join(r) for r in rows])
        for _, (head, rows) in sorted(blocks.items(), key=lambda kv: kv[0].lower())
    ]
    if out or path.exists():  # пустой слой не создаёт файл
        save(path, "\n\n".join(["\n".join(tagged_head(path)), *out]) + "\n")


def in_speller(cands):
    """Те из cands, что есть в последнем собранном словаре (merged.txt, ~4,5 млн строк: grep в 5 раз быстрее цикла на Python)."""
    merged = W / "merged.txt"
    if not cands or not merged.exists():
        return set()
    out = subprocess.run(
        ["grep", "-Fx", "-f", "-", str(merged)],
        check=False,
        input="\n".join(cands) + "\n",
        capture_output=True,
        encoding="utf-8",
    )
    if out.returncode > 1:
        sys.exit(out.stderr)
    return set(out.stdout.splitlines())


PARTICLES = ("ка", "то", "таки", "с", "де", "нибудь", "либо")
# наречия на по-, merge.py импортирует это
PO = re.compile(r"ADJ:Short:PL .*[сц]ки|ADJ:Posit:PL:Nom .*ьи|ADJ:Posit:Masc:D .*[оеё]му")


def particle_base(w):
    """сделал-таки -> сделал, смейся-смейся -> смейся: у слова с частицей или повтором через дефис
    склонять нечего (LT видит одно слово)."""
    base, _, p = w.rpartition("-")
    if base and len(set(w.lower().split("-"))) == 1:
        # нет-нет-нет: повторов сколько угодно, само слово должно быть известно
        return w.split("-")[0]
    return base if base and p in PARTICLES else None


def yo_variants(w):
    return {w[:i] + ("ё" if c == "е" else "Ё") + w[i + 1 :] for i, c in enumerate(w) if c in "еЕ"}


def generate():
    """Файлы, которые монтируются в контейнер (compose.yaml): пересобирать словарь не нужно."""
    sp, ig, pr = ({key(line) for line in body(read_all(n))} for n in LISTS)
    tagged = read_tagged_all()
    for head, rows in tagged.values():
        # формы и наречия на по- от них (по-лавкрафтиански)
        (ig if ignored(head) else sp).update(
            {f for f, _, _ in rows} | {"по-" + f for f, _, t in rows if PO.fullmatch(f"{t} {f}")}
        )
    gen = "# создано build/py/store.py из build/words/ и words/ (не править вручную)\n"
    save(D / "spelling_custom.txt", gen + "\n".join(sorted(sp - lower_only(pr))) + "\n")
    # то, что идёт с образом (что-что)
    image_ignore = body((W / "ignore.orig.txt").read_text(encoding="utf-8").splitlines())
    # LGPL 2.1, раздел 2b
    lt = (
        f"# Изменено в {time.strftime('%Y')} году, Razhon (build/py/store.py): к файлу из LanguageTool "
        "(GNU LGPL 2.1 или более поздняя) добавлены слова из build/words/ и words/\n"
    )
    save(D / "ignore.txt", gen + lt + "\n".join(sorted((ig | image_ignore) - pr)) + "\n")
    # added.txt, а не added_custom.txt: синтезатор LT (подсказки postag_replace) читает только added.txt
    orig = (W / "added.orig.txt").read_text(encoding="utf-8").splitlines()
    rows = sorted({tuple(r) for _, rs in tagged.values() for r in rs} - {tuple(line.split("\t")) for line in orig})
    save(D / "added.txt", lt + "\n".join(orig + ["\t".join(r) for r in rows]) + "\n")


def remove(words, layer: Layer | None = None):
    """Удалить слова из списков и tagged.txt слоя (по умолчанию своего)."""
    listed = set()
    for n in LISTS:
        lines = read_list(n, layer)
        # по слову строки: «мда = м-да» снимается словом мда
        if gone := [key(line) for line in lines if key(line) in words and not line.startswith("#")]:
            print(f"- {n}: {' '.join(gone)}")
            listed |= set(gone)
        write_list(n, [line for line in lines if line.startswith("#") or key(line) not in words], layer=layer)
    # слово, найденное в списке, удаляется только оттуда: одна-две остаётся формой блока один-два
    forms_out = set(words) - listed
    tagged = read_tagged(layer)
    for lemma, (head, rows) in list(tagged.items()):
        # # полугорящий: блок причастия с леммой полугореть
        named = {h[2:].partition(":")[0] for h in head}
        keep = (
            []
            if lemma in words or lemma.lower() in words or named & set(words)
            else [r for r in rows if r[0] not in forms_out]
        )
        if keep != rows:
            print(f"- tagged: {lemma}" + (f" ({len(rows) - len(keep)} строк)" if keep else ""))
            tagged[lemma] = (head, keep)
            if not keep:
                del tagged[lemma]
    write_tagged(tagged, layer)
    # слово, которого больше нет в словаре, не помечается
    ns = read_pairs(NONSTD, layer)
    if gone := sorted(ns.keys() & set(words)):
        print(f"- {NONSTD}: {' '.join(gone)}")
        write_pairs(NONSTD, {k: v for k, v in ns.items() if k not in gone}, layer)


def other_words():
    """Слова spelling/ignore и формы tagged другого слоя (prohibited не в счёт: его слова LT отвергает)."""
    rows = read_tagged(OTHER).values()
    return {line for n in LISTS[:2] for line in body(read_list(n, OTHER))} | {f for _, rs in rows for f, _, _ in rs}


def move(words):
    """rpdict -t: перенести слова из другого слоя в этот: строки списков и блоки tagged целиком (по лемме или форме)."""
    lists = {n: [line for line in body(read_list(n, OTHER)) if key(line) in words] for n in LISTS}
    blocks = {lem: b for lem, b in read_tagged(OTHER).items() if lem in words or any(r[0] in words for r in b[1])}
    found = {key(line) for lines in lists.values() for line in lines} | {f for b in blocks.values() for f, _, _ in b[1]}
    # пометка «вне нормы» переезжает вместе со словом, с заменой
    ns = {k: v for k, v in read_pairs(NONSTD, OTHER).items() if k in words or k in blocks}
    for w in sorted(words - found - set(blocks) - ns.keys()):
        print(f"! нет в {OTHER.name} списке: {w}")
    # из другого слоя — тем же remove: лемма убирает весь блок, слово списка — только строку
    remove({key(line) for lines in lists.values() for line in lines} | set(blocks) | ns.keys(), OTHER)
    if ns:
        write_pairs(NONSTD, read_pairs(NONSTD) | ns)
        print(f"+ {NONSTD}: {' '.join(ns)}")
    for n, lines in lists.items():
        if not lines:
            continue
        if n == "prohibited":  # по слову, не строкой: иначе «мда» и «мда = м-да» обе остались бы в файле
            write_pairs(n, read_pairs(n) | pairs(lines))
        else:
            write_list(n, read_list(n) + lines)
        print(f"+ {n}: {' '.join(key(line) for line in lines)}")
    if blocks:
        tagged = read_tagged()
        for b in blocks.values():
            put(tagged, b)
        write_tagged(tagged)
        print(f"+ tagged: {' '.join(blocks)}")


if __name__ == "__main__":
    # самопроверка; слои, W и D — во временном каталоге: настоящие файлы не затрагиваются
    import contextlib
    import io
    import tempfile
    from unittest import mock

    assert particle_base("нет-нет-нет") == "нет" and particle_base("смейся-смейся") == "смейся"
    assert particle_base("сделал-таки") == "сделал" and not particle_base("дом-панелька")
    assert tidy(["# h", "б", "", "а ", "б", "в", "Я"], {"в"}) == ["# h", "Я", "а", "б"]
    assert yo_variants("все") == {"всё"}
    # метка ignore: блок без заголовков и смешанный блок предлагаются
    assert not ignored([]) and not ignored(["# a: x (ignore)", "# a: y"])
    assert ignored(["# a: x (ignore)"])
    one = (["# a: x"], [("a", "a", "T")])
    assert mark([one], "ignore") == [(["# a: x (ignore)"], one[1])]
    assert mark([one], "spelling") == [one] and mark([], "ignore") == []
    tmp = Path(tempfile.mkdtemp())
    own, other = Layer(tmp, "своём"), Layer(tmp / "other", "общем")
    with (
        mock.patch.multiple(sys.modules[__name__], OWN=own, OTHER=other, SHARED=own, LOCAL=other, W=tmp, D=tmp),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        # tagged.txt: пустая строка внутри блока — половины объединяются, ничего не теряется
        own.tagged.write_text("# стат: x\nстат\tстат\tT1\nстата\tстат\tT2\n\nстату\tстат\tT3\n", encoding="utf-8")
        assert read_tagged() == {
            "стат": (["# стат: x"], [("стат", "стат", "T1"), ("стата", "стат", "T2"), ("стату", "стат", "T3")])
        }
        # remove: форма убирает только свою строку, лемма — весь блок
        own.tagged.write_text(
            "# стат: x\nстат\tстат\tT1\nстата\tстат\tT2\n\n# скилл: y\nскилл\tскилл\tT1\n", encoding="utf-8"
        )
        remove({"стата"})
        assert read_tagged() == {
            "стат": (["# стат: x"], [("стат", "стат", "T1")]),
            "скилл": (["# скилл: y"], [("скилл", "скилл", "T1")]),
        }
        remove({"скилл"})
        assert set(read_tagged()) == {"стат"}
        # пустую строку между блоками забыли: удаление одной леммы сохраняет другую
        own.tagged.write_text("# стат: x\nстат\tстат\tT1\n# скилл: y\nскилл\tскилл\tT1\n", encoding="utf-8")
        remove({"стат"})
        assert read_tagged() == {"скилл": (["# скилл: y"], [("скилл", "скилл", "T1")])}, read_tagged()
        # блок причастия с леммой-инфинитивом удаляется целиком по имени в комментарии
        own.tagged.write_text("# брумящий: x\nбрумящий\tбрумить\tT1\nбрумящая\tбрумить\tT2\n", encoding="utf-8")
        remove({"брумящий"})
        assert read_tagged() == {}, read_tagged()
        # два заголовка у одной леммы переживают запись и чтение
        two = {"Брумза": (["# Брумза: a", "# Брумза: b"], [("Брумза", "Брумза", "T1")])}
        write_tagged(two)
        assert read_tagged() == two, read_tagged()
        # шапка tagged.txt: пишется по умолчанию; своя переживает запись и не прилипает к первому блоку
        assert own.tagged.read_text(encoding="utf-8").startswith(HEADS["tagged"][0] + "\n")
        blocks_text = own.tagged.read_text(encoding="utf-8").split("\n\n", 1)[1]
        own.tagged.write_text("# моя шапка\n\n" + blocks_text, encoding="utf-8")
        write_tagged(read_tagged())
        assert own.tagged.read_text(encoding="utf-8") == "# моя шапка\n\n" + blocks_text and read_tagged() == two
        # шапка списка: файл без строк # её получает, своя не заменяется
        write_list("ignore", ["кхм"])
        assert read_list("ignore") == [*HEADS["ignore"], "кхм"]
        write_list("ignore", ["# своя", "кхм"])
        assert read_list("ignore") == ["# своя", "кхм"]
        # битый tagged.txt: понятное сообщение с файлом и строкой вместо traceback
        bad = Layer(tmp / "bad", "битом")
        bad.dir.mkdir()
        bad.tagged.write_text("# брум: x\nбрум\tбрум\n", encoding="utf-8")
        try:
            read_tagged(bad)
            raise AssertionError("битый tagged.txt прочитан")
        except SystemExit as e:
            assert str(bad.tagged) in str(e) and "'брум\\tбрум'" in str(e), e
        # move: блок tagged переезжает целиком по любой форме, строка списка — сама; другой слой пустеет
        other.dir.mkdir()
        other.tagged.write_text("# Брумзик: x\nБрумзик\tБрумзик\tT1\nБрумзика\tБрумзик\tT2\n", encoding="utf-8")
        (other.dir / "spelling.txt").write_text("брумс\n", encoding="utf-8")
        assert other_words() == {"брумс", "Брумзик", "Брумзика"}, other_words()
        move({"Брумзика", "брумс"})
        assert other_words() == set() and read_tagged(other) == {}
        assert "брумс" in body(read_list("spelling")) and len(read_tagged()["Брумзик"][1]) == 2
        # nonstandard.txt: замена переживает запись и чтение, комментарий остаётся первым, лишние пробелы не мешают
        (other.dir / "nonstandard.txt").write_text("# x\nбрумщ=брум\nфлумс\n", encoding="utf-8")
        assert read_pairs(NONSTD, other) == {"брумщ": "брум", "флумс": ""}
        write_pairs(NONSTD, read_pairs(NONSTD, other), other)
        assert read_list("nonstandard", other) == ["# x", "брумщ = брум", "флумс"]
        # move переносит пометку с заменой; remove снимает её вместе со словом
        (other.dir / "spelling.txt").write_text("брумщ\nфлумс\n", encoding="utf-8")
        move({"брумщ"})
        assert read_pairs(NONSTD) == {"брумщ": "брум"} and read_pairs(NONSTD, other) == {"флумс": ""}
        assert "брумщ" in body(read_list("spelling")) and read_pairs_all(NONSTD) == {"брумщ": "брум", "флумс": ""}
        remove({"брумщ"})
        assert read_pairs(NONSTD) == {} and "брумщ" not in body(read_list("spelling"))
        # ссылка-подтверждение: последний токен http(s)://, замена может быть из двух слов
        assert split_url("на хер https://x.org/a") == ("на хер", "https://x.org/a")
        assert split_url("на хер") == ("на хер", "") and split_url("https://x.org") == ("", "https://x.org")
        # prohibited со строкой «слово = замена ссылка»: генерация и remove смотрят на слово
        write_list("prohibited", ["брумц = брум https://x.org", "брумщ"])
        assert read_pairs("prohibited") == {"брумц": "брум https://x.org", "брумщ": ""}
        remove({"брумц"})
        assert read_pairs("prohibited") == {"брумщ": ""}
        # метка * переживает запись и чтение; remove и key видят слово без неё; заглавное не вычитается из словаря
        write_pairs("prohibited", {"Брумзик*": "https://x.org", "брумщ": ""})
        assert read_pairs("prohibited") == {"Брумзик*": "https://x.org", "брумщ": ""}
        assert key("Брумзик* = https://x.org") == "Брумзик" and lower_only({"Брумзик", "брумщ", "брум щ"}) == {"брумщ"}
        remove({"Брумзик"})
        assert read_pairs("prohibited") == {"брумщ": ""}
        # move того же слова prohibited с заменой: одна строка, замена из перенесённой
        (other.dir / "prohibited.txt").write_text("брумщ = брум\n", encoding="utf-8")
        move({"брумщ"})
        assert body(read_list("prohibited")) == {"брумщ = брум"}, read_list("prohibited")
        write_list("prohibited", [])
        # generate: формы ignore-блока — в ignore.txt, не в spelling_custom.txt; смешанный блок предлагается; теги — у всех
        for n in ("ignore.orig.txt", "added.orig.txt"):
            (tmp / n).write_text("", encoding="utf-8")
        own.tagged.write_text(
            "# брумзяк: x (ignore)\nбрумзяк\tбрумзяк\tT1\nбрумзяка\tбрумзяк\tT2\n\n"
            "# флумс: x (ignore)\n# флумс: y\nфлумс\tфлумс\tT1\n\n"
            "# хрумс: x\nхрумс\tхрумс\tT1\n",
            encoding="utf-8",
        )
        generate()
        sp_out, ig_out, add_out = (
            body((tmp / n).read_text(encoding="utf-8").splitlines())
            for n in ("spelling_custom.txt", "ignore.txt", "added.txt")
        )
        assert {"брумзяк", "брумзяка"} <= ig_out and not {"брумзяк", "брумзяка"} & sp_out
        assert {"флумс", "хрумс", "брумс"} <= sp_out and "флумс" not in ig_out, sp_out
        assert {r.split("\t")[0] for r in add_out} >= {"брумзяка", "флумс", "хрумс"}
        # повторная генерация того же: ни один файл не переписан (rpdict по этому выходит с кодом 3)
        WRITES.clear()
        generate()
        assert WRITES == [], WRITES
