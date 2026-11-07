# Личные слова для русского словаря (нужен только podman или docker).
# запуск: build\rpdict.ps1 [-s] [-i | -p] [-u] [-n] [-c] [-a файл] [слово...] | [-s] -r|-t слово... | [-s] [-i] -m [-a файл] | -b | -h
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
param([switch]$s, [switch]$i, [switch]$p, [switch]$u, [switch]$n, [switch]$c, [switch]$r, [switch]$t, [switch]$m, [switch]$b, [switch]$h, [string]$a,
      [Parameter(Position = 0, ValueFromRemainingArguments)][string[]]$Words)   # Position: иначе первое слово уходит в -a
if ($h -or ($Words -like '-*')) {   # справка; неизвестный флаг не должен попасть в словарь как слово
  Get-Content -Encoding UTF8 $PSCommandPath -TotalCount 12 | Select-Object -Skip 1 | ForEach-Object { $_ -replace '^# ?', '' }
  exit $(if ($h) { 0 } else { 2 })
}
$root = Split-Path $PSScriptRoot -Parent
if ($a -and -not (Test-Path -PathType Leaf (Join-Path $root $a))) { Write-Error "нет файла ответов: $a (путь от корня репозитория)"; exit 2 }
$rt = (Get-Command podman, docker -ErrorAction SilentlyContinue | Select-Object -First 1).Name
if (-not $rt) { Write-Error "нужен podman или docker"; exit 1 }
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false   # вывод контейнера в UTF-8
[Console]::InputEncoding = New-Object Text.UTF8Encoding $false    # ответы вводятся по-русски
$lt = (Select-String -Path (Join-Path $root 'compose.yaml') -Pattern '^\s*image:\s*(\S*languagetool\S*)').Matches[0].Groups[1].Value   # образ, на котором работает сервер: dict/ собирается из него
$py = 'docker.io/library/python:3.15-slim'
$work = Join-Path $root 'build\.work'
$it = @(if (-not [Console]::IsInputRedirected) { '-it' })   # для вопросов о склонении нужен терминал
$ae = @(if ($a) { '-e', "WORDS_ANSWERS=/p/$($a -replace '\\', '/')" })   # -a: words.py читает ответы сам, без терминала
$le = @(if ($s) { '-e', 'WORDS_LAYER=shared' })   # -s: общий слой build/words/
$ue = @(if ($u) { '-e', 'WORDS_NONSTD=1' })   # -u: пометить слова вне нормы
function Run($img, [string[]]$step, [int[]]$ok = @(0)) {
  & $rt run --rm @it @ae @le @ue --user root --security-opt label=disable -v "${root}:/p" -w /p --entrypoint sh $img /p/build/build.sh @step
  if ($ok -notcontains $LASTEXITCODE) { exit $LASTEXITCODE }
}
$imgf = Join-Path $work 'image'
if (-not (Test-Path $imgf) -or (Get-Content $imgf) -ne $lt) { $b = $true }   # другой образ (git pull с новым тегом): дампы устарели
if ($b) { Remove-Item -ErrorAction SilentlyContinue (Join-Path $work 'aot.raw'), (Join-Path $work 'tags.raw'), (Join-Path $work 'para.pkl'), (Join-Path $work 'merged.txt') }   # merged.txt: пересобирается ниже, до проверок слов
Run $lt @('prep')
Set-Content $imgf $lt
if (-not (Test-Path (Join-Path $work 'merged.txt'))) { Run $py @('merge') }   # его читают проверки слов и индекс парадигм
$f = if ($i) { 'ignore' } elseif ($p) { 'prohibited' } else { 'spelling' }
$step = if ($r) { @('words', 'remove') } elseif ($t) { @('words', 'move') } elseif ($m) { @('words', 'migrate') + @(if ($i) { 'ignore' }) } else { @('words', $f, $(if ($c) { '1' } else { '0' })) }
if ($Words) { $step += $Words }
Run $py $step @(0, 3)
$same = $LASTEXITCODE -eq 3   # words.py: ни один файл не изменился
Run $py @('merge')   # сразу выходит, если prohibited.txt обоих слоёв и источники не менялись (merged.stamp)
$dictf = Join-Path $root 'dict\ru_RU.dict'
if (-not (Test-Path $dictf) -or (Get-Item $dictf).LastWriteTime -le (Get-Item (Join-Path $work 'merged.txt')).LastWriteTime) { Run $lt @('dict') }
elseif ($same -and ($Words -or $m)) { Write-Host 'без изменений: перезапуск не нужен'; exit 0 }   # без слов не пропускать: так применяют и правки rules.py
$grammar = Join-Path $root 'dict\grammar.xml'
$stamp = Join-Path $work 'grammar.checked'
Run $py @('rules')
if ($n) { exit 0 }
Set-Location $root
& $rt compose up -d --force-recreate
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$sum = ((Get-FileHash $grammar).Hash + (Get-FileHash (Join-Path $root 'dict\segment.srx')).Hash + (Get-FileHash (Join-Path $root 'dict\replace.txt')).Hash).ToLower()   # изменился любой из них: проверить снова
if ($b -or -not (Test-Path $stamp) -or $sum -ne (Get-Content $stamp)) {   # исправления ещё не проверены: убедиться, что они ничего не портят
  $id = & $rt compose ps -q languagetool
  & $rt run --rm --network "container:$id" -v "${root}:/p" -w /p -e PYTHONDONTWRITEBYTECODE=1 $py python3 build/py/rules.py check http://localhost:8010
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  Set-Content $stamp $sum
}
exit 0
