#!/usr/bin/env bash
#
# specs-agent installer
#
# Creates a virtual environment, installs the package, and sets up
# a CLI symlink and desktop shortcut so you can launch specs-agent
# from anywhere.
#
# Usage:
#   ./install.sh              # Install to ~/.specs-agent
#   ./install.sh --uninstall  # Remove everything
#
set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────

APP_NAME="specs-agent"
INSTALL_DIR="${HOME}/.specs-agent"
VENV_DIR="${INSTALL_DIR}/venv"
CONFIG_FILE="${INSTALL_DIR}/config.yaml"
BIN_LINK="/usr/local/bin/${APP_NAME}"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Theme Colors ─────────────────────────────────────────────────────────────

BG='\033[48;2;26;27;46m'      # #1a1b2e
FG='\033[38;2;192;192;208m'   # #c0c0d0
GREEN='\033[38;2;85;204;85m'  # #55cc55
GOLD='\033[38;2;204;153;68m'  # #cc9944
CYAN='\033[38;2;85;170;204m'  # #55aacc
DIM='\033[38;2;122;122;154m'  # #7a7a9a
RED='\033[38;2;204;68;68m'    # #cc4444
STAR='\033[38;2;102;102;136m' # #666688
BOLD='\033[1m'
NC='\033[0m'

info()    { printf "  ${DIM}%s${NC}\n" "$*"; }
success() { printf "  ${GREEN}+${NC} %s\n" "$*"; }
warn()    { printf "  ${GOLD}!${NC} %s\n" "$*"; }
error()   { printf "  ${RED}x${NC} %s\n" "$*" >&2; }

step() {
    printf "\n"
    printf "  ${STAR}. . . . . . . . . . . . . . . . . . . .${NC}\n"
    printf "  ${GREEN}${BOLD}%s${NC}\n" "$*"
    printf "  ${STAR}. . . . . . . . . . . . . . . . . . . .${NC}\n"
}

show_banner() {
    printf "\n"
    printf "${GREEN}"
    cat << 'BANNER'

           ░█              ░█            ░█
         ░█              ░█  ░█            ░█
       ░█              ░█      ░█            ░█
     ░█              ░█          ░█        ░█░█
   ░█             ░█              ░█      ░█  ░█
 ░█░█           ░█                  ░█    ░█  ░█
   ░█             ░█              ░█      ░█  ░█
     ░█              ░█          ░█        ░█░█
       ░█              ░█      ░█            ░█
         ░█              ░█  ░█            ░█
           ░█              ░█            ░█
BANNER
    printf "${NC}"
    printf "${GREEN}${BOLD}        S  P  E  C  S     I  N  V  A  D  E  R  S${NC}\n"
    printf "${GOLD}              ░█░ Defend your APIs ░█░${NC}\n"
    printf "${DIM}                    installer v1.0${NC}\n"
    printf "\n"
}

show_uninstall_banner() {
    printf "\n"
    printf "${RED}"
    cat << 'BANNER'
     ░█           ░█         ░█
   ░█           ░█  ░█         ░█       UNINSTALLING...
 ░█░█         ░█      ░█    ░█░█
   ░█           ░█  ░█         ░█
     ░█           ░█         ░█
BANNER
    printf "${NC}\n"
}

# ── Helpers ──────────────────────────────────────────────────────────────────

find_python() {
    local candidates=("python3.13" "python3.12" "python3.11" "python3")
    for cmd in "${candidates[@]}"; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'  2>/dev/null)" || continue
            local major minor
            major="${ver%%.*}"
            minor="${ver#*.}"
            if [[ "$major" -ge "$MIN_PYTHON_MAJOR" && "$minor" -ge "$MIN_PYTHON_MINOR" ]]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

check_prerequisites() {
    step "SCANNING SYSTEM"

    # Python
    PYTHON_BIN="$(find_python)" || {
        error "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required but not found."
        error "Install it from https://www.python.org/downloads/"
        exit 1
    }
    local py_version
    py_version="$("$PYTHON_BIN" --version 2>&1)"
    success "${py_version} detected (${PYTHON_BIN})"

    # venv module
    "$PYTHON_BIN" -c "import venv" 2>/dev/null || {
        error "Python venv module not available."
        error "On Debian/Ubuntu: sudo apt install python3-venv"
        exit 1
    }
    success "venv module available"

    # pip (will be bootstrapped by venv, but check ensurepip)
    "$PYTHON_BIN" -c "import ensurepip" 2>/dev/null || {
        warn "ensurepip not available — pip will need to be installed manually in the venv."
    }

    # Source repo
    if [[ ! -f "${REPO_DIR}/pyproject.toml" ]]; then
        error "Cannot find pyproject.toml in ${REPO_DIR}"
        error "Run this script from the specs-agent repository root."
        exit 1
    fi
    success "Source repo locked at ${REPO_DIR}"
}

create_venv() {
    step "DEPLOYING ENVIRONMENT"

    if [[ -d "$VENV_DIR" ]]; then
        warn "Existing venv found at ${VENV_DIR}"
        read -rp "  Recreate it? [y/N] " answer
        if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
            info "Removing old venv..."
            rm -rf "$VENV_DIR"
        else
            info "Keeping existing venv"
            return 0
        fi
    fi

    "$PYTHON_BIN" -m venv "$VENV_DIR"
    success "Venv created at ${VENV_DIR}"

    info "Upgrading pip..."
    "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel --quiet
    success "pip upgraded"
}

install_package() {
    step "LOADING WEAPONS"

    info "Installing ${APP_NAME} and dependencies..."
    "${VENV_DIR}/bin/pip" install -e "${REPO_DIR}" --quiet
    local version
    version="$("${VENV_DIR}/bin/python" -c "from specs_agent import __version__; print(__version__)")"
    success "${APP_NAME} v${version} armed"
}

run_tests() {
    step "RUNNING DIAGNOSTICS"

    if [[ -d "${REPO_DIR}/tests" ]]; then
        info "Installing test dependencies..."
        "${VENV_DIR}/bin/pip" install -e "${REPO_DIR}[dev]" --quiet

        info "Running test suite..."
        if "${VENV_DIR}/bin/python" -m pytest "${REPO_DIR}/tests/" -q --tb=line 2>&1 | tail -5; then
            success "All systems operational"
        else
            warn "Some tests failed — the app may still work, check output above"
        fi
    else
        info "No tests directory found, skipping"
    fi
}

setup_config() {
    step "CONFIGURING BASE"

    mkdir -p "$INSTALL_DIR"
    mkdir -p "${INSTALL_DIR}/reports"

    if [[ -f "$CONFIG_FILE" ]]; then
        info "Config already exists at ${CONFIG_FILE} — not overwriting"
    else
        if [[ -f "${REPO_DIR}/config/default_config.yaml" ]]; then
            cp "${REPO_DIR}/config/default_config.yaml" "$CONFIG_FILE"
            success "Config deployed to ${CONFIG_FILE}"
        else
            cat > "$CONFIG_FILE" <<'YAML'
version: 1
defaults:
  timeout_seconds: 30
  follow_redirects: true
  verify_ssl: true
performance:
  concurrent_users: 10
  duration_seconds: 30
  latency_p95_threshold_ms: 2000
auth_presets:
  - name: "Bearer Token"
    type: bearer
    value: ""
recent_specs: []
reports:
  output_dir: "~/.specs-agent/reports"
  format: "html"
theme: "dark"
YAML
            success "Config deployed to ${CONFIG_FILE}"
        fi
    fi
}

create_symlink() {
    step "CREATING LAUNCH CODES"

    local target="${VENV_DIR}/bin/${APP_NAME}"
    if [[ ! -f "$target" ]]; then
        target="${INSTALL_DIR}/bin/${APP_NAME}"
        mkdir -p "${INSTALL_DIR}/bin"
        cat > "$target" <<WRAPPER
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/python" -m specs_agent "\$@"
WRAPPER
        chmod +x "$target"
    fi

    if [[ -L "$BIN_LINK" ]]; then
        info "Removing existing symlink at ${BIN_LINK}"
        sudo rm -f "$BIN_LINK"
    fi

    if [[ -d "/usr/local/bin" ]] && sudo ln -sf "$target" "$BIN_LINK" 2>/dev/null; then
        success "Command ready: ${BIN_LINK}"
    else
        local user_bin="${HOME}/.local/bin"
        mkdir -p "$user_bin"
        ln -sf "$target" "${user_bin}/${APP_NAME}"
        success "Command ready: ${user_bin}/${APP_NAME}"
        if [[ ":$PATH:" != *":${user_bin}:"* ]]; then
            warn "${user_bin} is not in your PATH."
            warn "Add to your shell profile: export PATH=\"\${HOME}/.local/bin:\${PATH}\""
        fi
    fi
}

create_desktop_shortcut() {
    step "PLACING SHORTCUT ON DECK"

    local os_type
    os_type="$(uname -s)"

    case "$os_type" in
        Darwin) _create_macos_shortcut ;;
        Linux)  _create_linux_shortcut ;;
        *)      warn "Desktop shortcuts not supported on ${os_type}" ;;
    esac
}

_create_macos_shortcut() {
    local app_dir="${HOME}/Desktop/${APP_NAME}.command"

    cat > "$app_dir" <<SCRIPT
#!/usr/bin/env bash
# specs-agent launcher — double-click to open
cd "\${HOME}"
exec "${VENV_DIR}/bin/python" -m specs_agent "\$@"
SCRIPT
    chmod +x "$app_dir"
    success "Desktop launcher: ${app_dir}"

    local shell_rc="${HOME}/.zshrc"
    [[ -f "${HOME}/.bashrc" && ! -f "$shell_rc" ]] && shell_rc="${HOME}/.bashrc"

    if [[ -f "$shell_rc" ]]; then
        if ! grep -q "alias ${APP_NAME}=" "$shell_rc" 2>/dev/null; then
            printf '\n# specs-agent\nalias %s="%s/bin/python -m specs_agent"\n' \
                "$APP_NAME" "$VENV_DIR" >> "$shell_rc"
            success "Shell alias added to ${shell_rc}"
        else
            info "Shell alias already exists in ${shell_rc}"
        fi
    fi
}

_create_linux_shortcut() {
    local desktop_dir="${HOME}/.local/share/applications"
    mkdir -p "$desktop_dir"

    local desktop_file="${desktop_dir}/${APP_NAME}.desktop"
    local icon_src="${REPO_DIR}/assets/icon.png"
    local icon_dest="${INSTALL_DIR}/icon.png"

    [[ -f "$icon_src" ]] && cp "$icon_src" "$icon_dest"

    cat > "$desktop_file" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=specs-agent
Comment=API Testing TUI — Defend your APIs from bugs
Exec=${VENV_DIR}/bin/python -m specs_agent
Icon=${icon_dest}
Terminal=true
Categories=Development;
DESKTOP

    chmod +x "$desktop_file"
    success "Desktop entry: ${desktop_file}"

    local shell_rc="${HOME}/.bashrc"
    [[ -f "${HOME}/.zshrc" ]] && shell_rc="${HOME}/.zshrc"

    if [[ -f "$shell_rc" ]]; then
        if ! grep -q "alias ${APP_NAME}=" "$shell_rc" 2>/dev/null; then
            printf '\n# specs-agent\nalias %s="%s/bin/python -m specs_agent"\n' \
                "$APP_NAME" "$VENV_DIR" >> "$shell_rc"
            success "Shell alias added to ${shell_rc}"
        else
            info "Shell alias already exists in ${shell_rc}"
        fi
    fi
}

verify_installation() {
    step "VERIFYING SYSTEMS"

    if "${VENV_DIR}/bin/python" -c "from specs_agent import __version__; print(__version__)" &>/dev/null; then
        success "Package imports OK"
    else
        error "Package import failed"
        exit 1
    fi

    local deps=("textual" "prance" "httpx" "yaml" "jsonschema" "jinja2" "click")
    for dep in "${deps[@]}"; do
        if "${VENV_DIR}/bin/python" -c "import ${dep}" 2>/dev/null; then
            success "${dep}"
        else
            error "Missing: ${dep}"
            exit 1
        fi
    done
}

print_summary() {
    printf "\n"
    printf "  ${STAR}. . . . . . . . . . . . . . . . . . . .${NC}\n"
    printf "  ${GREEN}${BOLD}MISSION READY${NC}\n"
    printf "  ${STAR}. . . . . . . . . . . . . . . . . . . .${NC}\n"
    printf "\n"
    printf "${GREEN}"
    cat << 'ART'
     ░█           ░█         ░█
   ░█           ░█  ░█         ░█       ALL SYSTEMS GO
 ░█░█         ░█      ░█    ░█░█
   ░█           ░█  ░█         ░█
     ░█           ░█         ░█
ART
    printf "${NC}\n"
    printf "  ${FG}Launch:${NC}    ${GREEN}${APP_NAME}${NC}\n"
    printf "  ${FG}With spec:${NC} ${GREEN}${APP_NAME} --spec /path/to/openapi.yaml${NC}\n"
    printf "\n"
    printf "  ${DIM}Config:${NC}    ${CONFIG_FILE}\n"
    printf "  ${DIM}Venv:${NC}      ${VENV_DIR}\n"
    printf "  ${DIM}Reports:${NC}   ${INSTALL_DIR}/reports/\n"
    printf "\n"
    if [[ "$(uname -s)" == "Darwin" ]]; then
        printf "  ${DIM}Restart your terminal or run${NC} ${CYAN}source ~/.zshrc${NC}\n"
    fi
    printf "\n"
}

# ── Uninstall ────────────────────────────────────────────────────────────────

uninstall() {
    show_uninstall_banner

    # Remove symlink
    if [[ -L "$BIN_LINK" ]]; then
        sudo rm -f "$BIN_LINK" 2>/dev/null && success "Removed ${BIN_LINK}" || warn "Could not remove ${BIN_LINK}"
    fi
    local user_bin_link="${HOME}/.local/bin/${APP_NAME}"
    if [[ -L "$user_bin_link" ]]; then
        rm -f "$user_bin_link" && success "Removed ${user_bin_link}"
    fi

    # Remove desktop shortcut
    local macos_launcher="${HOME}/Desktop/${APP_NAME}.command"
    [[ -f "$macos_launcher" ]] && rm -f "$macos_launcher" && success "Removed ${macos_launcher}"
    local linux_desktop="${HOME}/.local/share/applications/${APP_NAME}.desktop"
    [[ -f "$linux_desktop" ]] && rm -f "$linux_desktop" && success "Removed ${linux_desktop}"

    # Remove shell alias
    for rc in "${HOME}/.zshrc" "${HOME}/.bashrc"; do
        if [[ -f "$rc" ]] && grep -q "alias ${APP_NAME}=" "$rc" 2>/dev/null; then
            sed -i.bak "/# specs-agent/d;/alias ${APP_NAME}=/d" "$rc"
            rm -f "${rc}.bak"
            success "Removed alias from ${rc}"
        fi
    done

    # Remove venv (keep config)
    if [[ -d "$VENV_DIR" ]]; then
        rm -rf "$VENV_DIR"
        success "Removed venv at ${VENV_DIR}"
    fi

    printf "\n"
    info "Config preserved at ${INSTALL_DIR}/config.yaml"
    info "To remove all data: rm -rf ${INSTALL_DIR}"
    printf "\n"
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    if [[ "${1:-}" == "--uninstall" ]]; then
        show_uninstall_banner
        uninstall
        exit 0
    fi

    show_banner
    check_prerequisites
    create_venv
    install_package
    run_tests
    setup_config
    create_symlink
    create_desktop_shortcut
    verify_installation
    print_summary
}

main "$@"
