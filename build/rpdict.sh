#!/bin/sh
# Личные слова для русского словаря (нужен только podman или docker).
# запуск: build/rpdict.sh [-s] [-i|-p] [-u] [-n] [-c] [-a файл] [слово...] | [-s] -r|-t слово... | [-s] [-i] -m [-a файл] | -b | -h
#   по умолчанию: spelling (спросит, как слово склоняется: tagged.txt или только spelling.txt), в свой слой words/
#   -s: общий слой build/words/ (в git проекта) вместо своего words/    -t: перенести слова в слой из другого
#   -i: принимается, но не предлагается (спросит, как склоняется: tagged.txt с меткой (ignore) или 0 = только ignore.txt)
#   -u: слово вне литературной нормы (разговорное, новое, жаргон): в neutral — замечание style, спросит замену; в prose — норма
#   -p prohibited.txt (отвергается, пересборка словаря ~2 мин; спросит замену для подсказки и ссылку;
#      Слово с заглавной — только заглавная в середине предложения, без пересборки; 'Слово*' — все его формы; 'фраза' — только с заменой)
#   -r: удалить слова из всех списков слоя    -m: разметить склоняемые слова, уже лежащие в spelling.txt (с -i: в ignore.txt)
#   -b: полная пересборка после нового образа (дампы словарей, merge, dict, исправления грамматики и их проверка)
#   -n: только записать файлы, без перезапуска    -c: убрать слова, которые уже есть в базовом словаре
#   -a файл: ответы на вопросы из файла (путь от корня репозитория), по строке на вопрос, пустая = Enter
#   без слов: собрать dict/ и применить списки, исправленные вручную    -h: эта справка
set -e
help() { sed -n '3,13s/^# \{0,1\}//p' "$0"; }
usage() { help >&2; exit 2; }
f=spelling; restart=1; clean=0; cmd=add; full=0; ans=; le=; ue=
while getopts sipuncrtmba:h o; do
  case $o in a) ans=$OPTARG ;; s) le="-e WORDS_LAYER=shared" ;; i) f=ignore ;; p) f=prohibited ;; u) ue="-e WORDS_NONSTD=1" ;; n) restart=0 ;; c) clean=1 ;;
    r) cmd=remove ;; t) cmd=move ;; m) cmd=migrate ;; b) full=1 ;; h) help; exit 0 ;; *) usage ;; esac
done
P=$(cd "$(dirname "$0")/.." && pwd); cd "$P"
shift $((OPTIND - 1))
[ -z "$ans" ] || [ -f "$ans" ] || { echo "нет файла ответов: $ans (путь от корня репозитория)" >&2; exit 2; }

RT=$(command -v podman || command -v docker) || { echo "нужен podman или docker" >&2; exit 1; }
LT=$(sed -n 's/^ *image: *\(.*languagetool.*\)/\1/p' compose.yaml)   # образ, на котором работает сервер: dict/ собирается из него
PY=docker.io/library/python:3.15-slim
W=build/.work
it=; [ -t 0 ] && it=-it   # для вопросов о склонении нужен терминал
ae=; [ -z "$ans" ] || ae="-e WORDS_ANSWERS=/p/$ans"   # -a: words.py читает ответы сам, без терминала (путь без пробелов)
run() { img=$1; shift
  "$RT" run --rm $it --user root --security-opt label=disable -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" $ae $le $ue \
    -v "$P:/p" -w /p --entrypoint sh "$img" /p/build/build.sh "$@"; }
[ "$(tr -d '\r' 2>/dev/null < $W/image)" = "$LT" ] || full=1   # другой образ (git pull с новым тегом): дампы устарели
[ $full = 0 ] || rm -f $W/aot.raw $W/tags.raw $W/para.pkl $W/merged.txt   # merged.txt: пересобирается ниже, до проверок слов
run "$LT" prep
echo "$LT" > $W/image
[ -s $W/merged.txt ] || run "$PY" merge   # его читают проверки слов и индекс парадигм
rc=0
case $cmd in
add) run "$PY" words $f $clean "$@" || rc=$? ;;
migrate) [ $f = ignore ] && set -- ignore; run "$PY" words migrate "$@" || rc=$? ;;   # -i -m: размечать ignore.txt
*)   run "$PY" words $cmd "$@" || rc=$? ;;
esac
[ $rc = 0 ] || [ $rc = 3 ] || exit $rc   # 3: words.py не изменил ни одного файла
run "$PY" merge   # сразу выходит, если prohibited.txt обоих слоёв и источники не менялись (merged.stamp)
if [ ! dict/ru_RU.dict -nt $W/merged.txt ]; then run "$LT" dict
elif [ $rc = 3 ] && { [ $# -gt 0 ] || [ $cmd = migrate ]; }; then echo 'без изменений: перезапуск не нужен'; exit 0   # без слов не пропускать: так применяют и правки rules.py
fi
run "$PY" rules
[ $restart = 1 ] || exit 0
"$RT" compose up -d --force-recreate
sum=$(cat dict/grammar.xml dict/segment.srx dict/replace.txt | sha256sum | cut -c1-64)
if [ $full = 1 ] || [ "$sum" != "$(tr -d '\r' < $W/grammar.checked 2>/dev/null)" ]; then   # исправления ещё не проверены: убедиться, что они ничего не портят
  "$RT" run --rm --network "container:$("$RT" compose ps -q languagetool)" -v "$P:/p" -w /p -e PYTHONDONTWRITEBYTECODE=1 "$PY" python3 build/py/rules.py check http://localhost:8010
  echo "$sum" > $W/grammar.checked
fi
