Name:           kavis-agent
Version:        0.5.0
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

%description
사내 취약점 점검 통합 플랫폼용 수집 에이전트.
sshd_config, 설치 패키지 목록, dnf 보안 업데이트 목록 등 원문만 수집해
플랫폼 API로 전송한다. 취약 여부 판정은 서버(parse_rules)에서 수행하므로
판정 기준이 바뀌어도 에이전트 재배포가 필요 없다. 상주 데몬으로 동작하며
내부에서 자체 주기(기본 1시간)를 돌린다.

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
