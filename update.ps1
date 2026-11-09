# Обновить проект, синхронизировать свой слой слов words/ (если это git-репозиторий), собрать dict/ и пересоздать контейнеры.
# С адресом пустого приватного репозитория делает words/ git-репозиторием и отправляет туда слова;
# с адресом репозитория, где слова уже есть, клонирует его в words/ (words/ должен быть пуст).
# Синхронизация: свои изменения в words/ коммитятся, затем pull --rebase и push.
# запуск: update.ps1 [адрес-репозитория-слов]
if ($args.Count -gt 1) { Write-Error 'запуск: update.ps1 [адрес-репозитория-слов]'; exit 2 }
Set-Location $PSScriptRoot
$words = Join-Path $PSScriptRoot 'words'
if ($args.Count -eq 1) {
  $url = $args[0]
  if (Test-Path (Join-Path $words '.git')) { Write-Error 'words/ уже git-репозиторий'; exit 2 }
  git ls-remote --exit-code --heads $url main | Out-Null
  $rc = $LASTEXITCODE
  if ($rc -eq 0) {
    if (Get-ChildItem $words -Force -ErrorAction SilentlyContinue) {
      Write-Error 'в репозитории уже есть слова, а words/ не пуст: перенесите слова вручную'; exit 1
    }
    if (Test-Path $words) { Remove-Item $words -Recurse -Force }
    git clone $url words
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
  } elseif ($rc -eq 2) {   # репозиторий пуст: слова этой машины станут первыми
    New-Item -ItemType Directory -Force $words | Out-Null
    git -C words init -b main
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    git -C words remote add origin $url
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
  } else { exit $rc }
}
git pull --ff-only
if ($LASTEXITCODE) { exit $LASTEXITCODE }
if (Test-Path (Join-Path $words '.git')) {
  git -C words add -A
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  git -C words diff --cached --quiet
  if ($LASTEXITCODE) {
    git -C words commit -m слова
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
  }
  git -C words ls-remote --exit-code --heads origin main | Out-Null
  $rc = $LASTEXITCODE
  if ($rc -eq 0) {
    git -C words pull --rebase origin main
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
  } elseif ($rc -ne 2) { exit $rc }
  git -C words rev-parse -q --verify HEAD | Out-Null
  if (-not $LASTEXITCODE) {   # без коммитов слать нечего
    git -C words push -u origin HEAD:main
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
  }
}
git diff --quiet HEAD -- build/py/rules.py
$q = $LASTEXITCODE -eq 0   # rules.py правили здесь: исправления не проверены, -q не давать
& (Join-Path $PSScriptRoot 'build\rpdict.ps1') -q:$q   # без слов: собирает dict/ на этой машине и заканчивает compose up; -q: без проверки правил (это дело автора, он зовёт rpdict сам)
exit $LASTEXITCODE
