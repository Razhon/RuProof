#!/bin/sh
# Самопроверки всех модулей Python (assert'ы в __main__, сервер не нужен). Запускается внутри python:3.15-slim:
# в CI (.github/workflows/check.yml) и из tools/check.sh / check.ps1. Модуль с самопроверкой добавляется сюда.
# Печатает только упавшие модули (FAIL и хвост вывода), код выхода 1, если упал хоть один.
# запуск: sh tools/selfcheck.sh
set -e
[ $# = 0 ] || { echo "запуск: sh tools/selfcheck.sh" >&2; exit 2; }
cd "$(dirname "$0")/.."
export SELFCHECK=1 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
bad=0
out=$(mktemp)
for f in proxy/proxy.py proxy/regress.py build/py/store.py build/py/dialog.py build/py/words.py build/py/forms.py build/py/merge.py build/py/rules.py tools/count_errors.py; do
  python "$f" > "$out" 2>&1 || { echo "FAIL $f"; tail -n 15 "$out"; bad=1; }
done
rm -f "$out"
exit $bad
