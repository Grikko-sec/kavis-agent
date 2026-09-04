# kavis-agent-windows 제거 (관리자 PowerShell로 실행)
# 예약 작업과 설치 파일만 지운다. %ProgramData%\kavis-agent\config.ini(토큰 포함)는
# 남겨둔다 — 재설치 시 다시 등록(enroll)하지 않도록.
$ErrorActionPreference = 'SilentlyContinue'
$installDir = "C:\Program Files\Kavis Agent"

if (Test-Path "$installDir\unregister-task.ps1") {
    & "$installDir\unregister-task.ps1"
}
Remove-Item -Recurse -Force $installDir

Write-Host "제거 완료. 설정 파일은 남아있습니다: $env:ProgramData\kavis-agent\config.ini" -ForegroundColor Green
Write-Host "완전히 지우려면: Remove-Item -Recurse -Force `"$env:ProgramData\kavis-agent`""
