#!/bin/sh
# Выполняется ВНУТРИ контейнера (см. rpdict.sh / rpdict.ps1). Монтирование: корень проекта -> /p, рабочий каталог /p.
# запуск: build.sh prep|merge|dict|java|words|rules АРГУМЕНТЫ...   (prep, dict, java: образ LanguageTool; merge, words, rules: образ python)
set -e
export PYTHONDONTWRITEBYTECODE=1   # bind mount: __pycache__ не пишем в проект
W=/p/build/.work; OUT=/p/dict; LTR=/LanguageTool/org/languagetool/resource/ru/hunspell
mkdir -p "$W" "$OUT" /p/words   # words/: свой слой слов (в .gitignore)
# вернуть файлы пользователю хоста (Linux), даже если шаг упал; на Windows UID/GID не заданы
trap '[ -z "$HOST_UID" ] || chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$W" "$OUT" /p/build/words /p/words' EXIT
case "$1" in
prep)  # из образа: словари speller и теггера (дампы в koi8-r) и файлы, которые мы дополняем или правим
  # shortcut: дампы и копии кешируются; после нового образа запустите rpdict -b (он их удаляет, словари могли измениться)
  rm -f "$W/prep.ok"   # метка удачного prep: без неё rpdict не пропустит шаг, даже если копии остались от упавшего запуска
  if [ ! -s "$W/aot.raw" ] || [ ! -s "$W/tags.raw" ]; then echo "выгружаю словари из образа LanguageTool (один раз после нового образа, ~1 мин)..."; fi
  [ -s "$W/aot.raw" ] || java -cp "/LanguageTool/libs/*" morfologik.tools.Launcher fsa_decompile -i "$LTR/ru_RU.dict" -o "$W/aot.raw"
  [ -s "$W/tags.raw" ] || java -cp "/LanguageTool/libs/*" morfologik.tools.Launcher dict_decompile -i "$LTR/../russian.dict" -o "$W/tags.raw"
  cp /LanguageTool/org/languagetool/rules/ru/grammar.xml "$W/grammar.orig.xml"
  cp /LanguageTool/org/languagetool/rules/ru/replace.txt "$W/replace.orig.txt"
  cp /LanguageTool/org/languagetool/resource/ru/disambiguation.xml "$W/disambiguation.orig.xml"
  unzip -p /LanguageTool/libs/languagetool-core.jar org/languagetool/resource/segment.srx > "$W/segment.orig.srx"
  cp "$LTR/ignore.txt" "$W/ignore.orig.txt"
  cp "$LTR/../added.txt" "$W/added.orig.txt"
  touch "$W/prep.ok" ;;
merge) python3 /p/build/py/merge.py "$W" ;;
words) shift; python3 /p/build/py/forms.py >/dev/null; python3 /p/build/py/words.py "$@" ;;   # forms.py: только его самопроверка
rules) python3 /p/build/py/rules.py apply ;;
java)  # Java-правки LT: build/java/*.java -> dict/java/<пакет>/*.class (в JRE образа есть модуль jdk.compiler)
  set -- /p/build/java/*.java
  [ -f "$1" ] || exit 0   # правок нет
  [ -f "$W/java.stamp" ] && [ -z "$(find /p/build/java -name '*.java' -newer "$W/java.stamp")" ] && exit 0
  bad=0; core=/LanguageTool/libs/languagetool-core.jar
  for f; do   # класс образа должен совпасть с тем, с которого снята правка (хеш в строке «// образ: sha256 …»)
    pkg=$(sed -n 's/^package \([A-Za-z0-9_.]*\);.*/\1/p' "$f" | head -n 1)
    rel=$(echo "$pkg" | tr . /)/$(basename "$f" .java).class
    want=$(sed -n 's|^// образ: sha256 \([0-9a-f]\{64\}\) .*|\1|p' "$f" | head -n 1)
    if [ -f "/LanguageTool/$rel" ]; then have=$(sha256sum "/LanguageTool/$rel" | cut -c1-64)   # классы ru-модуля лежат файлами
    elif unzip -l "$core" "$rel" 2>/dev/null | grep -qF "$rel"; then have=$(unzip -p "$core" "$rel" | sha256sum | cut -c1-64)   # unzip -l (busybox) выходит с 0 и без файла: ищем имя в списке
    else have=; fi   # новый класс: хеш не нужен
    if [ -z "$pkg" ]; then echo "FAIL $f: нет строки package" >&2; bad=1
    elif [ -n "$have" ] && [ -z "$want" ]; then echo "FAIL $f: нет строки «// образ: sha256 $have /LanguageTool/$rel»" >&2; bad=1
    elif [ "$have" != "$want" ] && [ -n "$have" ]; then echo "FAIL $f: класс в образе изменился, сверьте правку с новым исходником" >&2; bad=1
    fi
  done
  [ $bad = 0 ] || exit 1
  rm -rf "$W/java"
  echo "компилирую Java-правки..."
  java -m jdk.compiler/com.sun.tools.javac.Main -encoding UTF-8 -nowarn -proc:none \
    -cp "/LanguageTool:/LanguageTool/languagetool.jar:/LanguageTool/libs/*" -d "$W/java" "$@"
  cd "$W/java"   # переносим по одному: сервер не увидит наполовину записанный класс
  find . -name '*.class' | while read -r c; do mkdir -p "$OUT/java/${c%/*}"; mv -f "$c" "$OUT/java/$c"; done
  touch "$W/java.stamp"
  echo "java: правок $#" ;;
dict)   # собрать в $W, затем перенести: неудачная сборка не должна оставить серверу сломанный dict/
  echo "собираю орфографический словарь ru_RU.dict (до минуты)..."
  { printf '%s\n' \
    "# Изменено в $(date +%Y) году, Razhon (build/py/merge.py, build/build.sh): в словарь ниже добавлены слова словаря Лебедева" \
    '# (ё обязательна) и словаря JetBrains ru_RU, е-написания слов с ё убраны.' \
    '# Лицензия словаря Лебедева и другие источники: THIRD_PARTY.md. Распространяется по GNU LGPL 2.1 или более поздней.'
    sed 's/koi8-r/utf-8/' "$LTR/ru_RU.info"; } > "$W/ru_RU.info"
  java -Xmx4g -cp "/LanguageTool/languagetool.jar:/LanguageTool/libs/*" org.languagetool.tools.SpellDictionaryBuilder \
    -i "$W/merged.txt" -info "$W/ru_RU.info" -freq "$W/freq.xml" -o "$W/ru_RU.dict"
  mv "$W/ru_RU.dict" "$W/ru_RU.info" "$OUT/" ;;
*) echo "запуск: build.sh prep|merge|dict|java|words|rules АРГУМЕНТЫ..." >&2; exit 2 ;;
esac
