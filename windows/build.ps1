# 이 폴더(windows\)에서 실행. kavis-agent-windows.exe 하나만 만든다 (MSI 없이).
# 사전 준비물: Python 3.11+ (PATH 등록) — README.md 참고.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "== 실제 Python 인터프리터 찾기 ==" -ForegroundColor Cyan
# Windows에는 Microsoft Store용 가짜 실행 별칭(WindowsApps\python.exe, 실제로 열 수 없는
# 빈 스텁 파일)이 PATH에 같이 잡혀있는 경우가 흔하다 — 이게 먼저 걸리면 pyinstaller가
# 내부적으로 그걸 열려다 "Invalid argument" 오류로 죽는다. WindowsApps 경로는 걸러내고
# 진짜 설치된 Python만 쓴다.
$pythonCmd = Get-Command python -All -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1
if (-not $pythonCmd) {
    throw "실제 Python 설치를 찾지 못했습니다 (Microsoft Store 실행 별칭만 감지됨) — https://python.org/downloads 에서 설치 후 다시 시도하세요."
}
$python = $pythonCmd.Source
Write-Host "사용할 Python: $python" -ForegroundColor DarkGray

Write-Host "== pyinstaller 설치 (이미 있으면 그대로 통과) ==" -ForegroundColor Cyan
& $python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 설치 실패" }

Write-Host "== exe 빌드 (PyInstaller) ==" -ForegroundColor Cyan
& $python -m PyInstaller --onefile --console --name kavis-agent-windows kavis-agent-windows.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 빌드 실패" }

Write-Host "`n완료: $(Resolve-Path dist\kavis-agent-windows.exe)" -ForegroundColor Green
Write-Host "다음: install.ps1 을 관리자 권한으로 실행하면 설치+등록까지 됩니다." -ForegroundColor Yellow
