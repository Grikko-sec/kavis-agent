#!/usr/bin/env bash
# kavis-agent 원라이너 설치 스크립트
#
#   curl -fsSL https://raw.githubusercontent.com/Grikko-sec/kavis-agent/main/install.sh \
#     | sudo bash -s -- --server-url https://kavis.example.com --enroll-key <KEY>
#
# 최신 릴리스에서 이 서버의 OS에 맞는 RPM을 받아 설치하고, config.ini를 비대화형으로
# 작성한 뒤 systemd timer까지 활성화한다. root(sudo)로 실행해야 한다.
set -euo pipefail

REPO="Grikko-sec/kavis-agent"
SERVER_URL=""
ENROLL_KEY=""
TOKEN=""
START_NOW=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url) SERVER_URL="$2"; shift 2 ;;
    --enroll-key) ENROLL_KEY="$2"; shift 2 ;;
    --token)      TOKEN="$2"; shift 2 ;;
    --no-start)   START_NOW=0; shift ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$SERVER_URL" ]]; then
  echo "오류: --server-url 이 필요합니다." >&2
  exit 2
fi
if [[ -z "$ENROLL_KEY" && -z "$TOKEN" ]]; then
  echo "오류: --enroll-key 또는 --token 중 하나가 필요합니다." >&2
  exit 2
fi
if [[ "$EUID" -ne 0 ]]; then
  echo "오류: root 권한으로 실행해주세요 (sudo bash ...)." >&2
  exit 2
fi

# ── OS 판별 ──────────────────────────────────────────
. /etc/os-release
OS_DIR=""
case "${ID}-${VERSION_ID}" in
  rhel-9*|rocky-9*|centos-9*|almalinux-9*) OS_DIR="el9" ;;
  *) ;;
esac
if [[ -z "$OS_DIR" ]]; then
  echo "오류: 지원하지 않는 OS입니다 (${PRETTY_NAME:-$ID $VERSION_ID}). 현재는 RHEL/Rocky/CentOS/Alma 9 계열만 지원합니다." >&2
  exit 1
fi
echo "[install] 감지된 OS: ${PRETTY_NAME:-$ID $VERSION_ID} -> ${OS_DIR} 패키지 사용"

# ── 최신 릴리스에서 이 OS용 RPM 다운로드 URL 찾기 ──────
API_URL="https://api.github.com/repos/${REPO}/releases/latest"
RELEASE_JSON=$(curl -fsSL "$API_URL")
RPM_URL=$(echo "$RELEASE_JSON" \
  | grep -o "\"browser_download_url\": *\"[^\"]*\.${OS_DIR}\.noarch\.rpm\"" \
  | head -1 | sed -E 's/.*"(https:[^"]+)"/\1/')

if [[ -z "$RPM_URL" ]]; then
  echo "오류: 최신 릴리스에서 ${OS_DIR}용 RPM을 찾지 못했습니다. ${API_URL} 확인해주세요." >&2
  exit 1
fi
echo "[install] 다운로드: ${RPM_URL}"

TMP_RPM=$(mktemp --suffix=.rpm)
trap 'rm -f "$TMP_RPM"' EXIT
curl -fsSL "$RPM_URL" -o "$TMP_RPM"

# ── 설치 ─────────────────────────────────────────────
echo "[install] 패키지 설치 중..."
if command -v dnf >/dev/null 2>&1; then
  dnf install -y "$TMP_RPM"
else
  rpm -Uvh "$TMP_RPM"
fi

# ── 설정 (비대화형) ──────────────────────────────────
CONF_ARGS=(--server-url "$SERVER_URL")
[[ -n "$ENROLL_KEY" ]] && CONF_ARGS+=(--enroll-key "$ENROLL_KEY")
[[ -n "$TOKEN" ]] && CONF_ARGS+=(--token "$TOKEN")

echo "[install] config.ini 작성 중..."
/usr/local/bin/kavis-agent configure "${CONF_ARGS[@]}"

# ── 활성화 ───────────────────────────────────────────
systemctl daemon-reload
systemctl enable --now kavis-agent.timer

if [[ "$START_NOW" -eq 1 ]]; then
  echo "[install] 최초 1회 실행 중 (dnf 캐시가 없으면 몇 분 걸릴 수 있습니다)..."
  systemctl start kavis-agent.service
  systemctl --no-pager status kavis-agent.service || true
fi

echo "[install] 완료. 로그: journalctl -u kavis-agent.service -n 50"
