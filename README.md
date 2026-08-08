# kavis-agent

Kavis(사내 취약점 점검 통합 플랫폼)용 수집 에이전트. RHEL/Rocky Linux 9 계열 서버에 RPM으로 설치한다.

## 설계 원칙

에이전트는 판정을 하지 않는다. `sshd_config`, `os-release`, 설치 패키지 목록,
`dnf updateinfo list security --installed` 결과 등 **원문만 수집해서** 플랫폼의
`/api/agent/ingest.php`로 전송한다. 취약 여부 판정(KISA 점검항목 매칭, dnf 보안
업데이트 파싱)은 전부 서버 쪽에서 이루어지므로, 판정 기준이 바뀌어도 에이전트를
재배포할 필요가 없다.

## 설치

```bash
sudo dnf install -y kavis-agent-<version>-1.el9.noarch.rpm
sudo vi /etc/kavis-agent/config.ini
sudo systemctl enable --now kavis-agent.timer
```

## 설정 (`/etc/kavis-agent/config.ini`)

둘 중 하나만 채우면 된다.

- **자동 등록**: 관리자 페이지(에이전트 자동 등록)에서 발급받은 공용 `enroll_key`를
  채우고 `token`은 비워둔다. 최초 실행 시 호스트명으로 자산이 자동 생성되고,
  발급받은 전용 토큰이 `token`에 자동 저장된다. 이후 실행부터는 그 토큰만 쓰인다.
- **수동 발급**: 자산 상세 페이지에서 그 자산 전용으로 직접 발급받은 `token`을 채운다.

```ini
[agent]
server_url = https://security.hyunni.com
enroll_key =
token =
verify_tls = true
timeout = 20
```

## 수집 주기

`kavis-agent.timer` — 매시간(`OnCalendar=hourly`), ±5분 랜덤 지연(`RandomizedDelaySec=300`).

## 자원 제한

운영 서비스와 자원을 경합하지 않도록 서비스 유닛에 `Nice=15`,
`IOSchedulingClass=idle`, `CPUQuota=25%`, `MemoryMax=256M`이 설정되어 있다.

## RPM 빌드

```bash
rpmbuild --define "_topdir $(pwd)/rpmbuild" --define "_sourcedir $(pwd)/SOURCES" -bb SPECS/kavis-agent.spec
```

## 디렉터리 구조

```
SOURCES/   에이전트 스크립트, systemd 유닛, 설정 샘플
SPECS/     RPM spec 파일
```
