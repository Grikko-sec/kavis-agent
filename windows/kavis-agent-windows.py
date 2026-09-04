#!/usr/bin/env python3
"""kavis-agent-windows - 취약점 점검 플랫폼 수집 에이전트 (Windows)

리눅스판(kavis-agent)과 설계 원칙은 동일하다 — 서버는 아무것도 판정하지 않는다.
이 에이전트는 정해진 원문(레지스트리, PowerShell 명령 결과 등)만 그대로 수집해
플랫폼의 /api/agent/ingest.php 로 전송한다. 취약 여부 판정은 서버 쪽에서 이루어진다.

v0.1.0(첫 버전) 범위: 인벤토리(OS/하드웨어/네트워크) + 원문 수집(핫픽스, 설치
소프트웨어, 로컬 계정, 방화벽 프로파일, 계정 정책, 감사 정책, RDP 설정, 리스닝
포트, 따옴표 없는 서비스 경로). FIM/로그온 이력/원격 작업(방화벽·차단)은
리눅스판에서 검증된 뒤 다음 버전에서 이어서 넣는다 — 서버 쪽에 아직 이 항목들을
위한 파서(parse_rules)/화면이 없으므로, 지금 보내도 원문 그대로 저장만 되고
체크리스트 판정에는 쓰이지 않는다(추후 서버 작업과 함께 활성화된다).
"""
import argparse
import configparser
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import random
import urllib.error
import urllib.request

AGENT_VERSION = "0.1.1"
CONFIG_PATH = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "kavis-agent", "config.ini")
MAX_ITEM_BYTES = 190_000  # 서버 측 200KB 제한보다 여유를 둔다
TIMEOUT_SECONDS = 20
DEFAULT_INTERVAL_SECONDS = 3600
DEFAULT_JITTER_SECONDS = 300


def log(msg: str) -> None:
    print(f"[kavis-agent-windows] {msg}", file=sys.stderr, flush=True)


def truncate(s: str) -> str:
    b = s.encode("utf-8", errors="replace")
    if len(b) <= MAX_ITEM_BYTES:
        return s
    return b[:MAX_ITEM_BYTES].decode("utf-8", errors="ignore") + "\n...[truncated]"


def read_config() -> dict:
    cp = configparser.ConfigParser()
    if not cp.read(CONFIG_PATH):
        log(f"설정 파일을 읽을 수 없습니다: {CONFIG_PATH}")
        sys.exit(1)
    if "agent" not in cp:
        log("설정 파일에 [agent] 섹션이 없습니다.")
        sys.exit(1)
    section = cp["agent"]
    server_url = section.get("server_url", "").rstrip("/")
    token = section.get("token", "").strip()
    enroll_key = section.get("enroll_key", "").strip()
    if not server_url or (not token and not enroll_key):
        log("server_url이 비어있거나, token/enroll_key가 둘 다 비어있습니다. "
            f"{CONFIG_PATH} 를 확인하세요.")
        sys.exit(1)
    return {
        "server_url": server_url,
        "token": token,
        "enroll_key": enroll_key,
        "verify_tls": section.getboolean("verify_tls", fallback=True),
        "timeout": section.getint("timeout", fallback=TIMEOUT_SECONDS),
    }


def make_ssl_context(url: str, verify_tls: bool):
    if url.startswith("https://") and not verify_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


def save_token(token: str) -> bool:
    """CONFIG_PATH의 token = ... 줄만 교체한다. 없으면 [agent] 섹션 끝에 추가한다."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        log(f"설정 파일을 읽을 수 없어 토큰을 저장하지 못했습니다: {e}")
        return False

    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith("token"):
            lines[i] = f"token = {token}\n"
            replaced = True
            break
    if not replaced:
        for i, line in enumerate(lines):
            if line.strip() == "[agent]":
                lines.insert(i + 1, f"token = {token}\n")
                replaced = True
                break
    if not replaced:
        lines.append(f"\n[agent]\ntoken = {token}\n")

    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except OSError as e:
        log(f"설정 파일에 토큰을 저장하지 못했습니다: {e}")
        return False


def enroll(config: dict) -> str:
    """공용 등록 키로 자산을 자동 등록하고, 발급받은 전용 토큰을 설정 파일에 저장한다."""
    url = f"{config['server_url']}/api/agent/enroll.php"
    payload = {"hostname": socket.gethostname()}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {config['enroll_key']}",
            "Content-Type": "application/json",
            "User-Agent": f"kavis-agent-windows/{AGENT_VERSION}",
        },
    )
    ctx = make_ssl_context(url, config["verify_tls"])
    try:
        with urllib.request.urlopen(req, timeout=config["timeout"], context=ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        log(f"자동 등록 실패 ({e.code}): {e.read().decode('utf-8', errors='replace')}")
        sys.exit(1)
    except urllib.error.URLError as e:
        log(f"자동 등록 연결 실패: {e.reason}")
        sys.exit(1)

    token = result.get("token", "")
    if not token:
        log(f"자동 등록 응답에 토큰이 없습니다: {result}")
        sys.exit(1)

    saved = save_token(token)
    status = "설정 파일에 저장했습니다" if saved else "설정 파일 저장에 실패했습니다 — 이번 실행에만 사용됩니다"
    log(f"자동 등록 완료 (asset_id={result.get('asset_id')}, "
        f"{'신규 생성' if result.get('created') else '기존 자산 재사용'}) — 토큰을 {status}.")
    return token


def cmd_configure(args) -> None:
    """비대화형으로 config.ini를 작성한다. 각 값은 --플래그 또는 KAVIS_* 환경변수로 줄 수 있다.
    기존 파일에 이미 값이 있는데 이번 실행에 해당 플래그를 안 줬으면, 그 값을 지우지 않고
    그대로 둔다 — 예: 최초엔 --enroll-key로 등록하고, 나중엔 --token만으로 재설정할 때
    직전에 저장된 값이 빈 문자열로 덮어써지는 일이 없도록."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH)
    existing = dict(cp["agent"]) if "agent" in cp else {}

    server_url = args.server_url or os.environ.get("KAVIS_SERVER_URL", "") or existing.get("server_url", "")
    enroll_key = args.enroll_key or os.environ.get("KAVIS_ENROLL_KEY", "") or existing.get("enroll_key", "")
    token = args.token or os.environ.get("KAVIS_TOKEN", "") or existing.get("token", "")
    verify_tls = "true" if args.verify_tls else "false"

    if not server_url:
        log("--server-url (또는 KAVIS_SERVER_URL)이 필요합니다.")
        sys.exit(2)
    if not enroll_key and not token:
        log("--enroll-key 또는 --token (혹은 해당 환경변수) 중 하나는 필요합니다.")
        sys.exit(2)

    cp["agent"] = {
        "server_url": server_url.rstrip("/"),
        "enroll_key": enroll_key,
        "token": token,
        "verify_tls": verify_tls,
        "timeout": str(args.timeout),
    }
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cp.write(f)
    except OSError as e:
        log(f"설정 파일을 쓰지 못했습니다: {e}")
        sys.exit(1)
    log(f"{CONFIG_PATH} 작성 완료. (token={'설정됨' if token else '없음'}, "
        f"enroll_key={'설정됨' if enroll_key else '없음'})")


# ── PowerShell 기반 수집 ────────────────────────────────
# 매 사이클 powershell.exe를 여러 번 띄우는 대신, 아래 스크립트 하나로 필요한 항목을
# 전부 모아 JSON 하나로 뽑아낸다(속도/일관성). 각 블록은 Try-Get으로 감싸 하나가
# 실패해도(권한 부족, 모듈 없음 등) 나머지 수집에 영향이 없도록 한다.
COLLECT_PS1 = r"""
$ErrorActionPreference = 'SilentlyContinue'
function Try-Get { param([scriptblock]$Block) try { & $Block } catch { $null } }

$os    = Try-Get { Get-CimInstance Win32_OperatingSystem }
$cs    = Try-Get { Get-CimInstance Win32_ComputerSystem }
$bios  = Try-Get { Get-CimInstance Win32_BIOS }
$cpu   = Try-Get { @(Get-CimInstance Win32_Processor) }
$prod  = Try-Get { Get-CimInstance Win32_ComputerSystemProduct }
$disks = Try-Get { @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3") }

$netcfg    = Try-Get { @(Get-NetIPConfiguration) }
$adapters  = Try-Get { @(Get-NetAdapter) }

$ifaces = @(); $allIps = @(); $allMacs = @(); $gateway = $null
foreach ($n in $netcfg) {
    if (-not $n.IPv4Address) { continue }
    $ips = @()
    foreach ($a in $n.IPv4Address) {
        $ips += "$($a.IPAddress)/$($a.PrefixLength)"
        $allIps += $a.IPAddress
    }
    $mac = ($adapters | Where-Object { $_.ifIndex -eq $n.InterfaceIndex } | Select-Object -First 1 -ExpandProperty MacAddress)
    if ($mac) { $allMacs += $mac }
    $gw = $null
    if ($n.IPv4DefaultGateway) { $gw = $n.IPv4DefaultGateway.NextHop }
    if ($gw -and -not $gateway) { $gateway = $gw }
    $ifaces += [ordered]@{ name = $n.InterfaceAlias; mac = $mac; ips = $ips; gateway = $gw }
}
$dnsServers = @()
foreach ($n in $netcfg) {
    if ($n.DNSServer) { foreach ($d in $n.DNSServer.ServerAddresses) { if ($d) { $dnsServers += $d } } }
}
$dnsServers = @($dnsServers | Select-Object -Unique)

$memMb = $null
if ($cs.TotalPhysicalMemory) { $memMb = [math]::Round($cs.TotalPhysicalMemory / 1MB) }
$diskGb = $null
if ($disks) { $diskGb = [math]::Round((($disks | Measure-Object -Property Size -Sum).Sum) / 1GB) }

$virt = "physical"
if ($cs.Model -match "Virtual|VMware|KVM|Xen|VirtualBox") { $virt = "virtual" }

$hotfixes = Try-Get { @(Get-HotFix | Select-Object HotFixID,Description,InstalledOn) | ConvertTo-Json -Compress -Depth 3 }

$software = @()
foreach ($base in @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)) {
    Try-Get {
        Get-ItemProperty $base | Where-Object { $_.DisplayName } | ForEach-Object {
            $software += [ordered]@{ name = $_.DisplayName; version = $_.DisplayVersion; publisher = $_.Publisher; install_date = $_.InstallDate }
        }
    } | Out-Null
}

$localUsers  = Try-Get { @(Get-LocalUser | Select-Object Name,Enabled,PasswordRequired,PasswordExpires,LastLogon) | ConvertTo-Json -Compress -Depth 3 }
$localAdmins = Try-Get { @(Get-LocalGroupMember -Group "Administrators" | Select-Object Name,ObjectClass,PrincipalSource) | ConvertTo-Json -Compress -Depth 3 }
$fwProfiles  = Try-Get { @(Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction) | ConvertTo-Json -Compress -Depth 3 }
$netAccounts = Try-Get { (net accounts | Out-String) }
$auditPolicy = Try-Get { (auditpol /get /category:* | Out-String) }
$listenPorts = Try-Get {
    @(Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess,
      @{n='ProcessName';e={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}}) | ConvertTo-Json -Compress -Depth 3
}

$rdpKey    = 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server'
$rdpTcpKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp'
$rdp = [ordered]@{
    deny_connections = (Try-Get { (Get-ItemProperty $rdpKey -ErrorAction Stop).fDenyTSConnections })
    nla_required     = (Try-Get { (Get-ItemProperty $rdpTcpKey -ErrorAction Stop).UserAuthentication })
    security_layer   = (Try-Get { (Get-ItemProperty $rdpTcpKey -ErrorAction Stop).SecurityLayer })
}

function Test-UnquotedServicePath {
    # 진짜 취약 조건: exe "이전" 경로(디렉터리+파일명)에 공백이 있고 따옴표로 안 감싼 경우.
    # svchost.exe 등은 뒤에 "-k netsvcs -p" 같은 인자가 붙어 PathName 전체엔 공백이 있지만,
    # 그건 인자 구분 공백이지 실행파일 경로의 공백이 아니므로 취약이 아니다 — exe 앞부분만 잘라서 검사.
    param($path)
    if (-not $path) { return $false }
    if ($path -match '^\s*"') { return $false }
    if ($path -match '^([A-Za-z]:\\[^"]*?\.exe)') {
        return $matches[1] -match ' '
    }
    return $false
}
$unquotedSvc = Try-Get {
    @(Get-CimInstance Win32_Service | Where-Object { Test-UnquotedServicePath $_.PathName } |
      Select-Object Name,PathName,StartMode,StartName) | ConvertTo-Json -Compress -Depth 3
}

$result = [ordered]@{
    os_name = $os.Caption
    os_version = $os.Version
    os_arch = $os.OSArchitecture
    manufacturer = $cs.Manufacturer
    model = $cs.Model
    serial_number = $bios.SerialNumber
    bios_version = $bios.SMBIOSBIOSVersion
    cpu_model = ($cpu | Select-Object -First 1 -ExpandProperty Name)
    cpu_count = (@($cpu)).Count
    cpu_core_count = (($cpu | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum)
    memory_mb = $memMb
    disk_total_gb = $diskGb
    domain = $cs.Domain
    machine_uuid = $prod.UUID
    virtualization_type = $virt
    network_interfaces = $ifaces
    ip_addresses = @($allIps | Select-Object -Unique)
    mac_addresses = @($allMacs | Select-Object -Unique)
    dns_servers = $dnsServers
    gateway = $gateway
    installed_hotfixes = $hotfixes
    installed_software = (@($software) | ConvertTo-Json -Compress -Depth 3)
    local_users = $localUsers
    local_administrators = $localAdmins
    firewall_profiles = $fwProfiles
    net_accounts_policy = $netAccounts
    audit_policy = $auditPolicy
    listening_ports = $listenPorts
    rdp_config = ($rdp | ConvertTo-Json -Compress -Depth 3)
    unquoted_service_paths = $unquotedSvc
}
$result | ConvertTo-Json -Compress -Depth 6
"""

# collect() 결과에서 inventory(구조화된 사실)로 보낼 키 — 리눅스판 upsert_asset_inventory와
# 같은 필드명을 써서 서버/화면 쪽 변경 없이 바로 개요 탭에 표시되도록 맞췄다.
_INVENTORY_KEYS = (
    "os_name", "os_version", "os_arch", "manufacturer", "model", "serial_number",
    "bios_version", "cpu_model", "cpu_count", "cpu_core_count", "memory_mb",
    "disk_total_gb", "domain", "machine_uuid", "virtualization_type",
    "network_interfaces", "ip_addresses", "mac_addresses", "dns_servers", "gateway",
)
# 나머지는 판정 파서가 아직 서버에 없는 원문 — items로 보내되 _windows 접미사를 붙여
# 리눅스 원문(예: listening_ports)과 이름이 겹치지 않게 한다.
_RAW_ITEM_KEYS = (
    "installed_hotfixes", "installed_software", "local_users", "local_administrators",
    "firewall_profiles", "net_accounts_policy", "audit_policy", "listening_ports",
    "rdp_config", "unquoted_service_paths",
)


def run_powershell_collect() -> dict:
    """COLLECT_PS1을 임시 파일로 저장해 실행하고 결과 JSON을 파싱한다.
    임시 파일로 저장하는 이유: -Command로 여러 줄을 그대로 넘기면 따옴표/이스케이프가
    깨지기 쉽고, 실패 시 사용자가 같은 파일로 직접 재현/디버깅하기도 쉽다."""
    fd, path = tempfile.mkstemp(suffix=".ps1", prefix="kavis-collect-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(COLLECT_PS1)
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
                capture_output=True, text=True, timeout=120, check=False,
                stdin=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log(f"PowerShell 수집 실패: {e}")
            return {}
        if result.returncode != 0:
            log(f"PowerShell 수집 스크립트가 오류를 반환했습니다 (rc={result.returncode}): "
                f"{result.stderr.strip()[:500]}")
        try:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError as e:
            log(f"PowerShell 수집 결과 JSON 파싱 실패: {e} — 원문 앞부분: {result.stdout[:300]!r}")
            return {}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def collect() -> dict:
    raw = run_powershell_collect()

    inv = {"fqdn": socket.getfqdn()}
    for k in _INVENTORY_KEYS:
        if k in raw:
            inv[k] = raw[k]

    items = {}
    for k in _RAW_ITEM_KEYS:
        v = raw.get(k)
        if v:
            items[f"{k}_windows"] = truncate(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))

    return {
        "agent_version": AGENT_VERSION,
        "hostname": socket.gethostname(),
        "items": items,
        "inventory": inv,
    }


def send(config: dict, payload: dict) -> dict:
    url = f"{config['server_url']}/api/agent/ingest.php"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {config['token']}",
            "Content-Type": "application/json",
            "User-Agent": f"kavis-agent-windows/{AGENT_VERSION}",
        },
    )
    ctx = make_ssl_context(url, config["verify_tls"])
    try:
        with urllib.request.urlopen(req, timeout=config["timeout"], context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            log(f"전송 성공 ({resp.status}): {body}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log(f"서버 응답 오류 ({e.code}): {body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        log(f"연결 실패: {e.reason}")
        sys.exit(1)
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return {}


def cmd_run(_args) -> None:
    """1회 수집 후 종료 — 수동 테스트/디버깅용. 상시 운영은 'daemon'을 쓴다."""
    config = read_config()
    if not config["token"]:
        config["token"] = enroll(config)
    payload = collect()
    log(f"{len(payload['items'])}개 원문 항목 + 인벤토리 수집 완료, 전송 중...")
    send(config, payload)


def cmd_daemon(args) -> None:
    """상주 프로세스로 실행 — Task Scheduler(부팅 시 시작, 실패 시 재시작)로 등록해 쓴다."""
    log(f"데몬 모드 시작 (수집 주기={args.interval}초, 지터=0~{args.jitter}초)")
    config = read_config()
    if not config["token"]:
        config["token"] = enroll(config)

    while True:
        try:
            payload = collect()
            log(f"{len(payload['items'])}개 원문 항목 + 인벤토리 수집 완료, 전송 중...")
            send(config, payload)
        except SystemExit:
            pass  # send()가 실패 시 sys.exit(1)을 부르는데, 데몬은 다음 주기에 재시도해야 하므로 죽지 않는다
        except Exception as e:  # noqa: BLE001 - 데몬은 어떤 예외에도 죽지 않고 다음 주기를 기다려야 한다
            log(f"수집/전송 중 예외: {e}")
        sleep_for = args.interval + random.randint(0, max(args.jitter, 0))
        time.sleep(sleep_for)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kavis-agent-windows")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("collect", help="1회 수집 후 종료 (테스트용)")
    p_run.set_defaults(func=cmd_run)

    p_daemon = sub.add_parser("daemon", help="상주 모드로 실행")
    p_daemon.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    p_daemon.add_argument("--jitter", type=int, default=DEFAULT_JITTER_SECONDS)
    p_daemon.set_defaults(func=cmd_daemon)

    p_conf = sub.add_parser("configure", help="비대화형으로 config.ini 작성")
    p_conf.add_argument("--server-url")
    p_conf.add_argument("--enroll-key")
    p_conf.add_argument("--token")
    p_conf.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS)
    p_conf.add_argument("--verify-tls", action="store_true", default=True)
    p_conf.add_argument("--no-verify-tls", dest="verify_tls", action="store_false")
    p_conf.set_defaults(func=cmd_configure)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
