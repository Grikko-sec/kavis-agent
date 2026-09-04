# kavis-agent-windows (v0.1.0 — 첫 버전)

리눅스판(`kavis-agent`)과 같은 설계 원칙: 에이전트는 판정하지 않고 원문만 수집해
서버(`/api/agent/ingest.php`)로 보낸다. Qualys 등 상용 에이전트와 같은 방식으로
**exe 하나로 배포**한다(MSI 없음). **이 리눅스 서버에서는 exe를 빌드할 수 없다**
— PyInstaller는 크로스 컴파일이 안 된다. 반드시 실제 윈도우 PC/서버에서 빌드한다.

## v0.1.0 범위

포함: 인벤토리(OS/하드웨어/네트워크 — 개요 탭에 바로 표시됨), 설치 소프트웨어,
핫픽스, 로컬 계정/관리자, 방화벽 프로파일 상태, 계정 정책(`net accounts`), 감사
정책(`auditpol`), RDP 설정, 리스닝 포트, 따옴표 없는 서비스 경로(전형적 권한상승
취약점) 원문 수집.

아직 없음(리눅스판에서 검증 후 다음 버전에 추가 예정): FIM, 로그온 이력 기반
이상탐지, 원격 작업(방화벽 on/off, IP 차단). 서버 쪽에도 이 원문들을 해석할
KISA류 판정 규칙(parse_rules)이 아직 없어서, 지금 보내는 원문 항목들은 DB에
저장은 되지만 화면/체크리스트에는 아직 안 뜬다.

**중요**: 이 폴더의 스크립트는 리눅스에서 문법만 작성한 것이라 실제 빌드로
검증하지 못했다. 진행하다 오류가 나면 **메시지를 그대로 알려달라** — 리눅스
에이전트 개발 때도 실제 서버에서 나온 오류를 보고 고친 경우가 많았다.

## 사전 준비물 (윈도우 PC/서버에)

**Python 3.11 이상만 있으면 된다.**
- https://python.org/downloads
- 설치 시 **"Add python.exe to PATH"** 체크

## 빌드

이 `windows/` 폴더 전체를 윈도우로 옮긴 뒤(git clone 또는 파일 복사), PowerShell을
**관리자 권한**으로 열고:

```powershell
cd C:\경로\windows
.\build.ps1
```

`pip install pyinstaller`(없으면) → `pyinstaller --onefile` 로
`dist\kavis-agent-windows.exe` 하나를 만든다.

## 설치 + 등록

```powershell
.\install.ps1
```

하는 일:
- `dist\kavis-agent-windows.exe`를 `C:\Program Files\Kavis Agent\`로 복사
- 예약 작업 `KavisAgent` 등록 (부팅 시 SYSTEM 권한으로 시작, 죽으면 1분 뒤
  재시작 — 최대 999회. systemd의 `Restart=always`에 대응)

설치 직후엔 아직 `server_url`/토큰이 없어서 예약 작업이 실행돼도 바로 실패한다 —
이어서 등록해야 한다(최초 1회):

```powershell
cd "C:\Program Files\Kavis Agent"
.\kavis-agent-windows.exe configure --server-url https://<서버> --enroll-key <관리자 페이지에서 발급한 등록 키>
.\kavis-agent-windows.exe collect
```

`전송 성공 (200): ...` 이 보이면 정상 — 수동 실행이라 결과가 바로 눈에 보인다.
Kavis 웹의 자산 목록에 새 자산(호스트명)이 자동 등록되어 있을 것이다. 이후
예약 작업을 재시작해 상시 수집을 시작:

```powershell
Restart-ScheduledTask -TaskName KavisAgent
```

## 상태 확인

```powershell
Get-ScheduledTask -TaskName KavisAgent | Get-ScheduledTaskInfo
```

`LastTaskResult`가 `0`이면 정상. 예약 작업은 콘솔 창 없이 백그라운드로 도는
`daemon` 모드라 표준출력이 어디에도 안 남는다 — 뭔가 이상하면 일단
`.\kavis-agent-windows.exe collect`를 수동으로 돌려서 직접 눈으로 확인하는 게 가장 빠르다.

## 업그레이드

새 `kavis-agent-windows.exe`를 빌드한 뒤 `.\install.ps1`을 다시 실행하면 된다 —
기존 파일을 덮어쓰고 예약 작업을 재등록한다. `%ProgramData%\kavis-agent\config.ini`
(토큰 포함)는 install.ps1이 건드리지 않는 위치라 그대로 보존된다.

## 제거

```powershell
.\uninstall.ps1
```

예약 작업과 설치 파일만 지운다. `%ProgramData%\kavis-agent\config.ini`는 남는다 —
완전히 지우려면 `uninstall.ps1`이 알려주는 명령을 추가로 실행.

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
