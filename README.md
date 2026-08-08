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
```

## 동작 방식 — 상주 데몬

`kavis-agent.service`는 `Type=simple` 상주 프로세스로 동작한다 (`ps`/`pstree`/
`systemctl status`에 항상 보이고, `enable`로 부팅 시 자동 시작된다). 내부에서
자체적으로 주기를 관리한다 — 기본 1시간(`--interval 3600`)마다, ±5분 랜덤
지연(`--jitter 300`)을 두고 수집·전송을 반복한다. 예상치 못한 오류가 나도
데몬이 죽지 않고 다음 주기를 기다리며, `SIGTERM`(`systemctl stop`)을 받으면
1초 이내에 정상 종료한다.

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
