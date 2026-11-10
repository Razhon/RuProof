#!/bin/sh
# Обновить проект, синхронизировать свой слой слов words/ (если это git-репозиторий), собрать dict/ и пересоздать контейнеры.
# С адресом пустого приватного репозитория делает words/ git-репозиторием и отправляет туда слова;
# с адресом репозитория, где слова уже есть, клонирует его в words/ (words/ должен быть пуст).
# Синхронизация: свои изменения в words/ коммитятся, затем pull --rebase и push.
# запуск: update.sh [адрес-репозитория-слов]
set -e
usage() { echo "запуск: update.sh [адрес-репозитория-слов]" >&2; exit 2; }
[ $# -le 1 ] || usage
cd "$(dirname "$0")"
if [ $# = 1 ]; then
  [ ! -d words/.git ] || { echo "words/ уже git-репозиторий" >&2; exit 2; }
  rc=0; git ls-remote --exit-code --heads "$1" main >/dev/null || rc=$?
  if [ $rc = 0 ]; then
    [ -z "$(ls -A words 2>/dev/null)" ] || { echo "в репозитории уже есть слова, а words/ не пуст: перенесите слова вручную" >&2; exit 1; }
    rm -rf words
    git clone "$1" words
  elif [ $rc = 2 ]; then   # репозиторий пуст: слова этой машины станут первыми
    mkdir -p words
    git -C words init -b main
    git -C words remote add origin "$1"
  else
    exit $rc
  fi
fi
git pull --ff-only
if [ -d words/.git ]; then
  git -C words add -A
  git -C words diff --cached --quiet || git -C words commit -m слова
  rc=0; git -C words ls-remote --exit-code --heads origin main >/dev/null || rc=$?
  if [ $rc = 0 ]; then git -C words pull --rebase origin main; elif [ $rc != 2 ]; then exit $rc; fi
  ! git -C words rev-parse -q --verify HEAD >/dev/null || git -C words push -u origin HEAD:main   # без коммитов слать нечего
fi
q=; git diff --quiet HEAD -- build/py/rules.py build/java && q=-q   # rules.py или Java-правки правили здесь: исправления не проверены, -q не давать
exec build/rpdict.sh $q   # без слов: собирает dict/ на этой машине и заканчивает compose up; -q: без проверки правил (это дело автора, он зовёт rpdict сам)
