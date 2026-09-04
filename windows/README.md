# kavis-agent-windows (v0.1.0 — 첫 버전)

리눅스판(`kavis-agent`)과 같은 설계 원칙: 에이전트는 판정하지 않고 원문만 수집해
서버(`/api/agent/ingest.php`)로 보낸다. **이 리눅스 서버에서는 exe/MSI를 빌드할 수
없다** — PyInstaller는 크로스 컴파일이 안 되고, MSI 빌드 도구(WiX)도 리눅스에서는
"동작 미정의"라 실제로 깨진다(테스트 완료). 반드시 실제 윈도우 PC/서버에서 빌드한다.

## v0.1.0 범위

포함: 인벤토리(OS/하드웨어/네트워크 — 개요 탭에 바로 표시됨), 설치 소프트웨어,
핫픽스, 로컬 계정/관리자, 방화벽 프로파일 상태, 계정 정책(`net accounts`), 감사
정책(`auditpol`), RDP 설정, 리스닝 포트, 따옴표 없는 서비스 경로(전형적 권한상승
취약점) 원문 수집.

아직 없음(리눅스판에서 검증 후 다음 버전에 추가 예정): FIM, 로그온 이력 기반
이상탐지, 원격 작업(방화벽 on/off, IP 차단). 서버 쪽에도 이 원문들을 해석할
KISA류 판정 규칙(parse_rules)이 아직 없어서, 지금 보내는 원문 항목들은 DB에
저장은 되지만 화면/체크리스트에는 아직 안 뜬다 — exe/MSI 파이프라인이 실제로
동작하는지 먼저 확인한 뒤에 서버 쪽을 이어서 붙일 계획이다.

**중요**: 이 폴더의 `.wxs`/`.ps1`은 리눅스에서 문법만 작성한 것이라 실제 빌드로
검증하지 못했다. 아래 절차대로 진행하다 오류가 나면(특히 `wix build` 단계)
**오류 메시지를 그대로 알려달라** — 리눅스 에이전트 개발 때도 실제 서버에서 나온
오류를 보고 고친 경우가 많았다(예: FIM 타임스탬프 인자 버그, sshd-session 정규식
버그). 이번에도 같은 방식으로 갈 가능성이 높다.

## 사전 준비물 (윈도우 PC/서버에)

1. **Python 3.11+** — https://python.org/downloads
   설치 시 **"Add python.exe to PATH"** 체크
2. **.NET 8 SDK** — https://dotnet.microsoft.com/download
   (MSI 빌드 도구 WiX가 이 위에서 동작)

## 빌드

이 `windows/` 폴더 전체를 윈도우로 옮긴 뒤(git clone 또는 파일 복사), PowerShell을
**관리자 권한**으로 열고:

```powershell
cd C:\경로\windows
.\build.ps1
```

`build.ps1`이 하는 일:
1. `pip install pyinstaller` (없으면)
2. `pyinstaller --onefile --console --name kavis-agent-windows kavis-agent-windows.py`
   → `dist\kavis-agent-windows.exe` 생성
3. `dotnet tool install --global wix --version 5.0.2` (없으면)
4. `wix build kavis-agent.wxs -o kavis-agent-windows-installer.msi`
   → 같은 폴더에 설치 파일 생성

완료되면 `kavis-agent-windows-installer.msi` 하나가 나온다 — 이게 RPM 파일에
해당하는 배포 단위다.

## 설치

```powershell
msiexec /i kavis-agent-windows-installer.msi /quiet
```

(`/quiet` 빼면 설치 마법사가 뜬다.) 설치되는 것:
- `C:\Program Files\Kavis Agent\kavis-agent-windows.exe`
- 예약 작업 `KavisAgent` (부팅 시 SYSTEM 권한으로 시작, 죽으면 1분 뒤 재시작 — 최대
  999회. systemd의 `Restart=always`에 대응)

설치 직후엔 아직 `server_url`/토큰이 없어서 예약 작업이 실행돼도 바로 실패한다 —
다음 단계로 등록해야 한다.

## 등록 (최초 1회)

관리자 PowerShell에서:

```powershell
cd "C:\Program Files\Kavis Agent"
.\kavis-agent-windows.exe configure --server-url https://<서버> --enroll-key <관리자 페이지에서 발급한 등록 키>
```

그리고 실제로 잘 되는지 **수동으로 한 번 먼저 확인**(예약 작업 로그는 따로 안
남으므로, 문제가 있으면 이 단계에서 바로 보인다):

```powershell
.\kavis-agent-windows.exe collect
```

`전송 성공 (200): ...` 이 보이면 정상. Kavis 웹의 자산 목록에 새 자산(호스트명)이
자동 등록되어 있을 것이다. 이후 예약 작업을 재시작해 상시 수집을 시작:

```powershell
Restart-ScheduledTask -TaskName KavisAgent
# 또는: Stop-ScheduledTask -TaskName KavisAgent; Start-ScheduledTask -TaskName KavisAgent
```

## 상태 확인

```powershell
Get-ScheduledTask -TaskName KavisAgent | Get-ScheduledTaskInfo
```

`LastTaskResult`가 `0`이면 정상. 예약 작업은 콘솔 창 없이 백그라운드로 도는
`daemon` 모드라 표준출력이 어디에도 안 남는다 — 뭔가 이상하면 일단
`.\kavis-agent-windows.exe collect`를 수동으로 돌려서 직접 눈으로 확인하는 게 가장 빠르다.

## 업그레이드

새 버전 MSI를 그냥 다시 `msiexec /i`로 설치하면 된다 — `UpgradeCode`가 고정돼
있어서 기존 설치를 자동으로 지우고 새 파일로 교체한다(RPM 업그레이드와 같은
방식). `%ProgramData%\kavis-agent\config.ini`(토큰 포함)는 MSI 패키지에 포함된
파일이 아니라서 그대로 보존된다.

## 제거

```powershell
msiexec /x kavis-agent-windows-installer.msi /quiet
```

예약 작업과 설치 파일만 지운다. `%ProgramData%\kavis-agent\config.ini`는 남는다 —
완전히 지우려면 그 폴더를 수동으로 삭제.

## 알려진 제약 / TODO

- FIM(파일 무결성 모니터링) — Windows는 auditpol(Object Access 감사) + SACL +
  보안 이벤트 로그(4663) 조합으로 리눅스 auditd와 비슷하게 만들 수 있지만, 다음
  버전으로 미룸.
- 로그온 이력 — 보안 이벤트 로그 4624(성공)/4625(실패)가 리눅스 SSH 이력과
  대응되는 항목. 다음 버전.
- 원격 작업(Windows 방화벽 on/off, IP 차단 — `New-NetFirewallRule -Block`) — 다음 버전.
- 서버 쪽 파서(parse_rules)/전용 UI 미구현 — 지금 보내는 원문(핫픽스, 로컬 계정,
  감사 정책 등)은 DB에는 쌓이지만 체크리스트 판정/화면 표시는 아직 안 됨.
- `installed_hotfixes`만으로는 "보안" 업데이트인지 구분 못함(리눅스 dnf처럼
  security-only 필터가 없음) — Windows Update Agent COM API로 미설치 보안 패치
  목록을 뽑을 수는 있지만 호출이 느려서(수십 초~수 분) 매 수집 주기에 넣기엔
  부담스러워 별도 설계가 필요.
