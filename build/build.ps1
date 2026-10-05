<#
    Сборка EXE: PyInstaller + проверка результата.

        .\build\build.ps1              # один файл: dist\PsycoAsk-<версия>.exe
        .\build\build.ps1 -AsFolder    # каталог dist\PsycoAsk-<версия>\ (быстрый старт)
        .\build\build.ps1 -Clean       # очистить рабочие файлы сборки и dist\

По умолчанию собирается один самодостаточный файл: его достаточно скопировать
в любое место и запустить, никакие каталоги рядом не нужны.

Перед сборкой ставит зависимости, если их не хватает: в окружении .venv
должны быть и requirements.txt, и requirements-build.txt.
#>

[CmdletBinding()]
param(
    [switch]$AsFolder,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
# Иначе любой INFO-вывод PyInstaller/pip в stderr обрывал бы сборку
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

Write-Host "==> Проверка зависимостей" -ForegroundColor Cyan
& $Python -m pip install -q -r requirements.txt
& $Python -m pip install -q -r requirements-build.txt

if ($Clean) {
    # build.ps1 и psycoask.spec лежат в build\, поэтому папку целиком удалять
    # нельзя: чистим только рабочие каталоги PyInstaller и dist\.
    Write-Host "==> Очистка рабочих файлов сборки" -ForegroundColor Cyan
    foreach ($folder in @("build", "dist")) {
        $path = Join-Path $Root $folder
        if (-not (Test-Path -LiteralPath $path)) { continue }
        Get-ChildItem -LiteralPath $path -Force | Where-Object {
            $_.Name -ne "build.ps1" -and $_.Extension -ne ".spec"
        } | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
    }
}

# Версия приложения — из app/__init__.py, чтобы имя файла совпадало
# с версией, которую показывает само приложение.
$VersionLine = Select-String -Path (Join-Path $Root "app\__init__.py") -Pattern 'APP_VERSION = "([^"]+)"'
$Version = $VersionLine.Matches[0].Groups[1].Value
$ExeName = "PsycoAsk-$Version"

$common = @(
    "--noconfirm"
    "--name", $ExeName
    "--windowed"
    "--icon", "assets\icon.ico"
    "--add-data", "frontend;frontend"
    "--add-data", "scripts;scripts"
    "--add-data", "data\input\MEMpreset.json;data/input"
    "--collect-all", "pywebview"
    "--paths", "scripts"
    "--exclude-module", "tkinter"
)
foreach ($module in @("paths", "txt_to_qa", "xlsx_to_json", "prepare_qa", "generate_data",
                      "json_to_xlsx", "visualize_to_excel", "visualize_to_excel_bars",
                      "compare_presets")) {
    $common += @("--hidden-import", $module)
}

if ($AsFolder) {
    Write-Host "==> Сборка каталогом (быстрый старт)" -ForegroundColor Cyan
    & $Python -m PyInstaller @common --onedir main.py
    $target = "dist\$ExeName\$ExeName.exe"
}
else {
    # Один файл собирается по спецификации — единому источнику настроек:
    # её hiddenimports и datas не разойдутся с CLI-флагами.
    Write-Host "==> Сборка одного файла (автономный)" -ForegroundColor Cyan
    & $Python -m PyInstaller --noconfirm "build\psycoask.spec"
    $target = "dist\$ExeName.exe"
}

if ($LASTEXITCODE -ne 0) {
    throw "Сборка не удалась, код $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $target)) {
    throw "Файл не найден после сборки: $target"
}

$size = [math]::Round((Get-Item -LiteralPath $target).Length / 1MB, 1)
Write-Host ""
Write-Host "✅ Готово: $target ($size МБ)" -ForegroundColor Green
Write-Host "   Достаточно скопировать этот файл — больше ничего не нужно."
Write-Host "   Рабочая папка данных: %LOCALAPPDATA%\PsycoAsk"