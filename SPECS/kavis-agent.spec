Name:           kavis-agent
Version:        0.2.2
Release:        1%{?dist}
Summary:        Vulnerability check platform collection agent
License:        Proprietary
BuildArch:      noarch

Source0:        kavis-agent
Source1:        config.ini.sample
Source2:        kavis-agent.service
Source3:        kavis-agent.timer

Requires:       python3
Requires:       iproute
Requires(post): systemd
Requires(preun): systemd
Requires(postun): systemd

%description
사내 취약점 점검 통합 플랫폼용 수집 에이전트.
sshd_config, 설치 패키지 목록, dnf 보안 업데이트 목록 등 원문만 수집해
플랫폼 API로 전송한다. 취약 여부 판정은 서버(parse_rules)에서 수행하므로
판정 기준이 바뀌어도 에이전트 재배포가 필요 없다.

%install
rm -rf %{buildroot}
install -Dm0750 %{SOURCE0} %{buildroot}/usr/local/bin/kavis-agent
install -Dm0640 %{SOURCE1} %{buildroot}%{_sysconfdir}/kavis-agent/config.ini
install -Dm0644 %{SOURCE2} %{buildroot}%{_unitdir}/kavis-agent.service
install -Dm0644 %{SOURCE3} %{buildroot}%{_unitdir}/kavis-agent.timer

%files
%attr(0750,root,root) /usr/local/bin/kavis-agent
%dir %attr(0750,root,root) %{_sysconfdir}/kavis-agent
%config(noreplace) %attr(0640,root,root) %{_sysconfdir}/kavis-agent/config.ini
%{_unitdir}/kavis-agent.service
%{_unitdir}/kavis-agent.timer

%post
%systemd_post kavis-agent.timer
cat <<'EOF'

==============================================================
 kavis-agent가 설치되었습니다.

 1) /etc/kavis-agent/config.ini 를 열어 server_url / token 을 입력하세요.
    (플랫폼 관리자 페이지 > 자산 상세 > 에이전트 연동 에서 토큰 발급)
 2) 설정 후 다음 명령으로 활성화하세요:
      systemctl enable --now kavis-agent.timer
 3) 즉시 1회 테스트 실행:
      systemctl start kavis-agent.service
      journalctl -u kavis-agent.service -n 50
==============================================================
EOF

%preun
%systemd_preun kavis-agent.timer kavis-agent.service

%postun
%systemd_postun_with_restart kavis-agent.timer

%changelog
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.2.2-1
- 서비스 유닛에 Nice=15, IOSchedulingClass=idle, CPUQuota=25%%, MemoryMax=256M 추가 (운영 서비스와 자원 경합 방지)
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.2.1-1
- 수집 주기 daily -> hourly 로 변경 (RandomizedDelaySec도 1800 -> 300으로 조정)
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.2.0-1
- 자동 등록(enroll_key) 지원: 공용 등록 키로 최초 실행 시 자산 자동 생성 + 전용 토큰 발급 후 로컬 저장
* Sat Aug 08 2026 kavis-platform <admin@security.hyunni.com> - 0.1.0-1
- Initial release: sshd_config, os-release, packages, listening ports, dnf security updates 수집
