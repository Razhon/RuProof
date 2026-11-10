#!/usr/bin/env python3
"""док-код: docs/rules/Unify_PADJ_NN_number.md

Правки правил Unify_PADJ_NN_number, _case, _gender (согласование местоимения-прилагательного с существительным)
и новые правила рядом с ними: кортежи PATCHES/ADD в формате Patch/Add из rules.py, его же загружает load_fixes.
Правки одного правила — в одном модуле, поэтому здесь и пропуски из docs/rules/Unify-PADJ-Propuski.md (глагольные
чтения, род и падеж вместе, «пол-», «Твои пальто висит», «Тот дома стоят»). Норма, причины и отклонённые варианты —
в документах. Unify_PADJ_NN_gender_case нужен dict/disambiguation.xml с блоками <unification> (rules.py apply):
его antipattern с <unify> берёт unifier снятия омонимии. Замену без {suggestion} (в наши саду) даёт Java-правка
build/java/AdvancedSynthesizerFilter.java, её случаи — в JAVA_CASES rules.py.
"""

PATCHES = [
    # «пару» в значении «несколько» с мн. ч. местоимения (за эти пару месяцев): норма колеблется, справочная Грамоты
    # признаёт и «последние пару лет»; ошибкой согласования по числу это не считаем
    (
        "Unify_PADJ_NN_number",
        r"(\s*<pattern>)",
        (
            r'<antipattern><token postag="ADJ:MPR:PL:.*" postag_regexp="yes"/><token>пару</token>'
            r'<token postag="NN:.*:PL:R" postag_regexp="yes"/></antipattern>\1'
        ),
        1,
        ["За эти пару месяцев Брумзик многого добился.", "Наши пару недель прошли быстро."],
        [("Мои книга лежит на столе.", "Моя книга")],
    ),
]

# глагольное чтение у «мой», «мою», «моя», «нашей» (мыть, нашить) не снимает правила после предлога (в мою дом):
# повелительное наклонение и деепричастие после предлога невозможны
VERB = (
    r'<antipattern><token postag="VB:.*|DPT:.*" postag_regexp="yes">'
    r'<exception scope="previous" postag="PREP"/></token><token postag="NN:.*:(V|D|T)|NN:[^:]+:[^:]+" postag_regexp="yes"/></antipattern>\1'
)
PADJ = ("Unify_PADJ_NN_case", "Unify_PADJ_NN_gender", "Unify_PADJ_NN_number")
PATCHES += [
    (
        rid,
        r'(negate_pos="yes"\s+postag="ADJ:MPR:\.\*)"',
        r'\1|VB:.*|DPT:.*"',
        2 if rid.endswith("number") else 1,
        ["Мой голову шампунем.", "Моя посуду, Брумзик пел.", "Мой сапоги щёткой."],
        [],
    )
    for rid in PADJ
] + [
    ("Unify_PADJ_NN_gender", r"(\s*<pattern>)", VERB, 1, [], [("Брумзик зашёл в мою дом.", "мой дом")]),
    ("Unify_PADJ_NN_case", r"(\s*<pattern>)", VERB, 1, [], [("Брумзик гулял в мой саду.", None)]),
    ("Unify_PADJ_NN_number", r"(\s*<pattern>)", VERB, 1, [], [("Брумзик гулял в мои саду.", None)]),
]

# у «чаю» есть чтение «чаять» (1-е лицо), и исключение VB у существительного снимало правило (налил мои чаю);
# глагол 1-го лица наст. времени сразу после местоимения-прилагательного не встречается; то же — в XML
# Unify_PADJ_NN_gender_case ниже
NOT_P1 = "VB:(?!Real:.*:P1$).*|CONJ"
PATCHES += [
    (
        rid,
        r'<exception postag="VB:\.\*\|CONJ',
        f'<exception postag="{NOT_P1}',
        2 if rid.endswith("number") else 1,
        ["Брумзик налил моего чаю.", "Того стали ругать."],
        [("Брумзик налил мои чаю.", None)] if rid.endswith("number") else [],
    )
    for rid in PADJ
]

# под ADJ:MPR попадают и указательные «этот», «тот» (Этот книга), а сообщение называло их притяжательными; типа не
# было (uncategorized), хотя это грамматическая ошибка
PATCHES += [
    (
        rid,
        r'(<rule\s+id="[^"]+")\s+name="Согласование притяжательного прилагательного \(местоимения\)',
        r'\1 type="grammar" name="Согласование местоимения',
        1,
        [],
        [],
    )
    for rid in PADJ
] + [
    (rid, r"Притяжательное прилагательное \(местоимение\)", "Местоимение", 1, ["Это ваша супруга?"], [must])
    for rid, must in zip(
        PADJ,
        [
            ("Брумзик гордится этот домом.", "этим домом"),
            ("Этот книга интересная.", "Эта книга"),
            ("Эти отношение странное.", "Это отношение"),
        ],
    )
]

ADD = [
    # «эти пару дней»: справочная Грамоты (вопрос 326881) считает нормой ед. ч. (эту пару дней), но мн. ч. преобладает
    # в речи, поэтому подсказка style, а не ошибка; правильную форму Unify_PADJ_NN_number предложить не может.
    # Замена всегда в вин. п. (эту пару), поэтому только после предлога с вин. п.: в «Наши пару недель прошли» и «в
    # течение этих пару дней» она была бы неверна, а им. п. от вин. п. по тегам «наши», «эти» не отличить.
    # «каких-то», «каких-нибудь» (осталось каких-то пару шагов) — «всего лишь» при числе, согласовано с «шагов»
    # (docs/rules/PARU_SOGLASOVANIE.md)
    (
        "Unify_PADJ_NN_number",
        """
        <rule id="PARU_SOGLASOVANIE" name="Согласование с «пару»: «эту пару дней»" type="style">
            <pattern>
                <token regexp="yes">за|на|через|в|во|про|сквозь</token>
                <marker>
                    <token postag="ADJ:MPR:PL:V.*" postag_regexp="yes"><exception inflected="yes" regexp="yes">который|сам|самый|каждый|весь|оба|обе</exception><exception regexp="yes">каких-(то|нибудь)</exception></token>
                    <token>пару</token>
                </marker>
                <token postag="NN:.*:PL:R" postag_regexp="yes"/>
            </pattern>
            <message>Возможно, лучше согласовать с «пара» в единственном числе: <suggestion><match no="2" postag="ADJ:MPR:PL:.*" postag_regexp="yes" postag_replace="ADJ:MPR:Fem:V"/> \\3</suggestion>. Форма «эти пару» распространена в речи, но нормой считается «эту пару».</message>
            <short>«эту пару дней»</short>
            <example correction="эту пару">За <marker>эти пару</marker> месяцев он вырос.</example>
            <example>За эту пару месяцев он вырос.</example>
        </rule>""",
        [
            "За эту пару месяцев Брумзик многого добился.",
            "В последние пару лет Брумзик не писал.",
            "Мои пара носков пропала.",
            "Наши пару недель прошли быстро.",
            "В течение этих пару дней Брумзик молчал.",
            "До моста оставалось всего каких-то пару шагов.",
            "За каких-то пару недель Брумзик вырос.",
            "Через каких-нибудь пару месяцев всё изменится.",
        ],
        [
            ("За эти пару месяцев Брумзик многого добился.", "эту пару"),
            ("Брумзик ушёл на свои пару часов.", "свою пару"),
        ],
    ),
]

# сложения «пол-» с родительным (полчаса, полминуты): словарь размечает их NN:Inanim:Neut:Sin. Тот же шаблон — в
# fixes/soglasovanienn_verb.py: меняется — править оба
POL_RE = "пол-?[а-яё]+[аяиы]"
POL = f'<exception regexp="yes" postag="NN:Inanim:Neut:Sin:.*" postag_regexp="yes">{POL_RE}</exception>'
# косвенные формы «полу-» словарь размечает ср. р., а род у них — второй части (к этой полуминуте)
POLU = '<exception regexp="yes" postag="NN:Inanim:Neut:Sin:(R|D|T|P)" postag_regexp="yes">полу[а-яё]+</exception>'
# вместо «пол.*» LT (полчаса, полдня), глушившего и «полк», «полку», «полковника»; «полдня» — ещё и форма «полдень»
POL_EXC = POL + '<exception regexp="yes">полдня|полночи</exception>' + POLU

# род и падеж проверяются раздельно: у «лесу» есть чтение «леса» (ж. р., вин.), и в «в моей лесу» род совпадает
# с одним чтением, падеж — с другим; правило ловит, когда ни одно чтение не сходится по обоим признакам сразу
ADD += [
    (
        "PARU_SOGLASOVANIE",
        """
        <rule id="Unify_PADJ_NN_gender_case" name="Согласование местоимения с существительным по роду и падежу вместе (одно чтение)">
            <antipattern><unify negate="yes"><feature id="gender"/><token postag="ADJ:MPR:.*" postag_regexp="yes"/><token postag="NN:.*" postag_regexp="yes"/></unify></antipattern><antipattern><unify negate="yes"><feature id="case"/><token postag="ADJ:MPR:.*" postag_regexp="yes"/><token postag="NN:.*" postag_regexp="yes"/></unify></antipattern>
            <antipattern><token postag="VB:.*|DPT:.*" postag_regexp="yes"><exception scope="previous" postag="PREP"/></token><token postag="NN:.*:(V|D|T)|NN:[^:]+:[^:]+" postag_regexp="yes"/></antipattern>
            <pattern>
                <marker>
                    <unify negate="yes">
                        <feature id="gender"/>
                        <feature id="case"/>
                        <token postag="ADJ:MPR:.*" postag_regexp="yes"><exception negate_pos="yes" postag="ADJ:MPR:.*|VB:.*|DPT:.*" postag_regexp="yes"/><exception postag="ADJ:MPR:PL.*" postag_regexp="yes"/><exception scope="previous" regexp="yes">,|–|-|—|при|оба|обе</exception><exception inflected="yes" regexp="yes">который|такой|сам|самый|каждый|свой|другой|оба|обе</exception><exception scope="previous" postag="NN:.*" postag_regexp="yes"/></token>
                        <token postag="NN:.*" postag_regexp="yes">
                            <exception regexp="yes">друг|уже|уж|при|после|весь|мировой|молодой|куплю|байке|лажа|лазанью</exception>
                            <exception postag="VB:(?!Real:.*:P1$).*|CONJ|PREP|ADV|ADJ:.*" postag_regexp="yes"/>
                            <exception regexp="yes">&missing_yo;</exception>
                            <exception scope="next" regexp="yes">&double_num;</exception>
                            <exception case_sensitive="yes">Tом</exception>
                            """
        + POL_EXC
        + """
                        </token>
                    </unify>
                </marker>
            </pattern>
            <filter class="org.languagetool.rules.ru.AdvancedSynthesizerFilter" args="lemmaFrom:1 lemmaSelect:ADJ:MPR:.*:.* postagFrom:2 postagSelect:NN:.*:(.*):.*:(.*) postagReplace:ADJ:MPR:\\b1:\\b2"/>
            <message>Местоимение не согласуется с существительным по роду или падежу.</message>
            <suggestion>{suggestion} \\2</suggestion>
            <short>Не согласуются по роду или падежу</short>
            <example correction="">Он гулял в <marker>моей лесу</marker>.</example>
            <example>Он гулял в моём лесу.</example>
        </rule>""",
        [
            "Брумзик гулял в моём лесу.",
            "Брумзик поставил книгу на мою полку.",
            "Брумзик сидел в моём кафе.",
            "Брумзик подошёл к этой полуминуте.",
        ],
        [("Брумзик гулял в моей лесу.", None)],
    ),
]

# «пол.*» LT глушит любое слово на «пол» (Эта полк, моей полковника, к моей полку): только сложения «пол-»
PATCHES += [
    (rid, r'<exception regexp="yes">пол\.\*</exception>', POL_EXC, n, ok, [])
    for rid, n, ok in (
        (
            "Unify_PADJ_NN_gender",
            1,
            [
                "Брумзик подошёл к этой полуминуте.",
                "Брумзик гордился этой полуминутой.",
                "Каждые полчаса Брумзик вставал.",
            ],
        ),
        ("Unify_PADJ_NN_number", 2, ["Каждые полчаса Брумзик вставал.", "Эти полдня Брумзик спал."]),
    )
]

# «этой полминуты»: в косвенных падежах «пол-» склоняется (этой полуминуты); прежнюю замену «Это полминуты» _case
# не даёт, её делает Unify_PADJ_POL; форма существительного — по падежу местоимения
PATCHES += [
    (
        "Unify_PADJ_NN_case",
        r'(<exception case_sensitive="yes">Tом</exception>)',
        r"\1" + POL,
        1,
        ["Брумзику не хватило этой полминуты."],
        [],
    )
]
POLN = f'<token postag="NN:Inanim:Neut:Sin:Nom" postag_regexp="yes" regexp="yes">{POL_RE}<exception postag="NN:.*:(R|D|T|P)" postag_regexp="yes"/><exception>полжизни</exception></token>'
ADD += [
    (
        "PARU_SOGLASOVANIE",
        # падеж «этой» (Р/Д/Т/П) виден только по предлогу: без предлога ж. р. не трогаем, твор. ж. р. тоже (синтез первой даёт «полуминутою»); «полжизни» не склоняется (БТС)
        '\n        <rulegroup id="Unify_PADJ_POL" name="«Пол-» в косвенном падеже после местоимения">'
        + "".join(
            f"""
            <rule>
                <pattern>
                    {prep}<marker>
                        <token postag="{pron}" postag_regexp="yes"><exception postag="{exc}" postag_regexp="yes"/></token>
                        {POLN}
                    </marker>
                </pattern>
                <filter class="org.languagetool.rules.ru.AdvancedSynthesizerFilter" args="lemmaFrom:{n + 1} lemmaSelect:NN:Inanim:Neut:Sin:Nom postagFrom:{n} postagSelect:{sel} postagReplace:NN:Inanim:Neut:Sin:\\b1"/>
                <message>В косвенном падеже «пол-» склоняется: «полу-» и вторая часть в нужном падеже.</message>
                <suggestion>\\{n} {{suggestion}}</suggestion>
                <short>«Пол-» не в том падеже</short>
                <example correction="{ex[1]}">{ex[0]}</example>
            </rule>"""
            for prep, pron, exc, sel, n, ex in (
                (
                    "",
                    "ADJ:MPR:(Masc|Neut):(D|T|P)",
                    "ADJ:MPR:.*:(Nom|R)|VB:.*|DPT:.*",
                    "ADJ:MPR:(?:Masc|Neut):(D|T|P)",
                    1,
                    ("Брумзик гордился <marker>этим полчаса</marker>.", "этим получасом"),
                ),
                (
                    '<token regexp="yes">к|ко|по|благодаря|вопреки|согласно|навстречу</token>',
                    "ADJ:MPR:Fem:D",
                    "ADJ:MPR:.*:(Nom|V)|VB:.*|DPT:.*",
                    "ADJ:MPR:Fem:(D)",
                    2,
                    ("Брумзик подошёл к <marker>этой полминуты</marker>.", "этой полуминуте"),
                ),
                (
                    '<token regexp="yes">о|об|обо|при|в|во|на</token>',
                    "ADJ:MPR:Fem:P",
                    "ADJ:MPR:.*:(Nom|V)|VB:.*|DPT:.*",
                    "ADJ:MPR:Fem:(P)",
                    2,
                    ("Брумзик думал об <marker>этой полминуты</marker>.", "этой полуминуте"),
                ),
            )
        )
        + "\n        </rulegroup>",
        [
            "Мне хватило этой полуминуты.",
            "Брумзик радовался этой полминуты.",
            "Брумзик думал о моей полжизни.",
            "За эту полминуты Брумзик успел.",
            "Брумзик гордился этим получасом.",
        ],
        [
            ("Брумзик подошёл к этой полминуты.", "этой полуминуте"),
            ("Брумзик гордился этим полчаса.", "этим получасом"),
            ("Брумзик думал об этой полминуты.", "этой полуминуте"),
        ],
    ),
    (
        "PARU_SOGLASOVANIE",
        # родительный «этой полминуты» словари допускают как разговорный (орфографический словарь: род. полминуты, разг.)
        '\n        <rulegroup id="Unify_PADJ_POL_R" name="«Пол-» в родительном падеже после местоимения" type="style">'
        + "".join(
            f"""
            <rule>
                <pattern>
                    {prep}<marker>
                        <token postag="{pron}" postag_regexp="yes"><exception postag="ADJ:MPR:.*:Nom|ADJ:MPR:Fem:V|VB:.*|DPT:.*" postag_regexp="yes"/></token>
                        {POLN}
                    </marker>
                </pattern>
                <filter class="org.languagetool.rules.ru.AdvancedSynthesizerFilter" args="lemmaFrom:{n + 1} lemmaSelect:NN:Inanim:Neut:Sin:Nom postagFrom:{n} postagSelect:{sel} postagReplace:NN:Inanim:Neut:Sin:\\b1"/>
                <message>В книжной речи «пол-» в родительном падеже склоняется; «\\{n} \\{n + 1}» — разговорный вариант.</message>
                <suggestion>\\{n} {{suggestion}}</suggestion>
                <short>«Пол-» в родительном: книжный вариант</short>
                <example correction="{ex[1]}">{ex[0]}</example>
            </rule>"""
            for prep, pron, sel, n, ex in (
                (
                    "",
                    "ADJ:MPR:(Masc|Neut):R",
                    "ADJ:MPR:(?:Masc|Neut):(R)",
                    1,
                    ("Брумзик не ждал <marker>этого полгода</marker>.", "этого полугода"),
                ),
                (
                    '<token regexp="yes">около|до|после|без|для|из|от|у|вокруг|кроме|среди|возле|вместо|ради|мимо|вдоль|против</token>',
                    "ADJ:MPR:Fem:R",
                    "ADJ:MPR:Fem:(R)",
                    2,
                    ("Около <marker>этой полминуты</marker> Брумзик ждал.", "этой полуминуты"),
                ),
            )
        )
        + "\n        </rulegroup>",
        [
            "Брумзику не хватило этой полминуты.",
            "Около этой полуминуты Брумзик ждал.",
            "Брумзик не ждал этого полугода.",
        ],
        [
            ("Брумзик не ждал этого полгода.", "этого полугода"),
            ("Около этой полминуты Брумзик ждал.", "этой полуминуты"),
        ],
    ),
    (
        "PARU_SOGLASOVANIE",
        # определение при «пол-» в именительном — во мн. ч. (эти полчаса); «это полчаса» не трогаем: «это» и частица
        """
        <rule id="Unify_PADJ_POL_number" name="Определение при «пол-» в единственном числе">
            <pattern>
                <marker>
                    <token postag="ADJ:MPR:(Masc|Fem):(Nom|V)" postag_regexp="yes"><exception postag="VB:.*|DPT:.*" postag_regexp="yes"/></token>
                    <token postag="NN:Inanim:Neut:Sin:(Nom|V)" postag_regexp="yes" regexp="yes">"""
        + POL_RE
        + """<exception postag="NN:.*:(R|D|T|P)" postag_regexp="yes"/></token>
                </marker>
            </pattern>
            <message>Определение при «пол-» ставится во множественном числе.</message>
            <suggestion><match no="1" postag="ADJ:MPR:(Masc|Fem):(Nom|V)" postag_regexp="yes" postag_replace="ADJ:MPR:PL:Nom"/> \\2</suggestion>
            <short>Определение при «пол-» во мн. ч.</short>
            <example correction="Эти полминуты"><marker>Эта полминуты</marker> прошли незаметно.</example>
            <example>Эти полминуты тянулись долго.</example>
        </rule>""",
        ["Эти полминуты тянулись долго.", "Это полчаса, не больше.", "Мои полгода прошли.", "Полчаса прошло."],
        [
            ("Эта полминуты тянулись долго.", "Эти полминуты"),
            ("Брумзик знал, что эта полминуты решат всё.", "эти полминуты"),
            ("Этот полчаса прошёл быстро.", "Эти полчаса"),
            ("За эту полминуты Брумзик успел.", "эти полминуты"),
            ("На ту полминуты Брумзик опоздал.", "те полминуты"),
        ],
    ),
]

# «Твои пальто висит»: у несклоняемого существительного число видно только по определению; нет правила, которое
# сверяло бы с ним число глагола. Только непереходные и не безличные глаголы: «Эти пальто носит Брумзик» (дополнение),
# «Эти кафе стоит посетить» (безличное) верны
NNV = "NN:(Anim|Inanim):(Masc|Fem|Neut)"
ADD += [
    (
        "PARU_SOGLASOVANIE",
        '\n        <rulegroup id="Soglasovanie_PADJ_NN_Verb" name="Сказуемое в ед. ч. при подлежащем «местоимение во мн. ч. + несклоняемое»">'
        + "".join(
            f"""
            <rule>
                <pattern>
                    <token postag="ADJ:MPR:PL:Nom" postag_regexp="yes"><exception scope="previous" postag="PREP"/></token>
                    <token postag="{NNV}" postag_regexp="yes"/>
                    <marker><token postag="{vb}" postag_regexp="yes"><exception postag="VB:.*(TRANS|bezl).*" postag_regexp="yes"/></token></marker>
                </pattern>
                <message>Сказуемое не согласуется с подлежащим «\\1 \\2» по числу.</message>
                <suggestion><match no="3" postag="{vb}" postag_regexp="yes" postag_replace="{rep}"/></suggestion>
                <short>Сказуемое во мн. ч.</short>
                <example correction="{ex[1]}">{ex[0]}</example>
            </rule>"""
            for vb, rep, ex in (
                (
                    "VB:Real:INTR:([^:]+):Sin:P3",
                    "VB:Real:INTR:$1:PL:P3",
                    ("Твои пальто <marker>висит</marker> в шкафу.", "висят"),
                ),
                (
                    "VB:Past:INTR:([^:]+):(Masc|Fem|Neut)",
                    "VB:Past:INTR:$1:PL",
                    ("Мои пальто <marker>висел</marker> в шкафу.", "висели"),
                ),
            )
        )
        + "\n        </rulegroup>",
        ["Твои пальто висят в шкафу.", "Эти кафе стоит посетить.", "Эти пальто носит Брумзик."],
        [("Твои пальто висит в шкафу.", "висят"), ("Мои пальто висел в шкафу.", "висели")],
    ),
]

# «Тот дома стоят»: у «дома» есть чтение наречия, и все три правила его исключают; глагол во мн. ч. снимает омонимию
# («Тот дома сидит» — местоимение-подлежащее и наречие, верно)
ADD += [
    (
        "PARU_SOGLASOVANIE",
        """
        <rule id="Unify_PADJ_NN_number_ADV" name="Местоимение в ед. ч. при существительном-наречии и глаголе во мн. ч.">
            <pattern>
                <marker>
                    <token postag="ADJ:MPR:(Masc|Fem|Neut):Nom" postag_regexp="yes"><exception postag="ADJ:MPR:PL:.*" postag_regexp="yes"/><exception scope="previous" postag="PREP"/></token>
                    <and><token postag="ADV"/><token postag="NN:.*:PL:Nom" postag_regexp="yes"/></and>
                </marker>
                <token postag="VB:(Real:.*:PL:P3|Past:.*:PL)" postag_regexp="yes"/>
            </pattern>
            <message>Местоимение не согласуется с существительным по числу.</message>
            <suggestion><match no="1" postag="ADJ:MPR:(Masc|Fem|Neut):Nom" postag_regexp="yes" postag_replace="ADJ:MPR:PL:Nom"/> \\2</suggestion>
            <short>Не согласуются по числу</short>
            <example correction="Те дома"><marker>Тот дома</marker> стоят на холме.</example>
            <example>Тот дома сидит, а этот в саду.</example>
        </rule>""",
        ["Тот дома сидит, а этот в саду.", "Те дома стоят на холме.", "Тот дома, а этот в саду."],
        [("Тот дома стоят на холме.", "Те дома"), ("Эта дома стоят на холме.", "Эти дома")],
    ),
]
