Name:           kavis-agent
Version:        0.6.3
Release:        1%{?dist}
Summary:        Vulnerability check platform collection agent
License:        Proprietary
BuildArch:      noarch

Source0:        kavis-agent
Source1:        config.ini.sample
Source2:        kavis-agent.service

Requires:       python3
Requires:       iproute
Requires(post): systemd
Requires(preun): systemd
Requires(postun): systemd
# FIM(config.ini [fim] watch_dirs)을 쓸 때만 필요 — 없어도 설치·나머지 기능은 정상 동작(FIM만 스스로 건너뜀).
Recommends:     audit

%description
사내 취약점 점검 통합 플랫폼용 수집 에이전트.
sshd_config, 설치 패키지 목록, dnf 보안 업데이트 목록, 리스닝 포트 등 원문만
수집해 플랫폼 API로 전송한다. 취약 여부 판정은 서버(parse_rules)에서 수행하므로
판정 기준이 바뀌어도 에이전트 재배포가 필요 없다. 상주 데몬으로 동작하며
내부에서 자체 주기(기본 1시간)를 돌린다. [fim] watch_dirs를 설정하면 auditd
기반으로 지정 디렉토리의 생성/삭제/내용변경/권한변경도 감지한다.

%install
rm -rf %{buildroot}
install -Dm0750 %{SOURCE0} %{buildroot}/usr/local/bin/kavis-agent
install -Dm0640 %{SOURCE1} %{buildroot}%{_sysconfdir}/kavis-agent/config.ini
install -Dm0644 %{SOURCE2} %{buildroot}%{_unitdir}/kavis-agent.service

%files
%attr(0750,root,root) /usr/local/bin/kavis-agent
%dir %attr(0750,root,root) %{_sysconfdir}/kavis-agent
%config(noreplace) %attr(0640,root,root) %{_sysconfdir}/kavis-agent/config.ini
%{_unitdir}/kavis-agent.service

%post
# 0.4.x 이하(timer 기반)에서 업그레이드하는 경우, 옛 timer가 활성 상태로 남지 않도록 정리한다.
systemctl disable --now kavis-agent.timer >/dev/null 2>&1 || :
%systemd_post kavis-agent.service
cat <<'EOF'

==============================================================
 kavis-agent가 설치되었습니다. (0.5.0부터 상주 데몬 방식으로 동작합니다)

 수동 설정:
   1) vi /etc/kavis-agent/config.ini  (server_url / enroll_key 또는 token)
   2) systemctl enable --now kavis-agent.service
   3) journalctl -u kavis-agent.service -f

 또는 비대화형 한 줄로:
   kavis-agent configure --server-url https://<서버> --enroll-key <키>
   systemctl enable --now kavis-agent.service
==============================================================
EOF

%preun
%systemd_preun kavis-agent.service

%postun
%systemd_postun_with_restart kavis-agent.service

%changelog
* Mon Aug 17 2026 kavis-platform <admin@security.hyunni.com> - 0.6.3-1
- FIM을 무거운 전체 수집(패키지/dnf/포트/인벤토리, --interval 기본 1시간)에서 분리해 별도
  주기(--fim-interval, 기본 180초)로 확인·전송하도록 데몬 루프를 이중 스케줄러로 재작성.
  Qualys FIM 등 상용 제품의 폴링 주기(수 분 단위)에 맞춘 것으로, 완전 실시간(inotify)은
  아니지만 무거운 스캔을 자주 돌리지 않고도 파일 변경을 몇 분 내로 반영한다.
  새 이벤트가 없는 주기는 아예 전송하지 않는다.
* Mon Aug 17 2026 kavis-platform <admin@security.hyunni.com> - 0.6.2-1
- 버그 수정: FIM 이벤트 조회 시 ausearch -ts에 날짜/시간을 "MM/DD/YYYY HH:MM:SS" 한 문자열로
  넘겨서 매번 "Hour, Minute, and Second are required" 오류로 조용히 실패하던 문제 수정 —
  실서버에서 커널은 이벤트를 정상 캡처했는데 에이전트가 계속 못 가져오던 원인이었음.
  날짜와 시간을 별개의 인자 두 개로 분리해서 넘기도록 수정.
- ProtectHome=true → read-only로 완화: watch_dirs에 /home 하위 경로를 지정해도 데몬이
  존재 여부를 확인하고 감시할 수 있도록 함 (true였을 때는 /home이 통째로 안 보여서
  실제로 존재하는 디렉토리도 "없다"고 건너뛰던 문제가 있었음). 쓰기는 여전히 막혀있음.
* Mon Aug 17 2026 kavis-platform <admin@security.hyunni.com> - 0.6.1-1
- 버그 수정: 'kavis-agent configure'가 config.ini를 통째로 새로 써서, 수동으로 추가해둔
  [fim] 등 다른 섹션이 재실행 시 날아가던 문제 수정. 이제 [agent] 섹션만 갱신하고
  나머지 섹션은 그대로 보존한다.
* Mon Aug 17 2026 kavis-platform <admin@security.hyunni.com> - 0.6.0-1
- FIM(파일 무결성 모니터링) 추가: config.ini [fim] watch_dirs에 디렉토리를 지정하면
  auditd(커널 감사 서브시스템)로 생성/삭제/내용변경/권한(소유자·모드)변경을 감지
- 에이전트는 auditctl 워치 규칙만 걸어두고, 그 사이 쌓인 이벤트 원문(ausearch -i)만
  서버로 넘김 — 판정(카테고리 분류)은 기존 원칙대로 서버(ingest.php)가 수행
- 체크포인트 파일로 마지막 조회 시점 이후 이벤트만 가져오며, 전송 성공 시에만 커밋
  (전송 실패 시 다음 주기가 같은 구간을 다시 조회 — 이벤트 유실 방지)
- auditd 미설치 서버에서는 FIM만 자동으로 건너뛰고 나머지 수집은 영향 없음
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.5.0-1
- timer+oneshot 방식에서 상주 데몬(Type=simple) 방식으로 전환 — ps/pstree/systemctl status에서 항상 프로세스 확인 가능
- 'kavis-agent daemon' 서브커맨드 추가 (내부에서 자체 주기 관리, SIGTERM 시 1초 내 정상 종료)
- 업그레이드 시 0.4.x 이하의 옛 timer를 자동으로 정리
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.4.1-1
- 버그 수정: ProtectSystem=full이 /etc를 읽기전용으로 막아서 자동등록 토큰이 config.ini에 저장되지 못하던 문제 수정
  (ReadWritePaths=/etc/kavis-agent 예외 추가). 저장 실패를 성공으로 잘못 로그하던 문제도 함께 수정.
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.4.0-1
- 계정/인증 관련 KISA 수집 항목 추가: passwd, shadow_perm(권한만), login_defs, pwquality_conf, cron_config
- 자산 인벤토리 수집 추가 (식별/OS/하드웨어/네트워크) — 판정 아닌 사실 데이터, /api/agent/ingest.php가 asset_inventory 테이블에 저장
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.3.0-1
- 'kavis-agent configure' 서브커맨드 추가 (비대화형 config.ini 작성, 프로비저닝 자동화용)
- install.sh 원라이너 설치 스크립트 추가
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.2.2-1
- 서비스 유닛에 Nice=15, IOSchedulingClass=idle, CPUQuota=25%%, MemoryMax=256M 추가 (운영 서비스와 자원 경합 방지)
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.2.1-1
- 수집 주기 daily -> hourly 로 변경 (RandomizedDelaySec도 1800 -> 300으로 조정)
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.2.0-1
- 자동 등록(enroll_key) 지원: 공용 등록 키로 최초 실행 시 자산 자동 생성 + 전용 토큰 발급 후 로컬 저장
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.1.0-1
- Initial release: sshd_config, os-release, packages, listening ports, dnf security updates 수집
