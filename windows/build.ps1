# Builds the JARVIS Windows installer. Run from the repository root, on Windows:
#   powershell -ExecutionPolicy Bypass -File windows\build.ps1 -Version 1.0.0
# Needs: Python 3.12 (this interpreter's dependencies are copied into the
# bundle), Node 20+, and Inno Setup 6 (iscc on PATH or in Program Files).
param(
    [string]$Version = "0.0.0",
    [string]$EmbedPython = "3.12.8"
)
$ErrorActionPreference = "Stop"
$root  = (Resolve-Path "$PSScriptRoot\..").Path
$build = Join-Path $root "build"
$stage = Join-Path $build "stage"
Remove-Item -Recurse -Force $build -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$stage\python", "$stage\app" | Out-Null

function Step($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Run($exe, [string[]]$a) { & $exe @a; if ($LASTEXITCODE -ne 0) { throw "$exe failed ($LASTEXITCODE)" } }

Step "Frontend"
Push-Location "$root\frontend"
Run npm @("ci")
Run npm @("run", "build")
Pop-Location

Step "Embeddable Python $EmbedPython"
$zip = Join-Path $build "python-embed.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$EmbedPython/python-$EmbedPython-embed-amd64.zip" -OutFile $zip
Expand-Archive $zip "$stage\python" -Force
$pth = Get-ChildItem "$stage\python\python*._pth" | Select-Object -First 1
# Search path: the stdlib zip, the interpreter dir, site-packages, and the app.
$stdlib = (Get-ChildItem "$stage\python\python*.zip" | Select-Object -First 1).Name
@($stdlib, ".", "Lib\site-packages", "..\app", "import site") | Set-Content -Encoding ascii $pth.FullName

Step "Python dependencies"
Run python @("-m", "pip", "install", "--no-warn-script-location", "--only-binary=:all:",
             "--target", "$stage\python\Lib\site-packages",
             "-r", "$root\requirements.txt")
# pytest is a development dependency listed in requirements.txt; the product
# does not need it at runtime.
foreach ($dev in "pytest", "_pytest", "pytest_asyncio", "iniconfig", "pluggy") {
    Get-ChildItem "$stage\python\Lib\site-packages" -Filter "$dev*" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force
}

Step "Application files"
$items = "*.py", "requirements.txt", ".env.example", "LICENSE", "jarvis_home", "migrations", "skills", "data"
foreach ($i in $items) {
    Get-ChildItem -Path $root -Filter $i -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item $_.FullName "$stage\app" -Recurse -Force
    }
}
New-Item -ItemType Directory -Force "$stage\app\frontend" | Out-Null
Copy-Item "$root\frontend\dist" "$stage\app\frontend\dist" -Recurse -Force

Step "Launcher (JARVIS.exe)"
Run python @("-m", "pip", "install", "pyinstaller")
Run python @("-m", "PyInstaller", "--noconfirm", "--onefile", "--noconsole",
             "--name", "JARVIS", "--icon", "$root\windows\jarvis.ico",
             "--distpath", "$build\launcher", "--workpath", "$build\pyi", "--specpath", "$build\pyi",
             "$root\windows\launcher.py")
Copy-Item "$build\launcher\JARVIS.exe" "$stage\JARVIS.exe"

Step "Installer"
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) { throw "Inno Setup 6 not found (choco install innosetup)" }
Run $iscc @("/DAppVersion=$Version", "$root\windows\jarvis.iss")

Get-ChildItem "$build\out" | ForEach-Object { Write-Host "Built: $($_.FullName) ($([math]::Round($_.Length/1MB,1)) MB)" }
