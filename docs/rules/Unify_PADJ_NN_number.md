# Unify_PADJ_NN_number: согласование местоимения-прилагательного с существительным по числу

- **Правило LT:** `Unify_PADJ_NN_number`, `dict/grammar.xml`; фильтр замены — Java-класс
  `org.languagetool.rules.ru.AdvancedSynthesizerFilter` (наследник `org.languagetool.rules.AbstractAdvancedSynthesizerFilter`);
  новое правило `PARU_SOGLASOVANIE`
- **док-код:** `build/py/fixes/unify_padj_nn_number.py`; Java: `build/java/AdvancedSynthesizerFilter.java`
- **Образ:** `erikvl87/languagetool:6.8`, дата разбора 2026-11-09

| Дефект | Тип | Причина | Статус |
|--------|-----|---------|--------|
| 1. «эти пару дней» помечается как ошибка согласования по числу | ложное срабатывание (норма колеблется) | grammar.xml | реализовано (вариант 1.2) |
| 2. в замене остаётся буквальный текст `{suggestion}` | ошибка вывода замены | Java (фильтр синтеза) | реализовано (вариант 2.2) |
| 3. сообщение называет «этот», «тот» притяжательными; тип `uncategorized` (также `_case`, `_gender`) | неточное сообщение | grammar.xml | реализовано (вариант 3.1) |

## Исходное правило

Ловит местоимение-прилагательное (`ADJ:MPR`: мой, наш, этот…) рядом с существительным другого числа: «эти отношение»
→ «это отношение». Пара токенов под `<unify negate="yes"><feature id="number"/>`; исключения у первого токена
(после запятой, тире, «при», «два», «три», «оба»; леммы который|такой|сам|самый|каждый|свой|другой|оба|обе; перед ним
существительное), у второго — список слов, «пол…», несколько частей речи. Одно `antipattern` — однородные
существительные («мои дедушка с бабушкой»).

Замену строит фильтр:

```text
<filter class="org.languagetool.rules.ru.AdvancedSynthesizerFilter" args="lemmaFrom:1 lemmaSelect:ADJ:MPR:.*:.*
    postagFrom:2 postagSelect:NN:.*:(.*):.*:(.*) postagReplace:ADJ:MPR:\b1:\b2"/>
<suggestion>{suggestion} \2</suggestion>
```

Лемма берётся у местоимения, род и падеж (`\b1`, `\b2`) — у **первого** чтения существительного, подходящего под
`postagSelect`; синтезатор строит `ADJ:MPR:<род>:<падеж>` и подставляет форму вместо `{suggestion}`.

Тот же фильтр с тем же `postagSelect` стоит ещё в `Unify_PADJ_NN_case`, `Unify_PADJ_NN_gender` и `Unify_Adj_NN_case`.

Правки: запись `PATCHES` и правило `PARU_SOGLASOVANIE` в `ADD` в `build/py/fixes/unify_padj_nn_number.py`, класс
`build/java/AdvancedSynthesizerFilter.java` (строка монтирования в `compose.yaml`, случаи в `JAVA_CASES`
`build/py/rules.py`). Итог: полный `rules.py check` прошёл (0 FAIL, `java: случаев 2`);
`tools/check.ps1 selfcheck ruff pyright rules`: OK. На 34 тестовых фразах разбора: «эти/наши/мои/свои/ваши пару» +
род. мн. (11 фраз) — `PARU_SOGLASOVANIE` [style] с заменой «эту/нашу/мою/свою/вашу пару», регистр сохраняется;
«в наши саду», «на эти мосту», «в эти году» — `Unify_PADJ_NN_number` без замены; «Эти тысяча», «Эти отношение», «Мои
книга», «Наши дом», «Эти окно», «Мои пара носков», «Эти пара дней» — как до правок, с верной заменой; остальные молчат.
Пропуски «Твои пальто», «мои чаю», «в мой саду», «в моей лесу» и определение при «пол-» («Эта полминуты») закрыты
позже в том же модуле: [Unify-PADJ-Propuski](Unify-PADJ-Propuski.md). После правки 3.1: `rpdict` (полный
`rules.py check`) прошёл, `tools/check.ps1 selfcheck ruff pyright rules`: OK.

## Дефект 1. «эти пару дней»

### Реализация

В `Unify_PADJ_NN_number` перед `<pattern>` — antipattern «мест. мн. ч. + пару + сущ. род. мн.»:

```diff
+<antipattern><token postag="ADJ:MPR:PL:.*" postag_regexp="yes"/><token>пару</token>
+<token postag="NN:.*:PL:R" postag_regexp="yes"/></antipattern>
 <pattern>
```

ok: «За эти пару месяцев Брумзик многого добился.», «Наши пару недель прошли быстро.»; must: «Мои книга лежит на
столе.» → «Моя книга».

После правила — новое `PARU_SOGLASOVANIE` (`type="style"`):

```text
<rule id="PARU_SOGLASOVANIE" name="Согласование с «пару»: «эту пару дней»" type="style">
    <pattern>
        <marker>
            <token postag="ADJ:MPR:PL:.*" postag_regexp="yes"><exception inflected="yes" regexp="yes">который|сам|самый|каждый|весь|оба|обе</exception></token>
            <token>пару</token>
        </marker>
        <token postag="NN:.*:PL:R" postag_regexp="yes"/>
    </pattern>
    <message>Возможно, лучше согласовать с «пара» в единственном числе: <suggestion><match no="1" postag="ADJ:MPR:PL:.*" postag_regexp="yes" postag_replace="ADJ:MPR:Fem:V"/> \2</suggestion>. Форма «эти пару» распространена в речи, но нормой считается «эту пару».</message>
    <short>«эту пару дней»</short>
    …
</rule>
```

ok: «За эту пару месяцев Брумзик многого добился.», «В последние пару лет Брумзик не писал.», «Мои пара носков
пропала.»; must: «За эти пару месяцев Брумзик многого добился.» → «эту пару», «Наши пару недель прошли быстро.» →
«Нашу пару», «Брумзик потратил свои пару часов на сон.» → «свою пару».

Позже правило сужено (только после предлога с вин. п., без «каких-то пару»), случаи изменены:
[PARU_SOGLASOVANIE](PARU_SOGLASOVANIE.md).

### Почему этот вариант

Справочная служба Грамоты.ру (вопрос № 326881, https://gramota.ru/spravka/buro/search-answer?s=326881): «Нормативным
является согласование местоимений с существительным пара в форме единственного числа» («эту пару дней»; «пара» —
ж. р., ед. ч., согласование по форме, не по смыслу), мн. ч. названо массовой ошибкой. Более ранний ответ № 216301
(2007, https://gramota.ru/spravka/buro/search-answer?s=216301) признал «в последние пару лет» корректным: справочная
непоследовательна, мн. ч. частотно, поэтому подсказка `style`, а не ошибка. Правило видело только несовпадение числа («пару» — ед. ч., «эти» — мн. ч.) и не знало, что «пару»
здесь — счётное слово. Вариант 1.1 (только antipattern) молчал полностью и терял подсказку строгой нормы. Принятый
риск: конструкция по-прежнему подсвечивается (как style-подсказка), а «свои пару часов», прежде молчавшее из-за
исключения «свой», теперь тоже получает подсказку.

## Дефект 2. Буквальный `{suggestion}` в замене

### Реализация

`build/java/AdvancedSynthesizerFilter.java` — копия класса LT 6.8 с переопределённым `acceptRuleMatch` (якорь
`// образ: sha256 0c4e5112… /LanguageTool/org/languagetool/rules/ru/AdvancedSynthesizerFilter.class`, строка
«Изменено в 2026 году, Razhon…»), монтируется поверх класса образа:

```diff
+  @Override
+  public RuleMatch acceptRuleMatch(RuleMatch match, Map<String, String> arguments, int patternTokenPos,
+                                   AnalyzedTokenReadings[] patternTokens, List<Integer> tokenPositions) throws IOException {
+    RuleMatch m = super.acceptRuleMatch(match, arguments, patternTokenPos, patternTokens, tokenPositions);
+    if (m == null) {
+      return null;
+    }
+    // синтез не дал формы: родительский класс возвращает замечание с буквальным {suggestion} в замене
+    List<String> ok = m.getSuggestedReplacements().stream()
+        .filter(r -> !r.toLowerCase().contains("{suggestion}"))
+        .collect(Collectors.toList());
+    if (ok.size() != m.getSuggestedReplacements().size()) {
+      m.setSuggestedReplacements(ok);
+    }
+    return m;
+  }
```

`JAVA_CASES`: `Unify_PADJ_NN_number` молчит на «Брумзик гулял в моём саду.» и ловит «Брумзик гулял в наши саду.» без
замены (`None`).

### Почему этот вариант

Замена должна быть словом или отсутствовать. `AbstractAdvancedSynthesizerFilter` берёт первое чтение существительного
(у «саду», «мосту», «году», «пару» это `2R`/`2P`), тега `ADJ:MPR:Masc:2R` нет, синтез пуст, и метод возвращает
замечание с сырым шаблоном. Вариант 2.1 (`2?` в `postagSelect`) давал грамматичные, но неверные замены («нашего саду»,
«этом пару»); 2.3 (`return null`) глушил настоящие ошибки («в наши саду»). 2.2 закрывает дефект во всех четырёх
правилах с этим фильтром. Принятый риск: при обновлении образа правку надо сверять с новым исходником (сборка
остановится по якорю).

## Дефект 3. Сообщение и тип

### Реализация

В `Unify_PADJ_NN_case`, `_gender`, `_number` — две правки на правило (шесть записей `PATCHES`):

```diff
-<rule  id="Unify_PADJ_NN_gender" name="Согласование притяжательного прилагательного (местоимения) с существительным по роду">
+<rule  id="Unify_PADJ_NN_gender" type="grammar" name="Согласование местоимения с существительным по роду">
-<message>Притяжательное прилагательное (местоимение) не согласуется с существительным по роду.</message>
+<message>Местоимение не согласуется с существительным по роду.</message>
```

ok: «Это ваша супруга?»; must: «Брумзик гордится этот домом.» → «этим домом» (`_case`), «Этот книга интересная.» →
«Эта книга» (`_gender`), «Эти отношение странное.» → «Это отношение» (`_number`); тип `grammar` проверяется на каждом
случае.

### Почему этот вариант

Под тег `ADJ:MPR` попадают притяжательные («мой», «наш»), указательные («этот», «тот») и определительные
местоимения-прилагательные, а сообщение называло все их притяжательными («Этот книга»); атрибута `type` не было
(`uncategorized`), хотя ошибка согласования — грамматическая. Правка меняет только текст и тип: замечания и замены
те же, корпус +0 −0. Вариант «не трогать» оставлял неточное сообщение. Принятый риск: прокси тип `grammar` от
`uncategorized` не отличает (он особо обрабатывает только `style`); как клиент LT показывает `grammar`, не проверено.

## Другие правила

- Пропуски `Unify_PADJ_NN_case`, `_gender`, `_number` («в мой саду», «налил мои чаю», «в моей лесу», «Твои пальто
  висит») — [Unify-PADJ-Propuski](Unify-PADJ-Propuski.md).
