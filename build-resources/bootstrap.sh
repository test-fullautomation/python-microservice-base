#!/usr/bin/env bash
#
# DevAtServGUI — infrastructure bootstrap.
#
# Detects Consul + Nomad, and for each missing tool prompts the user to:
#   1. Install via package manager (Debian/Ubuntu: HashiCorp apt repo;
#      RHEL/Fedora: HashiCorp yum repo) — the recommended path.
#   2. Download the official release tarball into /usr/local/bin/.
#   3. Provide a path to an existing executable.
#   4. Skip — install later.
#
# Persists the chosen Consul/Nomad executable paths to:
#   ~/.config/devatservgui/settings.json
#
# Used by:
#   - Debian .deb postinst (when stdin is a TTY)
#   - AppImage users (run once after extracting the AppImage)
#   - Manual re-run any time
#
# Re-run safe: it re-detects from scratch and only acts on missing tools.
#
# Pinned versions — bump when the GUI is tested against newer releases.

set -euo pipefail

CONSUL_VER="${CONSUL_VER:-1.20.6}"
NOMAD_VER="${NOMAD_VER:-1.9.6}"

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/devatservgui"
SETTINGS_FILE="$CONFIG_DIR/settings.json"

# ---- Pretty output -----------------------------------------------------
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    RED=$'\033[31m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
    BOLD=''; DIM=''; GREEN=''; YELLOW=''; RED=''; CYAN=''; RESET=''
fi
say()  { printf '%s\n' "$*"; }
info() { printf '%s>%s %s\n' "$CYAN" "$RESET" "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
err()  { printf '%sx%s %s\n' "$RED" "$RESET" "$*" >&2; }

# ---- Distro / package manager detection --------------------------------
detect_distro() {
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}
DISTRO="$(detect_distro)"

# Returns "apt" / "dnf" / "yum" / "" depending on what we can use to add
# the HashiCorp repo and install the binaries.
detect_pkg_manager() {
    case "$DISTRO" in
        debian|ubuntu|raspbian|linuxmint|pop)
            echo "apt" ;;
        fedora|rhel|centos|rocky|almalinux)
            command -v dnf >/dev/null 2>&1 && echo "dnf" || echo "yum" ;;
        *)
            command -v apt-get >/dev/null 2>&1 && echo "apt" \
                || (command -v dnf >/dev/null 2>&1 && echo "dnf") \
                || (command -v yum >/dev/null 2>&1 && echo "yum") \
                || echo "" ;;
    esac
}
PKG_MGR="$(detect_pkg_manager)"

need_sudo() {
    [[ $EUID -ne 0 ]] && command -v sudo >/dev/null 2>&1
}
sudo_run() {
    if [[ $EUID -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

# ---- Detection ---------------------------------------------------------
detect_tool() {
    local tool="$1"
    local path
    if path="$(command -v "$tool" 2>/dev/null)"; then
        echo "$path"
        return 0
    fi
    for candidate in /usr/local/bin/$tool /usr/bin/$tool /opt/hashicorp/$tool/bin/$tool; do
        if [[ -x "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

# ---- HashiCorp install paths -------------------------------------------
add_hashicorp_apt_repo() {
    info "Adding HashiCorp apt repository..."
    sudo_run apt-get update -qq
    sudo_run apt-get install -y -qq gpg lsb-release curl
    curl -fsSL https://apt.releases.hashicorp.com/gpg \
        | sudo_run gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
    local codename
    codename="$(lsb_release -cs)"
    echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
https://apt.releases.hashicorp.com $codename main" \
        | sudo_run tee /etc/apt/sources.list.d/hashicorp.list >/dev/null
    sudo_run apt-get update -qq
}

add_hashicorp_yum_repo() {
    info "Adding HashiCorp yum repository..."
    sudo_run "$PKG_MGR" install -y -q yum-utils
    sudo_run yum-config-manager \
        --add-repo https://rpm.releases.hashicorp.com/RHEL/hashicorp.repo
}

install_via_pkg_mgr() {
    local tool="$1"
    local pinned_ver="$2"
    case "$PKG_MGR" in
        apt)
            add_hashicorp_apt_repo
            # Pin the version when possible — apt syntax: pkg=ver-1
            if sudo_run apt-cache madison "$tool" | grep -q "$pinned_ver"; then
                sudo_run apt-get install -y "${tool}=${pinned_ver}-1" \
                    || sudo_run apt-get install -y "$tool"
            else
                warn "Pinned $tool version $pinned_ver not in apt — installing latest."
                sudo_run apt-get install -y "$tool"
            fi
            ;;
        dnf|yum)
            add_hashicorp_yum_repo
            sudo_run "$PKG_MGR" install -y "${tool}-${pinned_ver}" \
                || sudo_run "$PKG_MGR" install -y "$tool"
            ;;
        *)
            err "No supported package manager — falling back to tarball install."
            install_via_tarball "$tool" "$pinned_ver"
            return $?
            ;;
    esac
}

install_via_tarball() {
    local tool="$1"
    local pinned_ver="$2"
    local arch
    case "$(uname -m)" in
        x86_64)  arch="amd64" ;;
        aarch64|arm64) arch="arm64" ;;
        *) err "Unsupported architecture: $(uname -m)"; return 1 ;;
    esac
    local zip="${tool}_${pinned_ver}_linux_${arch}.zip"
    local url="https://releases.hashicorp.com/${tool}/${pinned_ver}/${zip}"
    local tmp
    tmp="$(mktemp -d)"
    info "Downloading $url"
    curl -fsSL "$url" -o "$tmp/$zip"
    info "Extracting to /usr/local/bin/$tool"
    (cd "$tmp" && unzip -oq "$zip")
    sudo_run install -m 0755 "$tmp/$tool" "/usr/local/bin/$tool"
    rm -rf "$tmp"
}

# ---- Per-tool prompt ---------------------------------------------------
# Args: tool_name, pinned_version
# Sets global RESULT_PATH on success (empty if skipped).
prompt_for_tool() {
    local tool="$1"
    local pinned_ver="$2"
    RESULT_PATH=""

    local detected
    if detected="$(detect_tool "$tool")"; then
        ok "$tool already installed at: $detected"
        RESULT_PATH="$detected"
        return 0
    fi

    warn "$tool not found on this system."
    say
    say "  ${BOLD}Choose how to install $tool $pinned_ver:${RESET}"
    say "    ${CYAN}1${RESET}) Install via $PKG_MGR (HashiCorp official repo) ${DIM}— recommended${RESET}"
    say "    ${CYAN}2${RESET}) Download release tarball into /usr/local/bin/"
    say "    ${CYAN}3${RESET}) Provide path to an existing $tool executable"
    say "    ${CYAN}4${RESET}) Skip — install later"
    say
    local choice
    while true; do
        read -r -p "  Choice [1-4, default 1]: " choice
        choice="${choice:-1}"
        case "$choice" in
            1)
                if [[ -z "$PKG_MGR" ]]; then
                    err "No supported package manager detected — pick option 2 or 3."
                    continue
                fi
                if install_via_pkg_mgr "$tool" "$pinned_ver"; then
                    RESULT_PATH="$(detect_tool "$tool" || true)"
                    [[ -n "$RESULT_PATH" ]] && ok "$tool installed at: $RESULT_PATH"
                fi
                return 0
                ;;
            2)
                install_via_tarball "$tool" "$pinned_ver" \
                    && RESULT_PATH="/usr/local/bin/$tool" \
                    && ok "$tool installed at: $RESULT_PATH"
                return 0
                ;;
            3)
                local provided
                read -r -p "  Path to $tool executable: " provided
                if [[ -x "$provided" ]]; then
                    RESULT_PATH="$provided"
                    ok "Using $tool at: $RESULT_PATH"
                    return 0
                fi
                err "Not executable: $provided"
                ;;
            4)
                warn "$tool: skipped — re-run this script when ready."
                return 0
                ;;
            *)
                err "Invalid choice: $choice"
                ;;
        esac
    done
}

# ---- settings.json persistence ----------------------------------------
save_to_settings() {
    local consul_path="$1"
    local nomad_path="$2"
    mkdir -p "$CONFIG_DIR"

    if command -v jq >/dev/null 2>&1 && [[ -f "$SETTINGS_FILE" ]]; then
        local tmp
        tmp="$(mktemp)"
        jq --arg c "$consul_path" --arg n "$nomad_path" '
            (if $c != "" then .consulPath = $c else . end) |
            (if $n != "" then .nomadPath  = $n else . end)
        ' "$SETTINGS_FILE" > "$tmp" && mv "$tmp" "$SETTINGS_FILE"
    else
        # No jq, or no existing file — write a minimal JSON document.
        # Simple emit: only include fields that have values.
        {
            printf '{\n'
            local first=1
            if [[ -n "$consul_path" ]]; then
                printf '  "consulPath": "%s"' "$consul_path"
                first=0
            fi
            if [[ -n "$nomad_path" ]]; then
                [[ $first -eq 0 ]] && printf ',\n'
                printf '  "nomadPath": "%s"' "$nomad_path"
            fi
            printf '\n}\n'
        } > "$SETTINGS_FILE"
    fi
    ok "Saved Consul/Nomad paths to $SETTINGS_FILE"
}

# ---- Main --------------------------------------------------------------
main() {
    say
    say "${BOLD}DevAtServGUI infrastructure bootstrap${RESET}"
    say "${DIM}Distro: $DISTRO  |  Package manager: ${PKG_MGR:-none}${RESET}"
    say

    if ! [[ -t 0 ]]; then
        err "This script needs an interactive terminal. Re-run from a shell:"
        err "    bash $(realpath "$0")"
        exit 2
    fi

    prompt_for_tool consul "$CONSUL_VER"
    local consul_path="$RESULT_PATH"

    prompt_for_tool nomad  "$NOMAD_VER"
    local nomad_path="$RESULT_PATH"

    save_to_settings "$consul_path" "$nomad_path"

    say
    ok "Bootstrap complete."
    [[ -z "$consul_path" || -z "$nomad_path" ]] && warn \
        "One or both tools were skipped — re-run this script after installing them."
}

main "$@"
