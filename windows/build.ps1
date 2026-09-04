# 이 폴더(windows\)에서 실행. kavis-agent-windows.exe 하나만 만든다 (MSI 없이).
# 사전 준비물: Python 3.11+ (PATH 등록) — README.md 참고.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "== pyinstaller 설치 확인 ==" -ForegroundColor Cyan
pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    pip install pyinstaller
}

Write-Host "== exe 빌드 (PyInstaller) ==" -ForegroundColor Cyan
pyinstaller --onefile --console --name kavis-agent-windows kavis-agent-windows.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 빌드 실패" }

Write-Host "`n완료: $(Resolve-Path dist\kavis-agent-windows.exe)" -ForegroundColor Green
Write-Host "다음: install.ps1 을 관리자 권한으로 실행하면 설치+등록까지 됩니다." -ForegroundColor Yellow
