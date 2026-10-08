# Сборка для Windows: папка, портативный zip и установщик.
#   powershell -File packaging\build_windows.ps1 [-Version 0.1.0] [-SkipInstaller]
# Нужны: Python с зависимостями ( pip install -e ".[build]" ) и, для установщика, Inno Setup 6.
param(
    [string]$Version = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not $Version) {
    $Version = (python -c "import quickedit; print(quickedit.__version__)").Trim()
}
Write-Host "QuickEdit $Version"

python packaging\generate.py
if (-not (Test-Path build\binaries\bin\ffmpeg.exe)) {
    python packaging\fetch_binaries.py --platform windows --out build\binaries
}
$env:QUICKEDIT_BINARIES = (Resolve-Path build\binaries).Path

Remove-Item dist -Recurse -Force -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller packaging\quickedit.spec

Copy-Item LICENSE, THIRD_PARTY_NOTICES.md -Destination dist\QuickEdit

# Проверка собранной программы: Qt, Pillow, ffmpeg, ffprobe и libmpv должны находиться и загружаться
$report = Join-Path (Get-Location) "build\self-check.json"
Remove-Item $report -ErrorAction SilentlyContinue
# программа без консоли: Start-Process -Wait дожидается её и отдаёт код выхода
$check = Start-Process -FilePath "dist\QuickEdit\QuickEdit.exe" -ArgumentList "--self-check", "`"$report`"" -Wait -PassThru
if (Test-Path $report) { Get-Content $report }
if ($check.ExitCode -ne 0) { throw "самопроверка собранной программы не пройдена" }

$portable = "dist\QuickEdit-$Version-win64-portable.zip"
Compress-Archive -Path "dist\QuickEdit" -DestinationPath $portable -Force

if (-not $SkipInstaller) {
    $env:QUICKEDIT_VERSION = $Version
    $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        foreach ($candidate in @(
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
            if (Test-Path $candidate) { $iscc = $candidate; break }
        }
    }
    if (-not $iscc) { throw "Inno Setup 6 не найден (winget install JRSoftware.InnoSetup)" }
    & $iscc packaging\quickedit.iss
    if ($LASTEXITCODE -ne 0) { throw "ISCC завершился с ошибкой" }
}

Get-ChildItem dist -File | ForEach-Object {
    "{0}  {1:N1} МБ" -f $_.Name, ($_.Length / 1MB)
}
