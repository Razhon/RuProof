# Сторонние материалы

Проект целиком распространяется по GNU LGPL 2.1 или более поздней версии (`LICENSE`). Он содержит перечисленные
ниже чужие работы или произведён от них. Их уведомления сохранены здесь и в самих файлах.

| Файлы | Происхождение | Лицензия |
|---|---|---|
| `dict/grammar.xml` | Русские правила [LanguageTool](https://languagetool.org) 6.8, © 2008–2023 Yakov Reztsov и участники LanguageTool. Исправлены и дополнены скриптом `build/py/rules.py` (пометка об этом есть в файле). | LGPL 2.1 или более поздняя |
| `dict/replace.txt` | Список замен правила `RU_SIMPLE_REPLACE` из LanguageTool (© Yakov Reztsov и другие), `build/py/rules.py` убирает из него записи, которые не просторечие (пометка есть в файле). | LGPL 2.1 или более поздняя |
| `dict/segment.srx` | Правила разбиения на предложения из LanguageTool (`languagetool-core`), `build/py/rules.py` добавляет одно правило (пометка есть в файле). | LGPL 2.1 или более поздняя |
| `dict/disambiguation.xml` | Русские правила снятия омонимии из LanguageTool (© Yakov Reztsov и другие), `build/py/rules.py` добавляет в них блоки `<unification>` из `grammar.xml` (пометка есть в файле). | LGPL 2.1 или более поздняя |
| `dict/ru_RU.dict`, `dict/ru_RU.info` | Орфографический словарь русского модуля LanguageTool; Yakov Reztsov перевёл его в формат morfologik из словарей проекта AOT (<http://www.aot.ru>, <https://github.com/sokirko74/aot>). Здесь словарь **изменён**: добавлены слова словаря Лебедева (с обязательной «ё») и словаря JetBrains `ru_RU`, е-написания слов с «ё» убраны (см. `build/README.md`, `build/py/merge.py`; пометка есть в `ru_RU.info`). | LGPL (AOT) и лицензия Лебедева далее |
| `build/data/io.txt.gz` | Список слов, развёрнутый (`unmunch`) из `ru_RU-lebedev-io.{dic,aff}` пакета `hunspell-ru-lebedev-io` ALT Linux (<https://packages.altlinux.org/ru/p10/binary/hunspell-ru-lebedev-io/noarch/>, там указана BSD-3-Clause) — словаря Александра И. Лебедева (<http://scon155.phys.msu.su/~swan/orthography.html>). | Лицензия Лебедева далее |
| `build/data/jb.txt.gz` | Список слов, развёрнутый из `ru_RU.dic`/`ru_RU.aff` репозитория <https://github.com/JetBrains/hunspell-dictionaries/tree/main/ru_RU>; это словарь Лебедева (его README содержит лицензию ниже). | Лицензия Лебедева далее |
| `build/java/*.java`, `dict/java/**/*.class` | Исходники классов LanguageTool 6.8 (`language-ru`, `languagetool-core`), © участники LanguageTool, с локальными правками (пометка в каждом файле); `build/build.sh java` компилирует их в `dict/java/`. | LGPL 2.1 или более поздняя |
| `dict/added.txt`, `dict/ignore.txt` | Начинаются с одноимённых файлов образа LanguageTool (LGPL 2.1 или более поздняя), дополнены словами из `build/words/` и `words/` (пометка есть в файлах). | LGPL 2.1 или более поздняя |

Файлы `dict/` в репозитории не хранятся: `rpdict` собирает их на каждой машине из перечисленных источников.

Не входят в репозиторий: образ LanguageTool `erikvl87/languagetool` и данные n-грамм. Их скачивают отдельно, у них
свои лицензии.

Файлы словаря Лебедева изменены: развёрнуты в простые списки слов и слиты с другими источниками, так что результат —
изменённая версия в смысле лицензии ниже.

## Лицензия словаря Лебедева

Взята из `README_ru_RU.txt` репозитория JetBrains, указанного выше. Текст лицензии приведён без изменений.

    * Copyright (c) 1997-2008, Alexander I. Lebedev

    Modifications:
    ------------------------------------------------------------------
    2012-08-24: Laszlo Nemeth (nemeth at numbertext org)
    * ru_RU.aff: add TRY line for better suggestions
      (fix fdo#35001, reported by sasha.libreoffice at gmail)


    Copyright:
    ------------------------------------------------------------------
    * Copyright (c) 1997-2008, Alexander I. Lebedev

    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions
    are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Modified versions must be clearly marked as such.
    * The name of Alexander I. Lebedev may not be used to endorse or promote
      products derived from this software without specific prior written
      permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
    AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
    IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
    ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
    LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
    CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
    SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
    INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
    CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
    ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
    POSSIBILITY OF SUCH DAMAGE.
