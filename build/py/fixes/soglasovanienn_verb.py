#!/usr/bin/env python3
"""док-код: docs/rules/SoglasovanieNN_Verb.md

Правки правила SoglasovanieNN_Verb (согласование подлежащего-существительного со сказуемым): кортежи PATCHES в
формате Patch из rules.py, его же загружает load_fixes. Группа SoglasovanieNN_Verb_Neut (ADD) остаётся в rules.py.
Норма, причины и отклонённые варианты — в документе.
"""

PATCHES = [
    # глагол среднего рода (Никита сказало) разбирает SoglasovanieNN_Verb_Neut с двумя вариантами, сказал и сказала;
    # здесь было бы второе замечание на том же месте с одним вариантом и неверным для безличных (Никита повезло → повёз)
    (
        "SoglasovanieNN_Verb",
        r'(<exception postag_regexp="yes" postag="VB:Past:\.\*:\.\*:PL"></exception>)',
        r'\1<exception postag_regexp="yes" postag="VB:Past:.*:Neut"></exception>',
        2,
        ["Никита сказало.", "Никита повезло.", "Мама сказало ему это."],
        [
            ("Кот грелась на солнышке.", "Кот грелся"),
            ("Кошка грелся на солнышке.", "Кошка грелась"),
        ],
    ),
    # слово времени, у которого винительный совпадает с именительным, при опущенном подлежащем — винительный
    # длительности, а не подлежащее (Час гуляли по парку, Каждый вечер гуляли у реки)
    (
        "SoglasovanieNN_Verb",
        r"(<pattern> <!-- TODO need remove)",
        (
            r'<antipattern><token regexp="yes">миг|момент|часок|час|денёк|день|вечерок|вечер|месяц|год|век|ночь|сезон|семестр'
            r'</token><token postag="VB:(Past|Real):.*PL.*" postag_regexp="yes"/></antipattern>\n                \1'
        ),
        1,
        ["Час гуляли по парку.", "Каждый вечер гуляли у реки.", "Год работали без отпуска."],
        [("Кот гуляли у реки.", None), ("Эта минута тянулись долго.", None)],
    ),
    # у знаков препинания нет тега, и исключение UNKNOWN после глагола снимало проверку на конце предложения и перед
    # запятой (Блюдо готовились.); теперь глагол не проверяется только перед словом не из словаря
    (
        "SoglasovanieNN_Verb",
        r'(<exception scope="next" postag_regexp="yes" postag="NN:\.\*:Nom\|)UNKNOWN\|(NumD_\[SDP\]\|PNN:\.\*:Nom"></exception>)',
        r'\1\2<exception scope="next" postag="UNKNOWN" regexp="yes">\\p{L}.*</exception>',
        1,
        ["Блюдо готовилось.", "Вечер танцевали Брумзик и Гуля."],
        [("Блюдо готовились.", None), ("Блюдо готовились, а потом остыло.", None)],
    ),
    # «Кот гуляли.», «Минута тянулись.» на конце предложения ловят правила м. и ж. рода ниже, с заменой; без этого
    # антишаблона их перекрывало бы это правило без замены
    (
        "SoglasovanieNN_Verb",
        r"(<pattern> <!-- TODO need remove)",
        "".join(
            '<antipattern><token postag="SENT_START" skip="-1"><exception scope="next" postag_regexp="yes" '
            'postag="NN:.*:PL:Nom"/><exception scope="next" postag_regexp="yes" postag="PNN:.*"/>'
            '<exception scope="next" regexp="yes">и|или</exception></token>'
            f'<token postag="NN:.*:{g}:Sin:Nom" postag_regexp="yes"><exception negate_pos="yes" '
            f'postag="NN:.*:{g}:Sin:Nom" postag_regexp="yes"/><exception scope="previous" regexp="yes">и|,</exception></token>'
            '<token postag="VB:Past:.*:.*:PL" postag_regexp="yes"><exception negate_pos="yes" postag_regexp="yes" '
            'postag="VB:Past:.*:.*:PL"/></token><token regexp="yes">[.;]</token></antipattern>\n                '
            for g in ("Masc", "Fem")
        )
        + r"\1",
        1,
        ["Коты гуляли."],
        [("Кот гуляли.", "Кот гулял"), ("Эта минута тянулись.", "минута тянулась"), ("Облако уплыли.", None)],
    ),
    # антишаблон перечисления («Сыр и масло делаются») срабатывал на любую запятую или «и» перед подлежащим, и второе
    # предложение не проверялось (Брумзик ушёл, и блюдо готовились быстро); после глагола и в «, и» это граница
    (
        "SoglasovanieNN_Verb",
        r'<token skip="3"  regexp="yes" >и\|,</token>',
        (
            '<token skip="3" regexp="yes">и|,<exception scope="previous" postag_regexp="yes" postag="VB:.*"/>'
            '<exception scope="previous">,</exception></token>'
        ),
        1,
        ["Сыр и сливочное масло делаются из молока.", "Брумзик ушёл, а кот и собака гуляли во дворе."],
        [("Брумзик ушёл, и блюдо готовились быстро.", None)],
    ),
    # третье правило группы проверяет только первое существительное ед. ч. в предложении (якорь SENT_START с
    # пропуском), поэтому подлежащее второго предложения после союза не проверялось (Папа сказал, что кот гуляли во
    # дворе); узкое правило: запятая, союз, сразу подлежащее и сказуемое; в конце группы, чтобы на конце
    # предложения первыми срабатывали правила рода с заменой (Мама ушла, а кот гуляли.)
    (
        "SoglasovanieNN_Verb",
        r"(Кошка грелись</marker> на солнышке\.</example>\s*</rule>)",
        r"""\1
            <rule>
                <pattern>
                    <token>,</token>
                    <token regexp="yes">что|будто|когда|пока|если|хотя|а|но|однако|зато|ибо|раз|где|куда|откуда|чтобы</token>
                    <marker>
                    <unify negate="yes">
                        <feature id="number"/>
                        <token postag="NN:.*:Sin:Nom" postag_regexp="yes"><exception negate_pos="yes" postag_regexp="yes" postag="NN:.*"/><exception postag_regexp="yes" postag="NN:.*:D"/><exception regexp="yes">пол.+|миг|момент|часок|час|денёк|день|вечерок|вечер|месяц|год|век|ночь|сезон|семестр</exception></token>
                        <token postag="VB:(Past|Real):.*" postag_regexp="yes">
                            <exception negate_pos="yes" postag_regexp="yes" postag="VB:(Past|Real):.*"/>
                            <exception postag_regexp="yes" postag="VB:(Past|Real):TRANS:.*|VB:(Past|Real):bezl:IMPFV|VB:Past:.*:Neut"/>
                            <exception scope="next" postag_regexp="yes" postag="NN:.*:Nom|NumD_[SDP]|PNN:.*:Nom"/>
                            <exception scope="next" postag="UNKNOWN" regexp="yes">\\p{L}.*</exception>
                            <exception scope="next" regexp="yes">и|более|менее|около|почти</exception>
                        </token>
                    </unify>
                    </marker>
                </pattern>
                <message>Существительное не согласуется с глаголом по числу.</message>
                <short>Ошибка в согласовании по числу</short>
                <example>Брумзик сказал, что кот гулял во дворе.</example>
                <example correction="">Брумзик сказал, что <marker>кот гуляли</marker> во дворе.</example>
            </rule>""",
        1,
        [
            "Мама сказала, что кот гулял во дворе.",
            "Мама сказала, что мы полчаса гуляли.",
            "Кот, конечно, и собака гуляли во дворе.",
        ],
        [
            ("Папа сказал, что кот гуляли во дворе.", None),
            ("Мама ушла, а кот гуляли.", "кот гулял"),
            ("Мама ушла, а блюдо готовились быстро.", None),
        ],
    ),
    # переходный глагол во мн. ч. после существительного, совпадающего с винительным, — неопределённо-личное с
    # прямым дополнением (Матч отменяют из-за дождя), а не подлежащее; у существительного без винительного это ошибка
    # (Учительница проверяют работу). Прошедшее время м. и ж. рода ловят правила рода с заменой, его не трогаем
    (
        "SoglasovanieNN_Verb",
        r'(<exception  postag_regexp="yes" postag=")VB:\(Past\|Real\):TRANS:\.\*(\|VB:\(Past\|Real\):bezl:IMPFV" />)',
        r"\1VB:Past:TRANS:.*\2",
        1,
        ["Матч отменяют из-за дождя.", "Мышь ловят в подвале."],
        [("Учительница проверяют работу по вечерам.", None)],
    ),
    (
        "SoglasovanieNN_Verb",
        r"(<pattern> <!-- TODO need remove)",
        (
            r'<antipattern><token postag="NN:.*:Sin:V" postag_regexp="yes"/>'
            r'<token postag="VB:(Past|Real):TRANS:.*" postag_regexp="yes"/></antipattern>'
            "\n                \\1"
        ),
        1,
        ["Блюдо подают горячим."],
        [("Бабушка пекут булку по субботам.", None)],
    ),
    # то же во втором предложении (Папа сказал, что мама купили книгу): правила рода его не видят
    (
        "SoglasovanieNN_Verb",
        r"VB:\(Past\|Real\):TRANS:\.\*\|(VB:\(Past\|Real\):bezl:IMPFV\|VB:Past:\.\*:Neut)",
        r"\1",
        1,
        ["Папа сказал, что матч отменили из-за дождя."],
        [("Папа сказал, что мама купили книгу.", None)],
    ),
    (
        "SoglasovanieNN_Verb",
        r'(<pattern>\s*<token>,</token>\s*<token regexp="yes">что\|будто)',
        (
            r'<antipattern><token postag="NN:.*:Sin:V" postag_regexp="yes"/>'
            r'<token postag="VB:(Past|Real):TRANS:.*" postag_regexp="yes"/></antipattern>'
            "\n                \\1"
        ),
        1,
        ["Мама сказала, что мышь поймали в подвале."],
        [("Мама ушла, а кошка поймали мышку.", None)],
    ),
    # «пол-» с согласованным определением требует сказуемого во мн. ч. (Эти полчаса тянулись долго, Наши полмира спят),
    # а словарь даёт этим словам только ед. ч.; определение в неверном числе (Эта полминуты тянулись) — ошибка
    # определения, её ловит Unify_PADJ_NN_number, а замечание здесь заняло бы то же место с неверным выводом;
    # окончание -а/-я/-ы/-и отсекает поле, полено, полотенце, полдень
    (
        "SoglasovanieNN_Verb",
        r"(<pattern> <!-- TODO need remove)",
        (
            r'<antipattern><token postag="(ADJ|PADJ|Ord):.*:Nom" postag_regexp="yes" min="1" max="3"/>'
            r'<token regexp="yes" postag="NN:.*:Neut:Sin:Nom" postag_regexp="yes">пол-?[а-яё]+[аяыи]</token>'
            r'<token postag="VB:(Past|Real):.*PL.*" postag_regexp="yes"/></antipattern>'
            "\n                \\1"
        ),
        1,
        [
            "Эти полчаса тянулись долго.",
            "Эти долгие полчаса тянулись медленно.",
            "Томительные полминуты казались вечностью.",
            "Наши полмира спят.",
            "Эта полминуты тянулись долго.",
        ],
        [
            ("Полминуты тянулись долго.", None),
            ("Эта минута тянулись долго.", None),
            ("Этот полдень тянулись долго.", None),
        ],
    ),
    # при «пол-» с определением во мн. ч. сказуемое ставится во мн. ч. (Эти полчаса прошло незаметно → прошли), а
    # словарь даёт «пол-» только ед. ч., и проверка числа ошибки не видит; только глаголы течения времени и только
    # без другого подлежащего после глагола: иначе это винительный времени (Эти полчаса шло совещание, моросило)
    (
        "SoglasovanieNN_Verb",
        r'(<example correction="">Брумзик сказал, что <marker>кот гуляли</marker> во дворе\.</example>\s*</rule>)',
        r"""\1
            <rule>
                <antipattern><token regexp="yes" postag="NN:.*:Neut:Sin:Nom" postag_regexp="yes">пол-?[а-яё]+[аяыи]</token><token postag="VB:.*" postag_regexp="yes" skip="4"/><token postag="NN:.*:Sin:Nom|PNN:.*:Nom" postag_regexp="yes"><exception scope="previous" postag="PREP"/></token></antipattern>
                <pattern>
                    <token postag="(ADJ|PADJ|Ord):.*PL:Nom" postag_regexp="yes"><exception scope="previous" postag="PREP"/><exception>каждые</exception></token>
                    <token postag="(ADJ|PADJ|Ord):.*PL:Nom" postag_regexp="yes" min="0" max="2"/>
                    <token regexp="yes" postag="NN:.*:Neut:Sin:Nom" postag_regexp="yes">пол-?[а-яё]+[аяыи]</token>
                    <marker>
                    <token inflected="yes" regexp="yes" postag="VB:Past:.*:Neut|VB:Real:.*:Sin:P3" postag_regexp="yes">пройти|проходить|пролететь|пролетать|тянуться|протянуться|длиться|продлиться|уйти|уходить|истечь|минуть|миновать|промелькнуть|промчаться|пробежать</token>
                    </marker>
                </pattern>
                <message>При «пол-» с определением во множественном числе сказуемое ставится во множественном числе: <suggestion><match no="4" postag="VB:(.*):(?:Neut|Sin(:P3))" postag_regexp="yes" postag_replace="VB:$1:PL$2"/></suggestion></message>
                <short>Ошибка в согласовании по числу</short>
                <example>Эти полчаса прошли незаметно.</example>
                <example correction="прошли">Эти полчаса <marker>прошло</marker> незаметно.</example>
            </rule>""",
        1,
        [
            "Эти полчаса прошли незаметно.",
            "Полчаса прошло незаметно.",
            "Эти полчаса длилось совещание.",
            "Эти полчаса было тихо.",
            "Каждые полчаса проходит поезд.",
            "За эти полчаса прошло совещание.",
            "Эти полчаса тянулось очень долгое совещание.",
        ],
        [
            ("Эти полчаса прошло незаметно.", "прошли"),
            ("Целые полдня ушло на сборы.", "ушли"),
            ("Эти полчаса тянется бесконечно.", "тянутся"),
        ],
    ),
]
