#!/usr/bin/env python3
"""Парадигмы словаря теггера LanguageTool: догадка, как склоняется незнакомое слово, по аналогии окончаний.

Индекс: WORKDIR/para.pkl, строится один раз из WORKDIR/tags.raw (`build.sh prep`, строки koi8-r лемма+форма+тег)
и WORKDIR/merged.txt (слова speller с обязательной ё — чтобы выбрать е или ё, где у теггера есть обе).

запуск: forms.py — только самопроверка (модуль импортирует words.py)
"""

import os
import pickle
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

type Form = tuple[str, str]  # (форма, тег)


class Para(NamedTuple):
    """Парадигма: класс (cls()), окончание леммы, (окончание формы, тег), до 200 лемм-образцов."""

    cls: str
    ending: str
    forms: tuple[Form, ...]
    samples: list[str]


W = Path(__file__).parent.parent / ".work"
MAXL = 5  # самое длинное окончание для аналогии
INDEX_FORMAT = 3  # увеличить при любом изменении того, что build() кладёт в para.pkl (3: мн. ч. общего рода, common())
PROPER = ("NN:Name", "NN:Fam", "NN:Patr")


def prefix(strs):
    """Самый длинный общий префикс (os.path.commonprefix устарел)."""
    a, b = min(strs), max(strs)
    k = 0
    while k < len(a) and a[k] == b[k]:
        k += 1
    return a[:k]


# новые слова бывают только этих классов, но не предлогами и не междометиями
OPEN = (
    "NN",
    "ADJ",
    "V",
    "ADV",
)
# продуктивные приставки новых слов (полугорящая, неубиваемый): известное слово после них склоняется как само
NOT_VERB = ("не", "без", "бес")  # неубиваемым — это неубиваемый, глагола неубивать нет
PREFIXES = (
    "полу",
    "недо",
    "пере",
    "сверх",
    "псевдо",
    "квази",
    "анти",
    "супер",
    "ультра",
    "около",
    "само",
    "не",
    "без",
    "бес",
)


def cls(tag):
    p = tag.split(":")
    if p[0] in ("VB", "PT", "PT_Short", "DPT"):
        return "V"  # причастия и деепричастия входят в парадигму глагола
    if p[0] == "NN":
        return ":".join(p[:3])  # NN:Anim:Masc, NN:Name:Fem, NN:Inanim: (только мн. ч.)
    return p[0]


def _groups():
    """(лемма, {класс: [(форма, тег)]}) для каждой леммы: дамп отсортирован по форме, поэтому сначала сортируем по лемме."""
    env = dict(os.environ, LC_ALL="C")
    p = subprocess.Popen(
        ["sort", "-t+", "-k1,1", "-S", "512M", str(W / "tags.raw")],
        stdout=subprocess.PIPE,
        env=env,
    )
    assert p.stdout is not None  # stdout=PIPE
    cur, g = None, defaultdict(list)
    for raw in p.stdout:
        lemma, form, tag = raw.decode("koi8-r").rstrip("\n").split("+")
        if lemma != cur:
            if cur is not None:
                yield cur, g
            cur, g = lemma, defaultdict(list)
        g[cls(tag)].append((form, tag))
    if cur is not None:
        yield cur, g
    if rc := p.wait():
        sys.exit(f"sort {W / 'tags.raw'}: код выхода {rc}")


def common(g):
    """Слово общего рода (сирота): у LT ед. ч. дважды, м.р. и ж.р., а мн. ч. — NN:Fam:PL, как у фамилий.
    Отдаём мн. ч. обоим родам, иначе образец «сирота» даёт слово без мн. ч.; у фамилий (есть NN:Fam:Masc) не трогаем."""
    pl = g.get("NN:Fam:PL")
    for a in ("Anim", "Inanim"):
        m, f = f"NN:{a}:Masc", f"NN:{a}:Fem"
        if pl and m in g and f in g and not {"NN:Fam:Masc", "NN:Fam:Fem"} & g.keys():
            for c in (m, f):
                g[c] = g[c] + [(x, c + t[len("NN:Fam") :]) for x, t in pl]
            del g["NN:Fam:PL"]
            break
    return g


def build():
    pids, paras, lemma_pids = {}, [], defaultdict(set)
    idx = defaultdict(Counter)  # окончание -> (pid, хвост формы) -> число словоформ
    for lemma, g in _groups():
        for c, fl in common(g).items():
            stem = prefix([lemma] + [x for x, _ in fl])
            key = (
                c,
                lemma[len(stem) :],
                tuple(sorted({(x[len(stem) :], t) for x, t in fl})),
            )
            pid = pids.setdefault(key, len(paras))
            if pid == len(paras):
                paras.append(Para(*key, []))
            if len(paras[pid].samples) < 200:
                paras[pid].samples.append(lemma)
            lemma_pids[lemma].add(pid)
            for x in {x for x, _ in fl}:
                for L in range(1, min(MAXL, len(x) - 1) + 1):
                    idx[x[-L:]][(pid, x[len(stem) :])] += 1
    paras = _pick_yo(paras)
    # после выбора е/ё парадигмы могут совпасть: объединяем
    new, remap, out = {}, {}, []
    for pid, p in enumerate(paras):
        k = p.cls, p.ending, p.forms
        if k not in new:
            new[k] = len(out)
            out.append(Para(p.cls, p.ending, p.forms, []))
        remap[pid] = new[k]
        out[new[k]].samples.extend(p.samples[: 200 - len(out[new[k]].samples)])
    keep = [{fs for fs, _ in p.forms} for p in out]
    ix = {}
    for e, cnt in idx.items():
        m = Counter()
        for (pid, fs), n in cnt.items():
            if fs in keep[remap[pid]]:
                m[(remap[pid], fs)] += n
        ix[e] = tuple((p, fs, n) for (p, fs), n in m.items())
    lp = {lem: tuple({remap[p] for p in s}) for lem, s in lemma_pids.items()}
    return out, lp, ix


def _pick_yo(paras):
    """В теггере ё необязательна (доделенный и доделённый): оставляем написание, которое есть в speller с обязательной ё."""
    pairs, need = {}, set()
    for pid, (c, ls, fl, samples) in enumerate(paras):
        fss = {fs for fs, _ in fl}
        for fs in fss:
            if "ё" in fs and fs.replace("ё", "е") in fss:
                stems = [w[: len(w) - len(ls)] for w in samples[:20]]
                pairs[(pid, fs)] = stems
                need.update(s + v for s in stems for v in (fs, fs.replace("ё", "е")))
    have = set()
    with open(W / "merged.txt", encoding="utf-8") as f:  # потоком: ~4,5 млн строк
        have = {line.rstrip("\n") for line in f if line.rstrip("\n") in need}
    drop = defaultdict(set)
    for (pid, fs), stems in pairs.items():
        e = fs.replace("ё", "е")
        yo, ee = sum(s + fs in have for s in stems), sum(s + e in have for s in stems)
        # shortcut: при равенстве остаются оба написания; это редкость, таблица форм их покажет
        if yo != ee:
            bad, good = (e, fs) if yo > ee else (fs, e)
            # у speller есть и другое написание (сестры: Р. ед.): не помечаем только теги, общие с правильным
            # (сестры как вариант сёстры), иначе всю форму (темно-зеленой)
            tags = (
                {t for x, t in paras[pid].forms if x == good}
                if min(yo, ee)
                else {t for x, t in paras[pid].forms if x == bad}
            )
            drop[pid] |= {(bad, t) for t in tags}
    return [p._replace(forms=tuple(x for x in p.forms if x not in drop[pid])) for pid, p in enumerate(paras)]


class Index:
    def __init__(self):
        pkl = W / "para.pkl"
        data = None
        if pkl.exists():  # rpdict -b удаляет его вместе с дампами
            with open(pkl, "rb") as f:
                data = pickle.load(f)
        # индекс от старой версии кода (другой INDEX_FORMAT или без него) строится заново: git pull не удаляет .work
        # shortcut: за merged.txt (выбор е/ё в build()) не следит, после крупного обновления словаря — rpdict -b
        if not (isinstance(data, dict) and data.get("format") == INDEX_FORMAT):
            print("строю индекс парадигм (один раз, ~2 мин)...", flush=True)
            data = {"format": INDEX_FORMAT, "index": build()}
            # оборванный файл (Ctrl+C) сломал бы все следующие запуски
            tmp = pkl.with_name("para.pkl.tmp")
            with open(tmp, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(pkl)
        self.paras, self.lemma_pids, self.idx = data["index"]

    def analyses(self, w):
        """(L, лемма, pid, fs, n) для каждого способа считать w формой известной парадигмы, начиная с самого длинного окончания."""
        for L in range(min(MAXL, len(w) - 1), 0, -1):
            for pid, fs, n in self.idx.get(w[-L:], ()):
                if w.endswith(fs) and len(w) > len(fs):
                    yield L, w[: len(w) - len(fs)] + self.paras[pid].ending, pid, fs, n

    def known(self, word, proper=None):
        """Слово уже есть в теггере: для слова с заглавной считаются только имена (Роза — не роза),
        для строчного — только нарицательные (статов — не Статов)."""
        proper = word[:1].isupper() if proper is None else proper
        return any(
            pid in self.lemma_pids.get(lem, ()) and self.paras[pid].cls.startswith(PROPER) == proper
            for _, lem, pid, _, _ in self.analyses(word.lower())
        )

    def lemma_tags(self, lemma, c):
        return {t for p in self.lemma_pids.get(lemma, ()) if self.paras[p].cls == c for _, t in self.forms(lemma, p)}

    def lemma_known(self, lemma, c):
        """У теггера есть эта лемма в этом классе (тогда слово — недостающая форма известного слова)."""
        return any(self.paras[p].cls == c for p in self.lemma_pids.get(lemma, ()))

    def guess(self, word, top=3):
        """Самые вероятные (лемма, pid, вес) для незнакомого слова; фамилии никогда, имена только для слова с заглавной."""
        w, cap = word.lower(), word[:1].isupper()
        head, _, tail = w.rpartition("-")
        if head:
            # день-другой, дом-панелька: склоняются обе части (дня-другого, дома-панельки) ...
            both = [(lem, pid, 1000) for lem, pid in self.agree(head, tail)]
            # ... или чёрно-золотое, интернет-магазин: только известная последняя часть, как её слово, а не по одному окончанию
            # не собственное и не глагол (смейся-смеяться); ...-нет: не частица и не предикатив
            res = Counter(
                (f"{head}-{lem}", pid)
                for _, lem, pid, _, _ in self.analyses(tail)
                if pid in self.lemma_pids.get(lem, ())
                and not self.paras[pid].cls.startswith(PROPER + ("V",))
                and self.paras[pid].cls.startswith(OPEN)
            )
            if both or res:
                return (both + [(lem, pid, n) for (lem, pid), n in res.most_common()])[:top]
        levels = defaultdict(Counter)
        for L, lem, pid, fs, n in self.analyses(w):
            c = self.paras[pid].cls
            # глагол через дефис — повтор или ошибка, а не парадигма (смейся-смейся)
            if (
                c.startswith(("NN:Fam", "NN:Patr"))
                or c.startswith(PROPER)
                and not cap
                or not c.startswith(OPEN)
                or head
                and c == "V"
            ):
                continue
            levels[L][(lem, pid)] += n
        # решает самое длинное окончание, если только оно не у одного-двух слов (голема: -олема только у глаголать,
        # -лема — голем, проблема...): тогда первым идёт следующее покороче, а редкое совпадение — после него
        # shortcut: порог 3 подобран на нескольких десятках слов пользователя; поправить, если хорошие догадки уходят вниз
        res, weak = [], []
        for L in sorted(levels, reverse=True):
            if sum(levels[L].values()) >= 3:
                res = levels[L].most_common()
                break
            weak += levels[L].most_common()
        # полугорящая: приставка перед целым известным словом (горящая) склоняется как это слово (гореть), а не по
        # более частому окончанию (спорящая); идёт первой, догадки по окончанию — после
        pre = Counter()
        for p in PREFIXES:
            if w.startswith(p) and len(w) - len(p) >= 4:
                pre.update(
                    (p + lem, pid)
                    for _, lem, pid, _, _ in self.analyses(w[len(p) :])
                    if pid in self.lemma_pids.get(lem, ())
                    and self.paras[pid].cls.startswith(OPEN)
                    and not self.paras[pid].cls.startswith(PROPER + (("V",) if p in NOT_VERB else ()))
                )
        seen, out = set(), []
        # вес целого известного слова должен победить и в группировке migrate, которая суммирует веса по формам
        for k, n in [(k, n * 1000) for k, n in pre.most_common()] + res + weak:
            if k not in seen:
                seen.add(k)
                out.append((*k, n))
        return out[:top]

    def like(self, word, model, own=()):
        """[(лемма, pid)] слова, склоняемого как известное слово-образец в любой форме (перепих как смех, неубиваемым
        как несносный). Берётся форма образца с самым длинным общим окончанием (брумзалом как окно → окном), и её
        форма переносится по изменению за общим окончанием; формы, которые меняются раньше (несносен: беглая
        гласная), перенести нельзя, они пропускаются. Результат — новая парадигма.
        own: [(лемма, [(форма, тег)])] своих слов (tagged.txt): образцом может быть и слово, которого нет в теггере
        (наебать как заебать)."""
        w, m = word.lower(), model.lower()

        def make(lem, pid, mm):
            k = len(prefix([w[::-1], mm[::-1]]))  # общее окончание: -ым
            if not k:
                return None  # Брумп как Джейк: общей буквы нет, окончания следовали бы самому образцу (Джейки, а не Брумпы)

            def carry(f):
                p = len(prefix([f, mm]))
                return w[: len(w) - (len(mm) - p)] + f[p:] if p >= len(mm) - k else None

            nl = carry(lem)
            new = [(g, t) for f, t in self.forms(lem, pid) if (g := carry(f))]
            if not nl or not new:
                return None
            return self._new_para(self.paras[pid].cls, nl, new, lem, sort=False)

        found = [(lem, pid) for _, lem, pid, _, _ in self.analyses(m) if pid in self.lemma_pids.get(lem, ())]
        for lem, fl in own:
            fl = [(f.lower(), t) for f, t in fl]
            if m not in {f for f, _ in fl}:
                continue
            lem = lem.lower()
            # парадигма по классу, как в build(): у глагола и прилагательного от него — разные
            for c in dict.fromkeys(cls(t) for _, t in fl):
                found.append(self._new_para(c, lem, [(f, t) for f, t in fl if cls(t) == c], lem))
        # Филипп: сначала имя, потом остальное (Мадрид, топоним, в теггере нарицательное)
        if model[:1].isupper():
            found.sort(key=lambda x: not self.paras[x[1]].cls.startswith(PROPER))
        # устойчиво: сначала образец как собственная лемма (Рахиль, а не Р. мн. от Рахиля)
        found.sort(key=lambda x: x[0] != m)
        found = list(dict.fromkeys(found))
        # образец в любой форме: берётся его форма с самым длинным общим окончанием со словом, при равной длине — сам
        # вписанный образец (неубиваемой как несносный → несносной, а не по одной общей -й: неубиваемоми)
        near = lambda lem, pid: max(
            (f for f, _ in self.forms(lem, pid)),
            key=lambda f: (len(prefix([w[::-1], f[::-1]])), f == m),
        )
        return [r for lem, pid in found if (r := make(lem, pid, near(lem, pid)))]

    def models(self, word, top=6):
        """[(лемма, pid, слово-образец)] для выбора по «к»: по парадигме на самое длинное общее окончание, для слова
        с заглавной сначала имена (Брумп: имя на -п раньше агитпроп), слово как своя лемма первым; без фильтров guess."""
        w, cap = word.lower(), word[:1].isupper()
        seen, out = set(), []
        for L, lem, pid, _, _ in self.analyses(w):
            c = self.paras[pid].cls
            if (
                not c.startswith(OPEN)
                or c.startswith(("NN:Fam", "NN:Patr"))
                or c.startswith(PROPER)
                and not cap
                or (c, lem) in seen
            ):
                continue
            seen.add((c, lem))
            out.append((cap and not c.startswith(PROPER), lem != w, -L, lem, pid))
        # устойчиво: при равной длине окончания — порядок разборов (частые первыми)
        out.sort(key=lambda x: x[:3])
        return [(lem, pid, self.sample(lem, pid)) for *_, lem, pid in out[:top]]

    def _new_para(self, c, lem, new, sample, sort=True):
        """Новая парадигма слова lem из форм new [(форма, тег)] -> (лемма, pid). sample — как она показывается:
        образец (заебать) или «дом» + «панелька». sort=False сохраняет порядок форм: первая на тег — основной вариант."""
        stem = prefix([lem] + [f for f, _ in new])
        fl = [(f[len(stem) :], t) for f, t in new]
        self.paras.append(Para(c, lem[len(stem) :], tuple(sorted(set(fl)) if sort else fl), [sample]))
        return lem, len(self.paras) - 1

    def _real(self, w, c):
        """[(лемма, pid)] разборов w с классом на c, у которых w и правда одна из форм."""
        return [
            (lem, p)
            for _, lem, p, _, _ in self.analyses(w)
            if p in self.lemma_pids.get(lem, ())
            and self.paras[p].cls.startswith(c)
            and w in {f for f, _ in self.forms(lem, p)}
        ]

    def agree(self, noun, tail):
        """[(лемма, pid)] двух слов, склоняемых вместе (день-другой, минута-другая, дом-панелька, месяц-два, три-четыре,
        один-единственный): новые парадигмы. Род и одушевлённость берутся от первого слова."""
        nn = ("NN:Anim", "NN:Inanim")
        kinds = [
            (nn, ("ADJ",) + nn, self._noun_adj),
            (nn, ("Num",), self._noun_num),
            (("Num",), ("Num",), self._num_num),
            (("ADJ",), ("ADJ",), self._adj_adj),
        ]
        out = []
        for head, second, make in kinds:
            for (hl, hp), (tl, tp) in dict.fromkeys(
                (h, t) for h in self._real(noun, head) for t in self._real(tail, second)
            ):
                if r := make(noun, hl, hp, tl, tp):
                    out.append(r)
        return out

    def _noun_adj(self, noun, nl, np_, tl, tp):
        """день-другой, минута-другая, дом-панелька: существительное с прилагательным или существительным."""
        adj = self.paras[tp].cls == "ADJ"
        tf = {}
        for f, t in self.forms(tl, tp):
            if t.startswith(("ADJ:Posit:", "ADJ:MPR:", "NN:")):
                # первый вариант: минутой-другой, а не -другою; прилагательное — по роду, существительное — по числу
                tf.setdefault(tuple(t.split(":")[-2:] if adj else t.split(":")[3:5]), f)
        # одна форма на тег: дома-панельки, а не дому-
        nf = list({t: (f, t) for f, t in reversed(self.forms(nl, np_))}.values())[::-1]
        nom = {t.split(":")[3]: f for f, t in nf if t.endswith(":Nom")}
        new = []
        for f, t in nf:
            g, num, case = t.split(":")[2:5]
            key = (g if num == "Sin" else "PL") if adj else num
            # вижу день-другой / кота-другого (минуту-другую не трогаем)
            if adj and case == "V" and key in ("Masc", "PL"):
                case = "Nom" if f == nom.get(num) else "R"
            if (key, case) in tf:
                new.append((f"{f}-{tf[key, case]}", t))
        if not new:
            return None
        g = self.paras[np_].cls.split(":")[2]
        lem = f"{nl}-{tf.get((g, 'Nom') if adj else ('Sin', 'Nom'), tl)}"  # минута-другая
        return self._new_para(self.paras[np_].cls, lem, new, f"{nl}» + «{tl}", sort=False)

    def _noun_num(self, noun, nl, np_, tl, tp):
        """месяц-два, неделю-две: существительное в ед. ч. и числительное по падежу и роду (месяца-двух, неделей-двумя)."""
        tf = {}
        for f, t in self.forms(tl, tp):
            tf.setdefault(tuple(t.split(":")[1:]), f)

        def pick(g, case):
            return tf.get((g, case)) or tf.get((case,))

        nf = list({t: (f, t) for f, t in reversed(self.forms(nl, np_)) if ":Sin:" in t}.values())
        gen = next((f for f, t in nf if t.endswith(":R")), None)
        new = []
        for f, t in nf:
            g, _, case = t.split(":")[2:5]
            if w := pick(g, ("R" if f == gen else "Nom") if case == "V" else case):
                new.append((f"{f}-{w}", t))
        if not new or noun not in {f for f, _ in nf}:
            return None
        lem = f"{nl}-{pick(self.paras[np_].cls.split(':')[2], 'Nom') or tl}"
        return self._new_para(self.paras[np_].cls, lem, new, f"{nl}» + «{tl}")

    def _num_num(self, noun, hl, hp, tl, tp):
        """три-четыре: два числительных по падежу (трёх-четырёх, тремя-четырьмя) и по роду, где он есть у обоих (одна-две)."""
        tf = {}
        for f, t in self.forms(tl, tp):
            # ("Fem", "Nom") для два, ("Nom",) для четыре
            tf.setdefault(tuple(t.split(":")[1:]), f)

        def pick(g, case):
            return tf.get((g, case)) or tf.get((case,)) or tf.get(("Masc", case))

        hf = [(f, t) for f, t in self.forms(hl, hp) if t.count(":") and pick(*([None] + t.split(":")[1:])[-2:])]
        # один / одна: по роду
        noms = {t.rpartition(":")[0]: f for f, t in hf if t.endswith(":Nom")}
        gens = {t.rpartition(":")[0]: f for f, t in hf if t.endswith(":R")}
        nom = noms.get("Num:Masc", next(iter(noms.values()), hl))
        new = []
        for f, t in hf:
            g, case = ([None] + t.split(":")[1:])[-2:]
            # вижу три-четыре дома / трёх-четырёх котов / одну-две книги: как Р. или нет
            if case == "V":
                case = "R" if f == gens.get(t.rpartition(":")[0]) else "Nom"
            new.append((f"{f}-{pick(g, case)}", t))
        if not new or noun not in {f for f, _ in hf}:
            return None
        return self._new_para(self.paras[hp].cls, f"{nom}-{tf.get('Nom', tl)}", new, f"{hl}» + «{tl}")

    def _adj_adj(self, noun, hl, hp, tl, tp):
        """один-единственный: два прилагательных, только полные формы (одного-единственного); тег — от второй части."""
        full = ("ADJ:Posit:", "ADJ:MPR:")
        tf = {}
        for f, t in self.forms(tl, tp):
            if t.startswith(full):
                tf.setdefault(tuple(t.split(":")[-2:]), (f, t))
        hf = [(f, t) for f, t in self.forms(hl, hp) if t.startswith(full)]
        if noun not in {f for f, _ in hf}:
            return None  # тёмно-синий: тёмно — краткая форма, первая часть не склоняется
        nom = {t.split(":")[-2]: f for f, t in hf if t.endswith(":Nom")}
        new = []
        for f, t in hf:
            g, case = t.split(":")[-2:]
            # вижу один-единственный дом / одного-единственного кота
            if case == "V" and g in ("Masc", "PL"):
                case = "Nom" if f == nom.get(g) else "R"
            if (g, case) in tf:
                tw, tt = tf[g, case]
                new.append((f"{f}-{tw}", tt[: -len(case)] + t.split(":")[-1]))
        if not new:
            return None
        lem = f"{nom.get('Masc', hl)}-{tf.get(('Masc', 'Nom'), (tl,))[0]}"
        return self._new_para("ADJ", lem, new, f"{hl}» + «{tl}")

    def forms(self, lemma: str, pid: int) -> list[Form]:
        p = self.paras[pid]
        stem = lemma[: len(lemma) - len(p.ending)]
        return [(stem + fs, t) for fs, t in p.forms]

    def sample(self, lemma, pid):
        """Слово-образец, ближайшее к лемме: самое длинное общее окончание, затем самое короткое слово."""

        def tail(s):
            n = 0
            while n < min(len(s), len(lemma)) and s[-1 - n] == lemma[-1 - n]:
                n += 1
            return n

        return min(self.paras[pid].samples, key=lambda s: (-tail(s), len(s)))


# --- вывод ---------------------------------------------------------------------------------------------

# (тег, падеж, вопрос одушевлённого, неодушевлённого, прилагательного)
CASES = [
    ("Nom", "И.", "кто?", "что?", "какой?"),
    ("R", "Р.", "кого?", "чего?", "какого?"),
    ("D", "Д.", "кому?", "чему?", "какому?"),
    ("V", "В.", "кого?", "что?", "какой?"),
    ("T", "Т.", "кем?", "чем?", "каким?"),
    ("P", "П.", "о ком?", "о чём?", "о каком?"),
]


def question(c, case):
    """Один вопрос падежа: у существительного он следует одушевлённости (Магнусона — кого?, стата — чего?)."""
    q = next(x for x in CASES if x[0] == case)
    return q[4] if c == "ADJ" else q[3] if c.split(":")[1:2] == ["Inanim"] else q[2]


ANIM = {"Anim": "одуш.", "Inanim": "неодуш.", "Name": "имя", "Fam": "фам."}
# Com — общий род только в диалоге (сирота, визави): при записи dialog.both() даёт формы и м.р., и ж.р., как у LT
GEN = {"Masc": "м.р.", "Fem": "ж.р.", "Neut": "ср.р.", "Com": "общ. р. (м. и ж.)", "": "только мн.ч."}


def label(c: str, fl: list[Form]) -> str:
    p = c.split(":")
    if p[0] == "NN":
        return f"сущ. {ANIM.get(p[1], p[1])} {GEN.get(p[2], p[2])}"
    if c == "V":
        t = next((t for _, t in fl if t.startswith("VB:INF")), fl[0][1]).split(":")
        asp = next((ASPECTS[x] for x in t if x in ASPECTS), "")
        # у дрочить в тегах LT нет ни вида, ни переходности: «неперех.» по умолчанию было бы выдумкой
        tr = "перех." if "TRANS" in t else "неперех." if "INTR" in t else "безл." if "bezl" in t else ""
        return "глаг. " + (" ".join(x for x in (asp, tr) if x) or "(вид и переходность не указаны)")
    return {
        "ADJ": "прил.",
        "PT": "прич.",
        "ADV": "нареч.",
        "Num": "числ.",
        "NumC": "числ.",
    }.get(c, c)


_POS = {
    "NN": "существительное",
    "ADJ": "прилагательное",
    "PNN": "местоимение",
    "ADV": "наречие",
    "PT": "причастие",
    "DPT": "деепричастие",
    "VB": "глагол",
}
_WORDS = {
    "INF": "неопределённая форма",
    "IMP": "повелительное наклонение",
    "Fut": "будущее время",
    "Real": "настоящее время",
    "Past": "прошедшее время",
    "Short": "краткая форма",
    "Comp": "сравнительная степень",
    "DST": "действительное",
    "STR": "страдательное",
    "Masc": "мужской род",
    "Fem": "женский род",
    "Neut": "средний род",
    "PL": "множественное число",
    "Sin": "единственное число",
    "2P": "предложный падеж (в лесу)",
    **{
        k: lab + " падеж"
        for k, lab in (
            ("Nom", "именительный"),
            ("R", "родительный"),
            ("D", "дательный"),
            ("V", "винительный"),
            ("T", "творительный"),
            ("P", "предложный"),
        )
    },
}
_WHO = {
    "Sin:P1": "я",
    "Sin:P2": "ты",
    "Sin:P3": "он/она",
    "PL:P1": "мы",
    "PL:P2": "вы",
    "PL:P3": "они",
}


def describe(t):
    """Тег простыми словами для пользователя (DPT:Real:TRANS:IMPFV -> деепричастие, настоящее время)."""
    p = t.split(":")
    who = next((w for k, w in _WHO.items() if k in t), None)
    if who:  # наст. время, «они»: число уже в лице
        p = [x for x in p if x not in ("Sin", "PL")]
    out = [_POS.get(p[0]) or p[0]] + [_WORDS[x] for x in p[1:] if x in _WORDS]
    return ", ".join(out + ([f"«{who}»"] if who else []))


def cells(c):
    """(заголовок, проверка тега) форм, показываемых для класса; остальное следует образцу."""
    if c.startswith("NN"):
        return [
            (f"{n} {lab}", lambda t, n=n, k=k: t.endswith(f":{n}:{k}")) for n in ("Sin", "PL") for k, lab, *_ in CASES
        ]
    # один тег на ячейку: вариант, введённый в ячейку, не должен попасть в другие (неубиваем)
    if c == "ADJ":
        return [(title, lambda t, tag=tag: t == tag) for title, tag in ACELLS]
    # порядок таблицы спряжения Викисловаря, чтобы сверять построчно; PT — причастие без глагола
    if c in ("V", "PT"):
        return [
            (
                title,
                lambda t, h=h, e=e: t.startswith(("VB:Fut:", "VB:Real:") if h == "VB:F" else h) and t.endswith(e),
            )
            for title, h, e in VCELLS
            if c == "V" or h.startswith("PT")
        ]
    return [("", lambda t: True)]


ASPECTS = {"PFV": "сов.", "IMPFV": "несов.", "2PFV": "двувид."}
_PERS = [
    ("Sin:P1", "я"),
    ("Sin:P2", "ты"),
    ("Sin:P3", "он"),
    ("PL:P1", "мы"),
    ("PL:P2", "вы"),
    ("PL:P3", "они"),
]
_TENSE = (("Real", "наст."), ("Past", "прош."))
# (заголовок, начало тега, конец тега) ячейки глагола; "VB:F" — это VB:Fut (сов. вид) или VB:Real (несов. вид)
VCELLS = (
    [("инф.|", "VB:INF", "")]
    + [(f"наст./буд.|{who}", "VB:F", e) for e, who in _PERS]
    + [
        (f"прош.|{g}", "VB:Past", e)
        for e, g in (
            ("Masc", "м.р."),
            ("Fem", "ж.р."),
            ("Neut", "ср.р."),
            ("PL", "мн."),
        )
    ]
    + [(f"повел.|{who}", "VB:IMP", e) for e, who in (("PL:P1", "мы"), ("Sin:P2", "ты"), ("PL:P2", "вы"))]
    + [
        (f"прич.|{v} {tn}", f"PT:{k}:", f":{s}:Masc:Nom")
        for s, v in (("DST", "действ."), ("STR", "страд."))
        for k, tn in _TENSE
    ]
    + [(f"деепр.|{tn}", f"DPT:{k}", "") for k, tn in _TENSE]
)


# (тег, род, вопрос полной формы, краткой) в порядке таблицы Викисловаря
_GENS = (
    ("Masc", "м.р.", "какой?", "каков?"),
    ("Neut", "ср.р.", "какое?", "каково?"),
    ("Fem", "ж.р.", "какая?", "какова?"),
    ("PL", "мн.", "какие?", "каковы?"),
)
ACELLS = (
    [(f"И. {q}|{g}", f"ADJ:Posit:{e}:Nom") for e, g, q, _ in _GENS]
    + [("Р. какого?|м.р.", "ADJ:Posit:Masc:R")]
    + [(f"кратк. {q}|{g}", f"ADJ:Short:{e}") for e, g, _, q in _GENS]
    + [("сравн.|", "ADJ:Comp")]
)


def blank(c, title, mid):
    """Тег ячейки, которую образец оставил пустой (кратк. м.р. неубиваем, прич. действ. наст.), или None, если заполнить нельзя."""
    if c == "ADJ":
        return dict(ACELLS)[title]
    if c.startswith("NN"):  # "PL Р." -> NN:Inanim:Neut:PL:R
        num, _, lab = title.partition(" ")
        return f"{c}:{num}:{next(k for k, x, *_ in CASES if x == lab)}"
    return vtag(title, mid) if c == "V" else None


def vtag(title, mid):
    """Тег ячейки глагола, которую образец оставил пустой; mid — середина тега INF (INTR:IMPFV). Причастие
    получает тег Masc:Nom: вызывающий код склоняет его по другому причастию."""
    _, h, e = next(x for x in VCELLS if x[0] == title)
    if h == "VB:F":
        h = "VB:Real" if mid.endswith(":IMPFV") else "VB:Fut"
    if h.startswith("PT"):
        return f"{h}{mid}{e}"
    return ":".join(x for x in (h, mid, e) if x)


def grid(cols, rows):
    """Строки таблицы с выровненными столбцами, rows = [(подпись, [ячейки])]; заголовок начинается с пробелов."""
    lines = [("", cols)] + rows
    w = [max(len(([r[0]] + r[1])[i]) for r in lines) for i in range(len(cols) + 1)]
    return ["  ".join(x.ljust(n) for x, n in zip([r[0]] + r[1], w)).rstrip() for r in lines]


def table(c: str, fl: list[Form], full=False) -> list[str]:
    """Формы для показа, по строке на ряд; разные формы одной ячейки через '/'.
    Существительное — таблицей падежей с вопросом; прилагательное — кратко, а с full всеми падежами (после правки)."""
    order = [f for f, _ in fl]

    def cell(test):
        return "/".join(sorted({f for f, t in fl if test(f, t)}, key=order.index))

    if c.startswith("NN"):
        nums = [(n, lab) for n, lab in (("Sin", "ед."), ("PL", "мн.")) if any(f":{n}:" in t for _, t in fl)]
        rows = [
            (
                f"{lab} {question(c, k)}",
                [cell(lambda f, t, n=n, k=k: t.endswith(f":{n}:{k}")) or "—" for n, _ in nums],
            )
            for k, lab, *_ in CASES
        ]
        if all(x == "—" for _, xs in rows for x in xs):
            return []  # записи без падежей (несклоняемые имена)
        return grid([lab for _, lab in nums], rows)
    if c == "ADJ":
        gens = [e for e, *_ in _GENS]
        tag = lambda s: lambda f, t: t == s
        short = [cell(tag(f"ADJ:Short:{e}")) or "—" for e in gens]
        comp = cell(lambda f, t: t.startswith("ADJ:Comp"))
        # склонение прилагательного видно по И.: падежи нужны только при правке
        if not full:
            rows = [
                (
                    "какой?",
                    " · ".join(cell(tag(f"ADJ:Posit:{e}:Nom")) or "—" for e in gens),
                ),
                ("кратк.", " · ".join(short) if set(short) != {"—"} else ""),
                ("сравн.", comp),
            ]
            return [f"{lab:8}{v}" for lab, v in rows if v]
        posit = lambda e, k: {f for f, t in fl if t == f"ADJ:Posit:{e}:{k}"}
        rows = []
        for k, lab, *_ in CASES:
            if k != "V":
                rows.append(
                    (
                        f"{lab} {question(c, k)}",
                        [cell(tag(f"ADJ:Posit:{e}:{k}")) for e in gens],
                    )
                )
                continue
            # В. м.р. и мн. как Р. у одушевлённого (вижу классного кота) и как И. у неодушевлённого (классный дом)
            for sub, o in (("одуш. какого?", "R"), ("неод. какой?", "Nom")):
                rows.append(
                    (
                        f"В. {sub}",
                        [
                            cell(
                                lambda f, t, e=e, o=o: (
                                    t == f"ADJ:Posit:{e}:V" and (f in posit(e, o) if e in ("Masc", "PL") else o == "R")
                                )
                            )
                            for e in gens
                        ],
                    )
                )
        if set(short) != {"—"}:
            rows.append(("кратк.", short))
        if comp:
            rows.append(("сравн.", [comp, "", "", ""]))
        return grid(["м.р.", "ср.р.", "ж.р.", "мн."], rows)
    out = []
    for title, test in cells(c):
        fs = cell(lambda f, t, test=test: test(t))
        if fs:
            out.append((title, fs))
    if c in ("V", "PT"):  # по строке на группу: инф., наст./буд., прош., прич., деепр.
        groups = {}
        for t, v in out:
            g, _, lab = t.partition("|")
            groups.setdefault(g, []).append(f"{v} ({lab})" if g == "прич." else v)
        return [f"{g}: {' · '.join(vs)}" for g, vs in groups.items()]
    return [" · ".join(v for _, v in out)]


def indeclinable(word: str, gender: str, anim: str) -> tuple[str, list[Form]]:
    """Все падежи одной формой: слово с заглавной (Брум, Токио) только в ед. ч., иначе в обоих числах."""
    a = anim
    nums = ("Sin",) if word[:1].isupper() else ("Sin", "PL")
    return "NN:" + a + ":" + gender, [(word, f"NN:{a}:{gender}:{n}:{k}") for n in nums for k, *_ in CASES]


if __name__ == "__main__":
    # самопроверка (индекс не нужен)
    assert prefix(["заигнорить", "заигнорю", "заигнорил"]) == "заигнор" and prefix(["а", "б"]) == ""
    assert cls("PT:Past:TRANS:PFV:STR:Fem:Nom") == "V" and cls("NN:Inanim::PL:R") == "NN:Inanim:"
    c, fl = indeclinable("Брум", "Fem", "Name")
    assert indeclinable("Токио", "Masc", "Inanim")[1][5] == (
        "Токио",
        "NN:Inanim:Masc:Sin:P",
    )
    assert c == "NN:Name:Fem" and len(fl) == 6 and fl[1] == ("Брум", "NN:Name:Fem:Sin:R")
    assert label(c, fl) == "сущ. имя ж.р." and table(c, fl) == [
        "           ед.",
        "И. кто?    Брум",
        "Р. кого?   Брум",
        "Д. кому?   Брум",
        "В. кого?   Брум",
        "Т. кем?    Брум",
        "П. о ком?  Брум",
    ], table(c, fl)
    assert question("NN:Inanim:Masc", "P") == "о чём?" and question("ADJ", "T") == "каким?"
    # общий род: мн. ч. NN:Fam:PL уходит к обоим родам; у фамилии остаётся
    g = common(
        {
            "NN:Anim:Masc": [("сирота", "NN:Anim:Masc:Sin:Nom")],
            "NN:Anim:Fem": [],
            "NN:Fam:PL": [("сирот", "NN:Fam:PL:R")],
        }
    )
    assert g == {
        "NN:Anim:Masc": [("сирота", "NN:Anim:Masc:Sin:Nom"), ("сирот", "NN:Anim:Masc:PL:R")],
        "NN:Anim:Fem": [("сирот", "NN:Anim:Fem:PL:R")],
    }, g
    fam = {"NN:Anim:Masc": [], "NN:Anim:Fem": [], "NN:Fam:Masc": [], "NN:Fam:PL": [("x", "NN:Fam:PL:R")]}
    assert common(dict(fam)) == fam
    # agree без индекса: существительное с прилагательным (брумза-другая), первый вариант формы — основной
    ix = Index.__new__(Index)
    ix.paras = [
        Para("NN:Inanim:Fem", "а", (("а", "NN:Inanim:Fem:Sin:Nom"), ("ой", "NN:Inanim:Fem:Sin:T")), ["брумза"]),
        Para(
            "ADJ",
            "ой",
            (
                ("ой", "ADJ:Posit:Masc:Nom"),
                ("ая", "ADJ:Posit:Fem:Nom"),
                ("ой", "ADJ:Posit:Fem:T"),
                ("ою", "ADJ:Posit:Fem:T"),
            ),
            ["другой"],
        ),
    ]
    res = ix._noun_adj("брумза", "брумза", 0, "другой", 1)
    assert res
    lem, pid = res
    assert lem == "брумза-другая" and ix.forms(lem, pid) == [
        ("брумза-другая", "NN:Inanim:Fem:Sin:Nom"),
        ("брумзой-другой", "NN:Inanim:Fem:Sin:T"),
    ], ix.forms(lem, pid)
    assert ix.paras[pid].samples == ["брумза» + «другой"]

    def toy(c, lemma, fl):
        """Парадигма из полных форм на игрушечном индексе -> pid."""
        ix.paras.append(Para(c, lemma, tuple(fl), [lemma]))
        return len(ix.paras) - 1

    def got(res):
        return res[0], set(ix.forms(*res))

    # числительное с числительным: падеж, В. как И. или Р. по форме (три-четыре дома / трёх-четырёх котов)
    tri = toy(
        "Num",
        "три",
        [(f, f"Num:{c}") for f, c in (("три", "Nom"), ("трёх", "R"), ("три", "V"), ("трёх", "V"), ("тремя", "T"))],
    )
    four = [
        (f, f"Num:{c}")
        for f, c in (("четыре", "Nom"), ("четырёх", "R"), ("четыре", "V"), ("четырёх", "V"), ("четырьмя", "T"))
    ]
    assert got(ix._num_num("трёх", "три", tri, "четыре", toy("Num", "четыре", four))) == (
        "три-четыре",
        {
            ("три-четыре", "Num:Nom"),
            ("трёх-четырёх", "Num:R"),
            ("три-четыре", "Num:V"),
            ("трёх-четырёх", "Num:V"),
            ("тремя-четырьмя", "Num:T"),
        },
    )
    # род, где он есть у обоих: одна-две, одну-две
    one = toy("Num", "один", [("один", "Num:Masc:Nom"), ("одна", "Num:Fem:Nom"), ("одну", "Num:Fem:V")])
    two = toy("Num", "два", [("два", "Num:Masc:Nom"), ("две", "Num:Fem:Nom"), ("две", "Num:Fem:V"), ("двух", "Num:R")])
    assert got(ix._num_num("одну", "один", one, "два", two)) == (
        "один-два",
        {("один-два", "Num:Masc:Nom"), ("одна-две", "Num:Fem:Nom"), ("одну-две", "Num:Fem:V")},
    )
    # существительное с числительным: только ед. ч., В. неодуш. как И. (месяц-два, месяца-двух)
    nn = [("месяц", "Nom"), ("месяца", "R"), ("месяц", "V")]
    month = toy(
        "NN:Inanim:Masc",
        "месяц",
        [(f, f"NN:Inanim:Masc:Sin:{c}") for f, c in nn] + [("месяцы", "NN:Inanim:Masc:PL:Nom")],
    )
    assert got(ix._noun_num("месяца", "месяц", month, "два", two)) == (
        "месяц-два",
        {
            ("месяц-два", "NN:Inanim:Masc:Sin:Nom"),
            ("месяца-двух", "NN:Inanim:Masc:Sin:R"),
            ("месяц-два", "NN:Inanim:Masc:Sin:V"),
        },
    )
    # прилагательное с прилагательным: только полные формы, тег второй части (брумный-единственный)
    a = toy(
        "ADJ",
        "брумный",
        [
            (f, f"ADJ:Posit:{t}")
            for f, t in (
                ("брумный", "Masc:Nom"),
                ("брумного", "Masc:R"),
                ("брумный", "Masc:V"),
                ("брумного", "Masc:V"),
                ("брумная", "Fem:Nom"),
            )
        ]
        + [("брумна", "ADJ:Short:Fem")],
    )
    b = toy(
        "ADJ",
        "единственный",
        [
            (f, f"ADJ:Posit:{t}")
            for f, t in (
                ("единственный", "Masc:Nom"),
                ("единственного", "Masc:R"),
                ("единственный", "Masc:V"),
                ("единственного", "Masc:V"),
                ("единственная", "Fem:Nom"),
            )
        ],
    )
    assert got(ix._adj_adj("брумного", "брумный", a, "единственный", b)) == (
        "брумный-единственный",
        {
            ("брумный-единственный", "ADJ:Posit:Masc:Nom"),
            ("брумного-единственного", "ADJ:Posit:Masc:R"),
            ("брумный-единственный", "ADJ:Posit:Masc:V"),
            ("брумного-единственного", "ADJ:Posit:Masc:V"),
            ("брумная-единственная", "ADJ:Posit:Fem:Nom"),
        },
    )
    assert ix._adj_adj("брумна", "брумный", a, "единственный", b) is None  # краткая форма: первая часть не склоняется
    # _new_para: sort=True убирает повторы и сортирует, основа — общее начало леммы и форм
    lem, pid = ix._new_para("ADJ", "брумный", [("брумного", "T2"), ("брумный", "T1"), ("брумный", "T1")], "плёвый")
    assert ix.paras[pid] == Para("ADJ", "ый", (("ого", "T2"), ("ый", "T1")), ["плёвый"]) and lem == "брумный"
    # причастие без глагола: правятся только ячейки причастий, личных форм нет
    assert [t for t, _ in cells("PT")] == [x[0] for x in VCELLS if x[1].startswith("PT")]
    assert label("PT", []) == "прич."
    # глагол без вида и переходности в тегах LT (дрочить) не выдаётся за непереходный
    assert label("V", [("брумить", "VB:INF:")]) == "глаг. (вид и переходность не указаны)"
    assert label("V", [("брумить", "VB:INF:bezl:IMPFV")]) == "глаг. несов. безл."
    assert label("V", [("брумить", "VB:INF:INTR:PFV")]) == "глаг. сов. неперех."
    # прилагательное: кратко в меню, всеми падежами после правки; В. м.р. делится на одуш./неод.
    adj = [
        ("брумный", "ADJ:Posit:Masc:Nom"),
        ("брумного", "ADJ:Posit:Masc:R"),
        ("брумного", "ADJ:Posit:Masc:V"),
        ("брумный", "ADJ:Posit:Masc:V"),
        ("брумная", "ADJ:Posit:Fem:Nom"),
        ("брумную", "ADJ:Posit:Fem:V"),
        ("брумна", "ADJ:Short:Fem"),
    ]
    assert table("ADJ", adj) == [
        "какой?  брумный · — · брумная · —",
        "кратк.  — · — · брумна · —",
    ], table("ADJ", adj)
    full = table("ADJ", adj, full=True)
    assert full[4].split() == ["В.", "одуш.", "какого?", "брумного", "брумную"]
    assert full[5].split() == ["В.", "неод.", "какой?", "брумный"], full
    assert describe("DPT:Real:TRANS:IMPFV") == "деепричастие, настоящее время"
    assert describe("VB:Real:INTR:IMPFV:PL:P3") == "глагол, настоящее время, «они»"
    assert (
        describe("PT:Past:TRANS:PFV:STR:Fem:R")
        == "причастие, прошедшее время, страдательное, женский род, родительный падеж"
    )
    # like: образец в той же форме и в любой другой (брумзалом как клюкало), на игрушечном индексе
    t = Index.__new__(Index)
    t.paras, t.lemma_pids, t.idx = [], {}, defaultdict[str, tuple](tuple)
    ends = ("о", "а", "у", "о", "ом", "е", "а", "", "ам", "ами", "ах")
    tags = [
        f"NN:Inanim:Neut:{n}:{c}" for n, cs in (("Sin", "Nom R D V T P"), ("PL", "Nom R D T P")) for c in cs.split()
    ]
    adj = ("ый", "ого", "ому", "ым", "ом", "ая", "ой", "ую", "ое", "ые", "ых", "ыми")
    for lemma, c, ls, fl in (
        ("клюкало", "NN:Inanim:Neut", "о", tuple(zip(ends, tags))),
        ("несносный", "ADJ", "ый", tuple((e, f"ADJ:{i}") for i, e in enumerate(adj))),
    ):
        pid = len(t.paras)
        t.paras.append(Para(c, ls, fl, []))
        t.lemma_pids[lemma] = (pid,)
        for fs in dict.fromkeys(e for e, _ in fl):
            x = lemma[: len(lemma) - len(ls)] + fs
            for L in range(1, min(MAXL, len(x) - 1) + 1):
                t.idx[x[-L:]] += ((pid, fs, 1),)
    found = t.like("брумзалом", "клюкало")
    assert [lem for lem, _ in found] == ["брумзало"], found
    assert ("брумзал", "NN:Inanim:Neut:PL:R") in t.forms(*found[0]), t.forms(*found[0])
    assert [lem for lem, _ in t.like("брумзало", "клюкало")] == ["брумзало"]
    assert t.like("брумзик", "клюкало") == []
    # одна общая -й с леммой не делает слово той же формой: ближе несносной (а не лемма неубиваемой с формой неубиваемоми)
    assert [lem for lem, _ in t.like("неубиваемой", "несносный")] == ["неубиваемый"]
    assert [lem for lem, _ in t.like("неубиваемым", "несносным")] == ["неубиваемый"]
    # своё слово из tagged.txt как образец: в теггере его нет
    own = [("брумкать", [("брумкать", "VB:INF:TRANS:IMPFV"), ("брумкал", "VB:Past:TRANS:IMPFV:Masc")])]
    assert t.like("пробрумкать", "брумкал") == []
    found = t.like("пробрумкать", "брумкал", own=own)
    assert [lem for lem, _ in found] == ["пробрумкать"], found
    assert ("пробрумкал", "VB:Past:TRANS:IMPFV:Masc") in t.forms(*found[0]), t.forms(*found[0])
    print("самопроверка: ок")
