# 이 폴더(windows\)에서 실행. kavis-agent-windows.exe 하나만 만든다 (MSI 없이).
# 사전 준비물: Python 3.11+ (PATH 등록) — README.md 참고.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "== pyinstaller 설치 (이미 있으면 그대로 통과) ==" -ForegroundColor Cyan
python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 설치 실패" }

Write-Host "== exe 빌드 (PyInstaller) ==" -ForegroundColor Cyan
# pip이 설치한 pyinstaller.exe가 PATH에 없는 환경이 흔해서(Python Scripts 디렉터리 미등록),
# PATH와 무관하게 항상 동작하는 'python -m PyInstaller' 형태로 실행한다.
python -m PyInstaller --onefile --console --name kavis-agent-windows kavis-agent-windows.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 빌드 실패" }

Write-Host "`n완료: $(Resolve-Path dist\kavis-agent-windows.exe)" -ForegroundColor Green
Write-Host "다음: install.ps1 을 관리자 권한으로 실행하면 설치+등록까지 됩니다." -ForegroundColor Yellow
