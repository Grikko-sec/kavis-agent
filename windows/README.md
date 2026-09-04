# kavis-agent-windows (v0.2.0)

리눅스판(`kavis-agent`)과 같은 설계 원칙: 에이전트는 판정하지 않고 원문만 수집해
서버(`/api/agent/ingest.php`)로 보낸다. Qualys 등 상용 에이전트와 같은 방식으로
**exe 하나로 배포**한다(MSI 없음). **이 리눅스 서버에서는 exe를 빌드할 수 없다**
— PyInstaller는 크로스 컴파일이 안 된다. 반드시 실제 윈도우 PC/서버에서 빌드한다.

## 범위

포함: 인벤토리(OS/하드웨어/네트워크 — 개요 탭에 바로 표시됨), 설치 소프트웨어,
핫픽스, 로컬 계정/관리자, 방화벽 프로파일 상태, 계정 정책(`net accounts`), 감사
정책(`auditpol`), RDP 설정, 리스닝 포트, 따옴표 없는 서비스 경로(전형적 권한상승
취약점) 원문 수집. v0.2.0부터 **FIM(파일 무결성 모니터링)** 추가 — 아래 참고.

아직 없음(리눅스판에서 검증 후 다음 버전에 추가 예정): 로그온 이력 기반 이상탐지,
원격 작업(방화벽 on/off, IP 차단). 계정 정책/감사 정책 등 일부 원문 항목은 서버
쪽 판정 규칙(parse_rules)이 아직 없어서 DB엔 저장되지만 체크리스트엔 안 뜬다.

**중요**: 이 폴더의 스크립트는 리눅스에서 문법만 작성한 것이라 실제 빌드로
검증하지 못했다. 진행하다 오류가 나면 **메시지를 그대로 알려달라** — 리눅스
에이전트 개발 때도 실제 서버에서 나온 오류를 보고 고친 경우가 많았다. 특히 FIM은
Windows 감사 이벤트 로그 형식이 실제 서버에서 어떻게 나오는지 아직 라이브로
확인 못 했으므로(서버 쪽 함수는 격리 테스트로만 검증됨), 처음 켤 때 가장 버그가
날 가능성이 높은 부분이다.

## FIM(파일 무결성 모니터링)

리눅스판(auditd)과 같은 원리를 Windows 감사 서브시스템으로 구현했다:

1. `auditpol /set /subcategory:{GUID} /success:enable` — 파일 시스템 개체 액세스
   감사를 켠다. 서브카테고리는 영문 이름("File System")이 아니라 로케일 무관
   고정 GUID(`{0CCE921D-69AE-11D9-BED3-505054503030}`)로 지정한다 — 실제
   한국어 Windows에서 영문 이름을 안 받아서(0x00000057 오류) GUID로 바꿈.
2. `HKLM\SYSTEM\CurrentControlSet\Control\Lsa\SCENoApplyLegacyAuditPolicy`를
   `1`로 설정한다. 이 값이 없으면 위에서 켠 세부(서브카테고리) 감사 정책을
   Windows가 무시하고 예전 방식(카테고리 단위, 기본 꺼짐)을 우선시해서 SACL을
   걸어도 이벤트가 하나도 안 남는다 — 실기 확인된 문제, Microsoft도 세부 감사
   정책 사용 시 이 값을 켜도록 공식 권장한다.
3. 서버(관리자 페이지, 자산 상세 FIM 탭)가 지정한 감시 경로마다 SACL(감사용 ACL)을
   건다 — `Everyone` 계정의 생성/삭제/내용변경/권한변경 관련 액세스를 `Success`
   기준으로 감사하도록. 이미 걸려있으면 다시 안 건다(idempotent).
4. 이후 그 경로에서 파일이 생성/삭제/수정/권한변경되면 보안 이벤트 로그에
   **4663**(개체 액세스 시도)/**4670**(권한 변경) 이벤트가 쌓인다.
5. 에이전트는 `Get-WinEvent`로 마지막 체크포인트 이후 이벤트를 가져와 원시 필드
   (`ObjectName`, `AccessMask` 16진수, 이벤트 ID, 계정명)만 그대로 서버에 보낸다.

윈도우는 리눅스(auditd)와 달리 감사를 켜면 우리가 지정 안 한 경로(윈도우 자체
서비싱 작업 등)의 이벤트도 같이 들어올 수 있어서, 서버는 설정된 감시 범위 밖
이벤트를 리눅스와 반대로 **버린다**(리눅스는 범위 밖이면 안전하게 유지).

**분류(CREATE/DELETE/CONTENT/SECURITY)는 에이전트가 아니라 서버가 한다** —
`AccessMask` 비트를 해석해서: DELETE 비트 → DELETE, WRITE_DAC/WRITE_OWNER 비트나
4670 이벤트 → SECURITY, WriteData/AppendData 비트 → CONTENT. 렌더링된 이벤트
설명 텍스트(`AccessList`)는 절대 안 쓴다 — 이 서버가 한국어 Windows라 로케일에
따라 문구가 달라지고, 로케일 의존 텍스트 파싱은 리눅스판이 `sshd-session` 정규식
사건으로 이미 겪은 함정이라 피했다.

**알려진 한계**: Windows 감사 이벤트만으론 "새 파일 생성"과 "기존 파일 수정"을
구분할 명시적 신호가 없다(리눅스 auditd의 `nametype=CREATE`에 대응하는 게 없음)
— 그래서 v0.2.0은 둘 다 CONTENT로 묶는다. DELETE/SECURITY는 정확히 구분된다.

FIM 전용 수집 주기는 `--fim-interval`(기본 180초)로 무거운 전체 수집(기본 3600초)
과 분리되어 있다 — `daemon` 서브커맨드가 내부에서 두 주기를 같이 돈다.

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

- FIM CREATE/CONTENT 미구분 — 위 "알려진 한계" 참고.
- 로그온 이력 — 보안 이벤트 로그 4624(성공)/4625(실패)가 리눅스 SSH 이력과
  대응되는 항목. 다음 버전.
- 원격 작업(Windows 방화벽 on/off, IP 차단 — `New-NetFirewallRule -Block`) — 다음 버전.
- 서버 쪽 파서(parse_rules)/전용 UI 미구현인 원문이 아직 있음 — 계정 정책(`net
  accounts`)/감사 정책(`auditpol`)은 로케일(한국어) 의존 텍스트라 실제 출력 확인
  후에 규칙을 만들 예정. 핫픽스/방화벽 프로파일/Guest 계정/서비스 경로/RDP NLA는
  이미 체크리스트(W-02~W-07)로 판정됨.
- `installed_hotfixes`만으로는 "보안" 업데이트인지, 최신인지 구분 못함(리눅스
  dnf처럼 security-only 필터가 없음) — Windows Update 오프라인 카탈로그
  (wsusscn2.cab) 기반 비교로 개선 예정.
