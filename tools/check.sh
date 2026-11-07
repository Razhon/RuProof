#!/bin/sh
# Все проверки перед коммитом: самопроверки модулей, ruff и pyright (стиль и типы), rules.py check (против LT),
# regress.py (против прокси).
# Поднимает контейнеры (compose up -d, без пересоздания). Полный вывод шага — в build/.work/check-ШАГ.log,
# на экран — итог шага и строки FAIL (хвост лога, если упало без них). Обычно ~1–1,5 мин, шаг обрывается через 5 мин.
# Код выхода 1, если упал хоть один шаг.
# запуск: tools/check.sh [selfcheck] [ruff] [pyright] [rules] [regress]      без аргументов: все по порядку
set -e
usage() { echo "запуск: tools/check.sh [selfcheck] [ruff] [pyright] [rules] [regress]" >&2; exit 2; }
for s in "$@"; do case $s in selfcheck|ruff|pyright|rules|regress) ;; *) usage ;; esac; done
[ $# -gt 0 ] || set -- selfcheck ruff pyright rules regress
P=$(cd "$(dirname "$0")/.." && pwd); cd "$P"
RT=$(command -v podman || command -v docker) || { echo "нужен podman или docker" >&2; exit 1; }
PY=docker.io/library/python:3.15-slim
# ruff и pyright — из своих образов (на хосте только podman); кеш npm — в .work, чтобы pyright не качался каждый раз
RUFF=ghcr.io/astral-sh/ruff:0.17.0-alpine NODE=docker.io/library/node:22.11.0-slim PYRIGHT=pyright@1.1.414
W=build/.work; mkdir -p $W
case " $* " in *" rules "* | *" regress "*)   # LT стартует ~30 с, пока идут самопроверки
  "$RT" compose up -d > $W/check-up.log 2>&1 ||
    { cat $W/check-up.log >&2; echo "контейнеры не поднялись (dict/ собран? build/rpdict.sh)" >&2; exit 1; } ;;
esac
bad=0
for s in "$@"; do
  case $s in
  selfcheck) net=; img=$PY; cmd="sh tools/selfcheck.sh" ;;
  ruff) net=; img=$RUFF; cmd="ruff check . && ruff format --check ." ;;
  pyright) net=; img=$NODE; cmd="npx --yes $PYRIGHT" ;;
  rules) net="--network container:$("$RT" compose ps -q languagetool 2>/dev/null)"; img=$PY; cmd="python3 build/py/rules.py check http://localhost:8010" ;;
  regress) net="--network container:$("$RT" compose ps -q proxy 2>/dev/null)"; img=$PY; cmd="python3 proxy/regress.py http://localhost:8080" ;;
  esac
  log=$W/check-$s.log; t=$(date +%s); rc=0
  "$RT" run --rm $net -v "$P:/p" -w /p -e PYTHONDONTWRITEBYTECODE=1 -e npm_config_cache=/p/$W/npm "$img" sh -c "timeout 300 sh -c '$cmd' 2>&1" > $log 2>&1 || rc=$?
  dt=$(( $(date +%s) - t ))
  if [ $rc = 0 ]; then echo "$s: OK ($dt с)"; continue; fi
  bad=1
  if [ $rc = 124 ]; then why="оборван через 5 мин"; else why="код $rc"; fi
  echo "$s: FAIL ($why, $dt с), лог: $log"
  if grep -q '^FAIL' $log && ! grep -q Traceback $log; then grep '^FAIL' $log; else tail -n 15 $log; fi   # упал Python: строки FAIL — в хвосте
done
exit $bad
