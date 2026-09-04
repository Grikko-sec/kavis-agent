#!/usr/bin/env python3
"""kavis-agent-windows - 취약점 점검 플랫폼 수집 에이전트 (Windows)

리눅스판(kavis-agent)과 설계 원칙은 동일하다 — 서버는 아무것도 판정하지 않는다.
이 에이전트는 정해진 원문(레지스트리, PowerShell 명령 결과 등)만 그대로 수집해
플랫폼의 /api/agent/ingest.php 로 전송한다. 취약 여부 판정은 서버 쪽에서 이루어진다.

v0.1.x 범위: 인벤토리(OS/하드웨어/네트워크) + 원문 수집(핫픽스, 설치 소프트웨어,
로컬 계정, 방화벽 프로파일, 계정 정책, 감사 정책, RDP 설정, 리스닝 포트, 따옴표
없는 서비스 경로). 로그온 이력/원격 작업(방화벽·차단)은 리눅스판에서 검증된 뒤
다음 버전에서 이어서 넣는다.

v0.2.0부터 FIM(파일 무결성 모니터링) 추가 — 리눅스판(auditd)과 같은 원리를
Windows 감사 서브시스템으로 구현: auditpol로 "파일 시스템" 개체 액세스 감사를
켜고, 서버가 지정한 감시 경로마다 SACL(감사용 ACL)을 걸어두면, 이후 그 경로에서
파일 생성/삭제/수정/권한변경이 일어날 때마다 보안 이벤트 로그(4663=개체 액세스
시도, 4670=권한 변경)가 쌓인다. 에이전트는 그 이벤트의 원시 필드(ObjectName,
AccessMask 16진수, 이벤트 ID, 계정)만 그대로 서버로 보내고 — CREATE/DELETE/
CONTENT/SECURITY 분류는 여기서 안 하고 서버(ingest.php)가 AccessMask 비트를
해석해서 판정한다(로케일 의존적인 렌더링된 설명 텍스트 대신 원시 비트마스크를
쓰는 이유: 이 서버가 한국어 Windows라 렌더링된 문구를 파싱하면 로케일이 바뀌는
순간 깨진다 — 리눅스판에서 sshd-session 정규식이 겪었던 것과 같은 종류의 함정).
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
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

AGENT_VERSION = "0.2.3"
_PROGRAMDATA = os.environ.get("ProgramData", r"C:\ProgramData")
_STATE_DIR = os.path.join(_PROGRAMDATA, "kavis-agent")
CONFIG_PATH = os.path.join(_STATE_DIR, "config.ini")
MAX_ITEM_BYTES = 190_000  # 서버 측 200KB 제한보다 여유를 둔다
TIMEOUT_SECONDS = 20
DEFAULT_INTERVAL_SECONDS = 3600
DEFAULT_JITTER_SECONDS = 300

# ── FIM(파일 무결성 모니터링) ─────────────────────────
# auditpol은 영문 서브카테고리 이름("File System")을 한국어 등 비영문 Windows에서
# 못 알아먹고 0x00000057(매개 변수가 틀립니다) 오류를 낸다 — 실제 서버(한국어)에서
# 확인됨. 서브카테고리 GUID(로케일 무관, 고정값)로 지정해야 모든 언어판에서 동작한다.
FIM_AUDIT_SUBCATEGORY = "{0CCE921D-69AE-11D9-BED3-505054503030}"  # Audit File System
FIM_CHECKPOINT_PATH = os.path.join(_STATE_DIR, ".fim_checkpoint.json")
FIM_SERVER_DIRS_PATH = os.path.join(_STATE_DIR, ".fim_watch_dirs.json")
FIM_INITIAL_LOOKBACK_SECONDS = 3600  # 체크포인트가 없는 최초 실행 시 최근 1시간만
DEFAULT_FIM_INTERVAL_SECONDS = 180   # FIM 전용 주기 — 리눅스판과 동일하게 무거운 전체 수집과 분리


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


def run_cmd(args: list, timeout: int = 30) -> str:
    """일반 exe(파워셸이 아닌) 명령 실행 — 실패해도 예외를 던지지 않고 빈 문자열을 돌려준다."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
            stdin=subprocess.DEVNULL,
        )
        return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log(f"명령 실행 실패 ({' '.join(args)}): {e}")
        return ""


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

$hotfixes = Try-Get { ConvertTo-Json -InputObject @(Get-HotFix | Select-Object HotFixID,Description,InstalledOn) -Compress -Depth 3 }

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

$localUsers  = Try-Get { ConvertTo-Json -InputObject @(Get-LocalUser | Select-Object Name,Enabled,PasswordRequired,PasswordExpires,LastLogon) -Compress -Depth 3 }
$localAdmins = Try-Get { ConvertTo-Json -InputObject @(Get-LocalGroupMember -Group "Administrators" | Select-Object Name,ObjectClass,PrincipalSource) -Compress -Depth 3 }
$fwProfiles  = Try-Get { ConvertTo-Json -InputObject @(Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction) -Compress -Depth 3 }
$netAccounts = Try-Get { (net accounts | Out-String) }
$auditPolicy = Try-Get { (auditpol /get /category:* | Out-String) }
$listenPorts = Try-Get {
    $conns = @(Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess,
      @{n='ProcessName';e={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}})
    ConvertTo-Json -InputObject $conns -Compress -Depth 3
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
    $bad = @(Get-CimInstance Win32_Service | Where-Object { Test-UnquotedServicePath $_.PathName } |
      Select-Object Name,PathName,StartMode,StartName)
    ConvertTo-Json -InputObject $bad -Compress -Depth 3
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
    installed_software = (ConvertTo-Json -InputObject @($software) -Compress -Depth 3)
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


def run_powershell_file(script: str, args: list = None, timeout: int = 120) -> str:
    """스크립트 본문을 임시 .ps1 파일로 저장해 실행하고 stdout을 돌려준다(실패 시 "").
    임시 파일로 저장하는 이유: -Command로 여러 줄을 그대로 넘기면 따옴표/이스케이프가
    깨지기 쉽고, 실패 시 사용자가 같은 파일로 직접 재현/디버깅하기도 쉽다."""
    fd, path = tempfile.mkstemp(suffix=".ps1", prefix="kavis-ps-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path]
        cmd.extend(args or [])
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False,
                stdin=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log(f"PowerShell 실행 실패: {e}")
            return ""
        if result.returncode != 0:
            log(f"PowerShell 스크립트가 오류를 반환했습니다 (rc={result.returncode}): "
                f"{result.stderr.strip()[:500]}")
        return result.stdout
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def run_powershell_collect() -> dict:
    out = run_powershell_file(COLLECT_PS1, timeout=120)
    try:
        return json.loads(out) if out.strip() else {}
    except json.JSONDecodeError as e:
        log(f"PowerShell 수집 결과 JSON 파싱 실패: {e} — 원문 앞부분: {out[:300]!r}")
        return {}


# ── FIM(파일 무결성 모니터링) ─────────────────────────
# SACL 적용 대상 경로 하나 - 이미 걸려있으면 건드리지 않는다(idempotent, 매 주기 재적용 방지).
FIM_SACL_PS1 = r"""
param([string]$TargetPath)
$ErrorActionPreference = 'Stop'
try {
    if (-not (Test-Path -LiteralPath $TargetPath)) {
        Write-Output "MISSING"
        exit 0
    }
    $acl = Get-Acl -Path $TargetPath -Audit
    $alreadySet = $false
    foreach ($rule in $acl.Audit) {
        if ($rule.IdentityReference.Value -eq "Everyone" -and $rule.AuditFlags -eq "Success") {
            $alreadySet = $true
            break
        }
    }
    if (-not $alreadySet) {
        $rights     = [System.Security.AccessControl.FileSystemRights]"CreateFiles, AppendData, Delete, DeleteSubdirectoriesAndFiles, WriteData, ChangePermissions, TakeOwnership"
        $inherit    = [System.Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
        $propagate  = [System.Security.AccessControl.PropagationFlags]::None
        $auditFlag  = [System.Security.AccessControl.AuditFlags]::Success
        $rule = New-Object System.Security.AccessControl.FileSystemAuditRule("Everyone", $rights, $inherit, $propagate, $auditFlag)
        $acl.AddAuditRule($rule)
        Set-Acl -Path $TargetPath -AclObject $acl
        Write-Output "APPLIED"
    } else {
        Write-Output "ALREADY_SET"
    }
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
"""

# 4663=개체 액세스 시도(생성/삭제/내용변경 전부 이 이벤트에서 AccessMask로 구분),
# 4670=개체 권한(SACL/DACL) 변경 — 리눅스의 SECURITY 분류에 대응.
# AccessList(렌더링된 설명 텍스트)는 로케일에 따라 달라지므로 절대 안 쓰고, 로케일 무관한
# 원시 16진수 AccessMask만 그대로 서버에 넘긴다 — 분류(CREATE/DELETE/CONTENT/SECURITY)는
# 서버가 비트 연산으로 판정한다(ingest.php).
FIM_EVENTS_PS1 = r"""
param([string]$SinceIso)
$ErrorActionPreference = 'SilentlyContinue'
try {
    $startTime = [DateTime]::Parse($SinceIso, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)
} catch {
    $startTime = (Get-Date).AddHours(-1)
}

$events = @(Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4663,4670; StartTime=$startTime} -MaxEvents 3000 -ErrorAction SilentlyContinue)
$out = @()
foreach ($e in $events) {
    try {
        $xml = [xml]$e.ToXml()
        $data = @{}
        foreach ($d in $xml.Event.EventData.Data) {
            if ($d.Name) { $data[$d.Name] = $d.'#text' }
        }
        $out += [ordered]@{
            event_id       = [int]$e.Id
            record_id      = [int64]$e.RecordId
            time_created   = $e.TimeCreated.ToUniversalTime().ToString("o")
            object_name    = $data['ObjectName']
            access_mask    = $data['AccessMask']
            process_name   = $data['ProcessName']
            subject_user   = $data['SubjectUserName']
            subject_domain = $data['SubjectDomainName']
        }
    } catch {}
}
ConvertTo-Json -InputObject $out -Compress -Depth 4
"""


def save_fim_watch_dirs(dirs) -> None:
    """서버(관리자 페이지, ingest.php 응답)가 내려준 FIM 감시 경로 목록을 로컬에 캐시한다."""
    if not isinstance(dirs, list):
        return
    clean = [d for d in dirs if isinstance(d, str) and d]
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        with open(FIM_SERVER_DIRS_PATH, "w", encoding="utf-8") as f:
            json.dump(clean, f)
    except OSError as e:
        log(f"[FIM] 서버 감시 경로 캐시 저장 실패: {e}")


def read_fim_watch_dirs() -> list:
    """캐시된 FIM 감시 경로 중 실제로 존재하는 디렉토리만 돌려준다."""
    dirs = []
    if os.path.exists(FIM_SERVER_DIRS_PATH):
        try:
            with open(FIM_SERVER_DIRS_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, list):
                dirs = [d for d in cached if isinstance(d, str)]
        except (OSError, ValueError):
            dirs = []
    result = []
    for d in dirs:
        if not os.path.isdir(d):
            log(f"[FIM] 감시 대상 디렉토리가 없어 건너뜁니다: {d}")
            continue
        result.append(d)
    return result


def sync_fim_audit(dirs: list) -> bool:
    """파일 시스템 개체 액세스 감사를 켜고, 각 디렉토리에 SACL(감사 규칙)을 적용한다."""
    if not dirs:
        return False
    if not shutil.which("auditpol.exe") and not shutil.which("auditpol"):
        log("[FIM] auditpol을 찾을 수 없어 파일 무결성 모니터링을 건너뜁니다.")
        return False

    # auditpol로 서브카테고리(File System) 단위 감사를 켜도, 이 레지스트리 값이 없으면
    # Windows가 옛날 방식(카테고리 단위 — 기본 꺼짐)을 우선시해서 SACL을 걸어도 이벤트가
    # 하나도 안 남는다 — 실제 서버에서 재현/확인된 문제. Microsoft도 세부 감사 정책을 쓸 때
    # 이 값을 켜도록 공식 권장한다.
    try:
        r = subprocess.run(
            ["reg", "add", r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa",
             "/v", "SCENoApplyLegacyAuditPolicy", "/t", "REG_DWORD", "/d", "1", "/f"],
            capture_output=True, text=True, timeout=15, check=False, stdin=subprocess.DEVNULL,
        )
        if r.returncode != 0:
            log(f"[FIM] SCENoApplyLegacyAuditPolicy 레지스트리 설정 실패 (rc={r.returncode}): "
                f"{(r.stdout + r.stderr).strip()[:300]}")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log(f"[FIM] 레지스트리 설정(reg.exe) 실행 실패: {e}")

    try:
        r = subprocess.run(
            ["auditpol", "/set", f"/subcategory:{FIM_AUDIT_SUBCATEGORY}", "/success:enable", "/failure:disable"],
            capture_output=True, text=True, timeout=30, check=False, stdin=subprocess.DEVNULL,
        )
        if r.returncode != 0:
            log(f"[FIM] auditpol 감사 정책 설정 실패 (rc={r.returncode}): {(r.stdout + r.stderr).strip()[:300]}")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log(f"[FIM] auditpol 실행 실패: {e}")
        return False

    ok_any = False
    for d in dirs:
        out = run_powershell_file(FIM_SACL_PS1, args=[d], timeout=30).strip()
        if out.startswith("APPLIED"):
            log(f"[FIM] 감사 규칙 적용: {d}")
            ok_any = True
        elif out.startswith("ALREADY_SET"):
            ok_any = True
        elif out.startswith("MISSING"):
            log(f"[FIM] 감시 대상 디렉토리가 없어 건너뜁니다: {d}")
        else:
            log(f"[FIM] 감사 규칙 적용 실패 ({d}): {out[:200]}")
    return ok_any


def read_fim_checkpoint() -> str:
    """마지막으로 조회한 시각(ISO, UTC)을 돌려준다. 체크포인트가 없으면 최근 1시간 전."""
    if os.path.exists(FIM_CHECKPOINT_PATH):
        try:
            with open(FIM_CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            since = data.get("since")
            if isinstance(since, str) and since:
                return since
        except (OSError, ValueError):
            pass
    return (datetime.now(timezone.utc) - timedelta(seconds=FIM_INITIAL_LOOKBACK_SECONDS)).isoformat()


_fim_checkpoint_pending = None  # collect()에서 조회 시각을 잠깐 들고 있다가, send() 성공 후에만 커밋한다


def collect_fim_events() -> list:
    """직전 체크포인트 이후 쌓인 4663/4670 이벤트를 구조화된 필드 그대로 가져온다.
    분류(CREATE/DELETE/CONTENT/SECURITY)는 서버가 AccessMask 비트로 판정한다."""
    global _fim_checkpoint_pending

    dirs = read_fim_watch_dirs()
    if not dirs or not sync_fim_audit(dirs):
        return []

    since = read_fim_checkpoint()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 보안 이벤트 로그가 커지면(대량 파일 작업 등) Get-WinEvent 조회 자체가 오래 걸릴 수 있어
    # 넉넉하게 잡는다 — 60초에서 잘려서 조용히 빈 결과 취급되던 문제(실사용 중 확인됨).
    out = run_powershell_file(FIM_EVENTS_PS1, args=[since], timeout=180)
    _fim_checkpoint_pending = now_iso  # 조회에 성공했으니, 이 시각 이후만 다음번에 다시 물어보면 된다

    if not out.strip():
        return []
    try:
        events = json.loads(out)
    except json.JSONDecodeError as e:
        log(f"[FIM] 이벤트 JSON 파싱 실패: {e}")
        return []
    return events if isinstance(events, list) else []


def commit_fim_checkpoint() -> None:
    """전송이 실제로 성공했을 때만 호출 — 실패하면 다음 주기가 같은 구간을 다시 조회한다."""
    global _fim_checkpoint_pending
    if _fim_checkpoint_pending is not None:
        try:
            os.makedirs(_STATE_DIR, exist_ok=True)
            with open(FIM_CHECKPOINT_PATH, "w", encoding="utf-8") as f:
                json.dump({"since": _fim_checkpoint_pending}, f)
        except OSError as e:
            log(f"[FIM] 체크포인트 저장 실패: {e}")
        _fim_checkpoint_pending = None


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

    fim_events = collect_fim_events()
    if fim_events:
        items["fim_events_windows"] = truncate(json.dumps(fim_events, ensure_ascii=False))

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
        result = json.loads(body)
    except (ValueError, TypeError):
        return {}
    if "fim_watch_dirs" in result:
        save_fim_watch_dirs(result["fim_watch_dirs"])
    return result


def cmd_run(_args) -> None:
    """1회 수집 후 종료 — 수동 테스트/디버깅용. 상시 운영은 'daemon'을 쓴다."""
    config = read_config()
    if not config["token"]:
        config["token"] = enroll(config)
    payload = collect()
    log(f"{len(payload['items'])}개 원문 항목 + 인벤토리 수집 완료, 전송 중...")
    send(config, payload)
    commit_fim_checkpoint()


def send_fim_only(config: dict) -> None:
    """FIM 전용 짧은 주기 — 무거운 전체 수집(패키지/핫픽스/포트 등)은 건드리지 않는다.
    새 이벤트가 있을 때만 전송한다(윈도우는 아직 원격 작업이 없어서, 리눅스판처럼 매번
    전송할 이유가 없다)."""
    fim_events = collect_fim_events()
    if fim_events:
        items = {"fim_events_windows": truncate(json.dumps(fim_events, ensure_ascii=False))}
        payload = {
            "agent_version": AGENT_VERSION,
            "hostname": socket.gethostname(),
            "items": items,
        }
        log(f"[FIM] 새 이벤트 {len(fim_events)}건 감지, 전송 중...")
        send(config, payload)
    commit_fim_checkpoint()


def cmd_daemon(args) -> None:
    """상주 프로세스로 실행하며, 내부에서 두 가지 주기를 돌린다 (리눅스판과 동일한 구조).
    - 전체 수집(핫픽스/계정/방화벽 등, 무거움): --interval 마다
    - FIM 이벤트만: --fim-interval 마다 (Qualys FIM 등 상용 제품의 폴링 주기와 비슷한 수준)
    Task Scheduler(부팅 시 시작, 실패 시 재시작)로 등록해 쓴다."""
    log(f"데몬 모드 시작 (전체 수집 주기={args.interval}초, 지터=0~{args.jitter}초, "
        f"FIM 전용 주기={args.fim_interval}초)")

    next_full = 0.0  # 0으로 두면 시작하자마자 첫 전체 수집을 바로 한 번 돈다
    next_fim = 0.0

    while True:
        now = time.time()
        try:
            config = read_config()
            if not config["token"]:
                config["token"] = enroll(config)

            if now >= next_full:
                payload = collect()  # FIM도 이 안에 포함되므로 전체 수집 시엔 FIM 전용 주기를 따로 안 돈다
                log(f"{len(payload['items'])}개 원문 항목 + 인벤토리 수집 완료, 전송 중...")
                send(config, payload)
                commit_fim_checkpoint()
                next_full = now + args.interval + random.randint(0, max(args.jitter, 0))
                next_fim = now + args.fim_interval
            elif now >= next_fim:
                send_fim_only(config)
                next_fim = now + args.fim_interval
        except SystemExit:
            log("이번 주기 실행에 실패했습니다 — 다음 주기에 다시 시도합니다.")
            next_fim = max(next_fim, time.time() + args.fim_interval)
        except Exception as e:  # noqa: BLE001 - 데몬은 어떤 예외에도 죽지 않고 다음 주기를 기다려야 한다
            log(f"예상치 못한 오류로 이번 주기를 건너뜁니다: {e}")
            next_fim = max(next_fim, time.time() + args.fim_interval)

        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kavis-agent-windows")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("collect", help="1회 수집 후 종료 (테스트용)")
    p_run.set_defaults(func=cmd_run)

    p_daemon = sub.add_parser("daemon", help="상주 모드로 실행")
    p_daemon.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    p_daemon.add_argument("--jitter", type=int, default=DEFAULT_JITTER_SECONDS)
    p_daemon.add_argument("--fim-interval", type=int, default=DEFAULT_FIM_INTERVAL_SECONDS)
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
