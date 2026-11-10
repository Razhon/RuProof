# Все проверки перед коммитом: самопроверки модулей, ruff и pyright (стиль и типы), rules.py check (против LT),
# regress.py (против прокси).
# Поднимает контейнеры (compose up -d, без пересоздания). Полный вывод шага — в build\.work\check-ШАГ.log,
# на экран — итог шага и строки FAIL (хвост лога, если упало без них). Обычно ~1 мин, шаг обрывается через 5 мин.
# Код выхода 1, если упал хоть один шаг.
# запуск: tools\check.ps1 [selfcheck] [ruff] [pyright] [rules] [regress]      без аргументов: все по порядку
param([Parameter(ValueFromRemainingArguments)][string[]]$Steps)
$all = @('selfcheck', 'ruff', 'pyright', 'rules', 'regress')
if ($Steps | Where-Object { $all -notcontains $_ }) { Write-Host 'запуск: tools\check.ps1 [selfcheck] [ruff] [pyright] [rules] [regress]'; exit 2 }
if (-not $Steps) { $Steps = $all }
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$rt = (Get-Command podman, docker -ErrorAction SilentlyContinue | Select-Object -First 1).Name
if (-not $rt) { Write-Error "нужен podman или docker"; exit 1 }
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false   # вывод контейнера в UTF-8
$py = 'docker.io/library/python:3.15-slim'
# ruff и pyright — из своих образов (на хосте только podman); кеш npm — в .work, чтобы pyright не качался каждый раз
$ruff = 'ghcr.io/astral-sh/ruff:0.17.0-alpine'; $node = 'docker.io/library/node:22.11.0-slim'; $pyright = 'pyright@1.1.414'
$work = Join-Path $root 'build\.work'
New-Item -ItemType Directory -Force $work | Out-Null
if ($Steps -contains 'rules' -or $Steps -contains 'regress') {   # LT стартует ~30 с, пока идут самопроверки
  $up = & $rt compose up -d 2>&1 | ForEach-Object { "$_" }
  if ($LASTEXITCODE) { $up; Write-Host 'контейнеры не поднялись (dict\ собран? build\rpdict.ps1)'; exit 1 }
}
$bad = 0
foreach ($s in $Steps) {
  $net = @(); $img = $py; $cmd = 'sh tools/selfcheck.sh'
  if ($s -eq 'ruff') { $img = $ruff; $cmd = 'ruff check . && ruff format --check .' }
  if ($s -eq 'pyright') { $img = $node; $cmd = "npx --yes $pyright" }
  if ($s -eq 'rules') { $net = @('--network', "container:$(& $rt compose ps -q languagetool 2>$null)"); $cmd = 'python3 build/py/rules.py check http://localhost:8010' }
  if ($s -eq 'regress') { $net = @('--network', "container:$(& $rt compose ps -q proxy 2>$null)"); $cmd = 'python3 proxy/regress.py http://localhost:8080' }
  $log = Join-Path $work "check-$s.log"
  $t = [Diagnostics.Stopwatch]::StartNew()
  $out = @(& $rt run --rm @net -v "${root}:/p" -w /p -e PYTHONDONTWRITEBYTECODE=1 -e npm_config_cache=/p/build/.work/npm $img sh -c "timeout 300 sh -c '$cmd' 2>&1" 2>&1 | ForEach-Object { "$_" })
  $rc = $LASTEXITCODE
  [IO.File]::WriteAllLines($log, [string[]]$out)   # UTF-8 без BOM
  $dt = [int]$t.Elapsed.TotalSeconds
  if ($rc -eq 0) { Write-Host "${s}: OK ($dt с)"; continue }
  $bad = 1
  $why = if ($rc -eq 124) { 'оборван через 5 мин' } else { "код $rc" }
  Write-Host "${s}: FAIL ($why, $dt с), лог: $log"
  $fails = @($out | Where-Object { $_ -like 'FAIL*' })
  if ($fails -and -not ($out -match 'Traceback')) { $fails } else { $out | Select-Object -Last 15 }   # упал Python: строки FAIL — в хвосте
}
exit $bad
