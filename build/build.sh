#!/bin/sh
# Выполняется ВНУТРИ контейнера (см. rpdict.sh / rpdict.ps1). Монтирование: корень проекта -> /p, рабочий каталог /p.
# запуск: build.sh prep|merge|dict|words|rules АРГУМЕНТЫ...   (prep, dict: образ LanguageTool; merge, words, rules: образ python)
set -e
export PYTHONDONTWRITEBYTECODE=1   # bind mount: __pycache__ не пишем в проект
W=/p/build/.work; OUT=/p/dict; LTR=/LanguageTool/org/languagetool/resource/ru/hunspell
mkdir -p "$W" "$OUT" /p/words   # words/: свой слой слов (в .gitignore)
# вернуть файлы пользователю хоста (Linux), даже если шаг упал; на Windows UID/GID не заданы
trap '[ -z "$HOST_UID" ] || chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$W" "$OUT" /p/build/words /p/words' EXIT
case "$1" in
prep)  # из образа: словари speller и теггера (дампы в koi8-r) и файлы, которые мы дополняем или правим
  # shortcut: дампы кешируются; после нового образа запустите rpdict -b (он их удаляет, словари могли измениться)
  [ -s "$W/aot.raw" ] || java -cp "/LanguageTool/libs/*" morfologik.tools.Launcher fsa_decompile -i "$LTR/ru_RU.dict" -o "$W/aot.raw"
  [ -s "$W/tags.raw" ] || java -cp "/LanguageTool/libs/*" morfologik.tools.Launcher dict_decompile -i "$LTR/../russian.dict" -o "$W/tags.raw"
  cp /LanguageTool/org/languagetool/rules/ru/grammar.xml "$W/grammar.orig.xml"
  cp /LanguageTool/org/languagetool/rules/ru/replace.txt "$W/replace.orig.txt"
  unzip -p /LanguageTool/libs/languagetool-core.jar org/languagetool/resource/segment.srx > "$W/segment.orig.srx"
  cp "$LTR/ignore.txt" "$W/ignore.orig.txt"
  cp "$LTR/../added.txt" "$W/added.orig.txt" ;;
merge) python3 /p/build/py/merge.py "$W" ;;
words) shift; python3 /p/build/py/forms.py >/dev/null; python3 /p/build/py/words.py "$@" ;;   # forms.py: только его самопроверка
rules) python3 /p/build/py/rules.py apply ;;
dict)   # собрать в $W, затем перенести: неудачная сборка не должна оставить серверу сломанный dict/
  { printf '%s\n' \
    "# Изменено в $(date +%Y) году, Razhon (build/py/merge.py, build/build.sh): в словарь ниже добавлены слова словаря Лебедева" \
    '# (ё обязательна) и словаря JetBrains ru_RU, е-написания слов с ё убраны.' \
    '# Лицензия словаря Лебедева и другие источники: THIRD_PARTY.md. Распространяется по GNU LGPL 2.1 или более поздней.'
    sed 's/koi8-r/utf-8/' "$LTR/ru_RU.info"; } > "$W/ru_RU.info"
  java -Xmx4g -cp "/LanguageTool/languagetool.jar:/LanguageTool/libs/*" org.languagetool.tools.SpellDictionaryBuilder \
    -i "$W/merged.txt" -info "$W/ru_RU.info" -freq "$W/freq.xml" -o "$W/ru_RU.dict"
  mv "$W/ru_RU.dict" "$W/ru_RU.info" "$OUT/" ;;
*) echo "запуск: build.sh prep|merge|dict|words|rules АРГУМЕНТЫ..." >&2; exit 2 ;;
esac
