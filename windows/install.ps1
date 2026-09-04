# kavis-agent-windows.exe 설치/등록 스크립트 (관리자 PowerShell로 실행)
# build.ps1로 만든 dist\kavis-agent-windows.exe 를 Program Files로 복사하고,
# 부팅 시 SYSTEM 권한으로 시작 + 실패 시 자동 재시작하는 예약 작업을 등록한다.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$installDir = "C:\Program Files\Kavis Agent"
$exeSource  = "dist\kavis-agent-windows.exe"

if (-not (Test-Path $exeSource)) {
    throw "먼저 .\build.ps1 을 실행해서 $exeSource 를 만드세요."
}

Write-Host "== 설치 폴더 준비: $installDir ==" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item $exeSource "$installDir\kavis-agent-windows.exe" -Force
Copy-Item "register-task.ps1" "$installDir\register-task.ps1" -Force
Copy-Item "unregister-task.ps1" "$installDir\unregister-task.ps1" -Force

Write-Host "== 예약 작업(KavisAgent) 등록 ==" -ForegroundColor Cyan
& "$installDir\register-task.ps1"

Write-Host "`n설치 완료: $installDir" -ForegroundColor Green
Write-Host "다음 단계 (최초 1회 등록):" -ForegroundColor Yellow
Write-Host "  cd `"$installDir`""
Write-Host "  .\kavis-agent-windows.exe configure --server-url https://<서버> --enroll-key <등록키>"
Write-Host "  .\kavis-agent-windows.exe collect      # 전송 성공(200) 확인"
Write-Host "  Restart-ScheduledTask -TaskName KavisAgent"
