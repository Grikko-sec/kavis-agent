# 제거 시 예약 작업만 지운다 — %ProgramData%\kavis-agent\config.ini(토큰 포함)는
# 건드리지 않는다. RPM의 %config(noreplace)와 같은 취지: 재설치/업그레이드 시 토큰 보존.
$ErrorActionPreference = 'SilentlyContinue'
Stop-ScheduledTask -TaskName 'KavisAgent' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'KavisAgent' -Confirm:$false -ErrorAction SilentlyContinue
