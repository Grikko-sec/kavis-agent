# kavis-agent

Kavis(사내 취약점 점검 통합 플랫폼)용 수집 에이전트. RHEL/Rocky Linux 9 계열 서버에 RPM으로 설치한다.

## 설계 원칙

에이전트는 판정을 하지 않는다. `sshd_config`, `os-release`, 설치 패키지 목록,
`dnf updateinfo list security --installed` 결과 등 **원문만 수집해서** 플랫폼의
`/api/agent/ingest.php`로 전송한다. 취약 여부 판정(KISA 점검항목 매칭, dnf 보안
업데이트 파싱)은 전부 서버 쪽에서 이루어지므로, 판정 기준이 바뀌어도 에이전트를
재배포할 필요가 없다.

## 설치

### 한 줄 설치 (권장)

```bash
curl -fsSL https://raw.githubusercontent.com/Grikko-sec/kavis-agent/main/install.sh \
  | sudo bash -s -- --server-url https://kavis.example.com --enroll-key <등록키>
```

OS를 감지해 최신 릴리스에서 맞는 RPM을 받아 설치하고, `config.ini`를 비대화형으로
작성한 뒤 `kavis-agent.service`까지 활성화한다. Ansible/cloud-init 등 자동화에도 그대로 쓸 수 있다.

### 수동 설치

```bash
sudo dnf install -y kavis-agent-<version>-1.el9.noarch.rpm
sudo kavis-agent configure --server-url https://kavis.example.com --enroll-key <등록키>
# 또는 vi /etc/kavis-agent/config.ini 로 직접 편집
sudo systemctl enable --now kavis-agent.service
```

## 설정 (`/etc/kavis-agent/config.ini`)

둘 중 하나만 채우면 된다.

- **자동 등록**: 관리자 페이지(에이전트 자동 등록)에서 발급받은 공용 `enroll_key`를
  채우고 `token`은 비워둔다. 최초 실행 시 호스트명으로 자산이 자동 생성되고,
  발급받은 전용 토큰이 `token`에 자동 저장된다. 이후 실행부터는 그 토큰만 쓰인다.
- **수동 발급**: 자산 상세 페이지에서 그 자산 전용으로 직접 발급받은 `token`을 채운다.

```ini
[agent]
server_url = https://kavis.example.com
enroll_key =
token =
verify_tls = true
timeout = 20

[fim]
watch_dirs =
```

### FIM(파일 무결성 모니터링, 선택)

`auditd`(커널 감사 서브시스템)로 지정된 디렉토리의 생성·삭제·내용변경·
권한(소유자·모드)변경을 감지한다. 에이전트는 판정하지 않는다는 원칙 그대로 —
auditd 워치 규칙만 걸어두고, 수집 주기마다 그 사이 쌓인 이벤트 원문
(`ausearch -k kavis_fim -i`)만 서버로 넘기면 서버(`ingest.php`)가
CREATE/DELETE/CONTENT/SECURITY로 분류해 저장한다.

**감시 경로는 관리자 페이지(자산 상세 > FIM 감시 경로 설정)에서 지정하는 게 기본
방식이다.** 경로별로 depth(1~3)도 같이 지정하는데, 이건 auditd 감시 범위를 제한하는
게 아니라(`-w`는 애초에 깊이 제한이 불가능해 하위 전체를 항상 다 봄) 저장 단계에서
그보다 깊은 이벤트를 걸러내는 노이즈 필터다. 에이전트는 매 전송의 `ingest.php` 응답에
실려오는 `fim_watch_dirs`를 로컬(`/etc/kavis-agent/.fim_watch_dirs.json`)에 캐시해
다음 사이클부터 반영한다 — 새 인증 엔드포인트 없이 기존 왕복에 얹은 것이다.

`config.ini`의 `[fim] watch_dirs`는 서버에 아직 한 번도 연결하지 못한 최초
부트스트랩 구간에서만 쓰이는 폴백이다. 서버가 한 번이라도 응답하면(빈 목록이어도)
그 값이 우선이며 로컬 설정은 더 이상 참조하지 않는다.

**CONTENT 이벤트는 SHA-256 해시로 한 번 더 검증한다** (Qualys FIM류 상용 제품과 같은
원리). auditd는 "write 계열 시스템콜이 발생했다"만 알려줄 뿐, 에디터가 열었다 그대로
저장하는 것처럼 실제로는 내용이 안 바뀐 경우도 이벤트로 잡힌다. 에이전트가 이벤트에
등장한 경로들의 현재 SHA-256을 계산해 `fim_hashes`로 같이 보내면, 서버가 직전 값과
비교해 판정한다 — 처음 보는 파일은 베이스라인만 세우고, 해시가 그대로면 오탐으로 보고
저장하지 않으며, 실제로 다르면 "변경 확인됨"으로 표시한다. 판정은 여전히 서버가 한다.

```ini
[fim]
watch_dirs = /etc/nginx, /var/www/html/config
```

`auditd`가 설치돼 있지 않으면(`dnf install audit`) FIM만 자동으로 건너뛰고 나머지
수집(패키지, 포트, dnf 보안 업데이트 등)은 그대로 동작한다.

## 동작 방식 — 상주 데몬

`kavis-agent.service`는 `Type=simple` 상주 프로세스로 동작한다 (`ps`/`pstree`/
`systemctl status`에 항상 보이고, `enable`로 부팅 시 자동 시작된다). 내부에서
자체적으로 두 가지 주기를 따로 관리한다.

- **전체 수집**(패키지/dnf 보안 업데이트/포트/인벤토리 등, 무거움): 기본 1시간
  (`--interval 3600`)마다, ±5분 랜덤 지연(`--jitter 300`)을 두고 반복.
- **FIM 이벤트만**: 기본 3분(`--fim-interval 180`)마다 별도로 확인·전송. 무거운
  전체 수집과 분리해뒀기 때문에, FIM 반영 지연을 줄이려고 전체 주기를 통째로
  줄일 필요가 없다(Qualys FIM 등 상용 제품의 폴링 주기와 비슷한 수준 — 완전
  실시간은 아니지만 근접한 지연). 새 이벤트가 없으면 아예 전송하지 않는다.

예상치 못한 오류가 나도 데몬이 죽지 않고 다음 주기를 기다리며,
`SIGTERM`(`systemctl stop`)을 받으면 1초 이내에 정상 종료한다.

```bash
systemctl status kavis-agent.service   # active (running) 이어야 정상
journalctl -u kavis-agent.service -f   # 실시간 로그
```

수동 1회 테스트만 하고 싶으면 `sudo kavis-agent run` (상주하지 않고 1회 실행 후 종료).

## 자원 제한

운영 서비스와 자원을 경합하지 않도록 서비스 유닛에 `Nice=15`,
`IOSchedulingClass=idle`, `CPUQuota=25%`, `MemoryMax=256M`이 설정되어 있다.

## RPM 빌드 (RHEL/Rocky/CentOS/Alma 9)

```bash
rpmbuild --define "_topdir $(pwd)/rpmbuild" --define "_sourcedir $(pwd)/el9/SOURCES" -bb el9/SPECS/kavis-agent.spec
```

## 디렉터리 구조

OS 계열별로 폴더를 분리해뒀다 — 다른 배포판(el8, debian 등) 지원은 같은 패턴으로 폴더만 추가하면 된다.

```
el9/
  SOURCES/   에이전트 스크립트, systemd 유닛, 설정 샘플
  SPECS/     RPM spec 파일
install.sh   원라이너 설치 스크립트 (OS 감지 → 최신 릴리스 다운로드 → 설치 → 설정 → 활성화)
```
