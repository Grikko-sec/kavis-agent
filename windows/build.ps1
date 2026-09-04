# 이 폴더(windows\)에서 실행. exe 빌드 -> MSI 패키징까지 한 번에 처리한다.
# 사전 준비물: Python 3.11+ (PATH 등록), .NET 8 SDK — README.md 참고.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "== 1) pyinstaller 설치 확인 ==" -ForegroundColor Cyan
pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    pip install pyinstaller
}

Write-Host "== 2) exe 빌드 (PyInstaller) ==" -ForegroundColor Cyan
pyinstaller --onefile --console --name kavis-agent-windows kavis-agent-windows.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 빌드 실패" }

Write-Host "== 3) wix 도구 설치 확인 ==" -ForegroundColor Cyan
$wixInstalled = dotnet tool list --global | Select-String '^wix\s'
if (-not $wixInstalled) {
    dotnet tool install --global wix --version 5.0.2
}

Write-Host "== 4) MSI 빌드 (WiX) ==" -ForegroundColor Cyan
wix build kavis-agent.wxs -o kavis-agent-windows-installer.msi
if ($LASTEXITCODE -ne 0) { throw "wix build 실패" }

Write-Host "`n완료: $(Resolve-Path kavis-agent-windows-installer.msi)" -ForegroundColor Green
