# 부팅 시 SYSTEM 권한으로 시작하고, 죽으면 자동 재시작하는 예약 작업을 등록한다.
# systemd의 Type=simple + Restart=always 에 대응하는 역할.
$ErrorActionPreference = 'Stop'
$exePath = Join-Path $PSScriptRoot 'kavis-agent-windows.exe'

$action    = New-ScheduledTaskAction -Execute $exePath -Argument 'daemon'
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Unregister-ScheduledTask -TaskName 'KavisAgent' -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'KavisAgent' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'KavisAgent'
