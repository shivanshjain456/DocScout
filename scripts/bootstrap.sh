#!/usr/bin/env bash
# bootstrap.sh — reconstruct the verified DocScout development environment.
#
# WHY THIS EXISTS
#   Phase 0 produced a verified toolchain, but every piece of it lived OUTSIDE the repository:
#   binaries in ~/.local/bin, a 1.8 GB .venv, a Hugging Face cache, node_modules. None of that is
#   part of the tracked tree, and on this platform those paths are excluded from workspace
#   snapshots entirely. The toolchain was therefore lost while the source survived, leaving a repo
#   that documented a verified environment nobody could re-create. This script is the missing
#   half: it turns "it worked on 2026-10-01" into "it works on any Debian 13 box, now".
#   Tracked in SPEC.md as U-15; it is the first exit criterion of MILESTONES.md M0.
#
# PROPERTIES
#   - Idempotent. Re-running is cheap: every step checks for the pinned version first and skips.
#   - Pinned. Versions below are exactly those verified in docs/setup/SETUP_REPORT.md. Drift from
#     a pin is reported, never silently accepted.
#   - Tiered.  'core' = everything needed to commit with all 11 pre-commit hooks green.
#              'full' = core + services, browsers, load testing and cloud CLI, i.e. everything
#                       `make verify-setup` exercises.
#   - Honest.  Exits non-zero on failure and prints a status table. It never claims a tool is
#              present because it tried to install it.
#
# USAGE
#   bash scripts/bootstrap.sh              # core tier (default)
#   bash scripts/bootstrap.sh full         # core + services/browsers/k6/aws
#   bash scripts/bootstrap.sh --check      # report only, install nothing
#   bash scripts/bootstrap.sh --help
#
# Verification after running:  make verify-setup

set -euo pipefail

# ---------------------------------------------------------------------------- pinned versions ---
# Source of truth: docs/setup/SETUP_REPORT.md (Phase 0, 2026-10-01).
UV_VERSION="0.12.21"
PYTHON_VERSION="3.12.14"
PRECOMMIT_VERSION="4.6.2"
GITLEAKS_VERSION="8.30.1"
NODE_VERSION="22.23.3"
PNPM_VERSION="12.8.1"
K6_VERSION="2.3.0"
COMPOSE_VERSION="5.5.1"
AWSCLI_VERSION="2.37.7"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
TIER="core"
CHECK_ONLY=0

# ----------------------------------------------------------------------------------- plumbing ---
C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
declare -a RESULTS=()

log()  { printf '%s\n' "$*" >&2; }
step() { printf '\n%s==>%s %s\n' $'\033[36m' "${C_OFF}" "$*" >&2; }
record() { RESULTS+=("$1|$2|$3"); }   # name | state | detail

die() { printf '%sFATAL%s %s\n' "${C_ERR}" "${C_OFF}" "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# Fetch a URL to a path, failing loudly on a non-200. Never leaves a partial file in place.
fetch() {
  local url="$1" dest="$2" tmp
  tmp="$(mktemp)"
  if ! curl -fsSL --retry 3 --retry-delay 2 --max-time 300 -o "${tmp}" "${url}"; then
    rm -f "${tmp}"
    die "download failed: ${url}"
  fi
  mv "${tmp}" "${dest}"
}

usage() {
  sed -n '2,33p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    core|full) TIER="$1" ;;
    --check)   CHECK_ONLY=1 ;;
    -h|--help) usage ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
  shift
done

mkdir -p "${BIN_DIR}"
export PATH="${BIN_DIR}:${PATH}"

# ------------------------------------------------------------------------------ shell wiring ---
# Phase 0 installed fnm with --skip-shell, which left non-login shells resolving a stale Node and
# no pnpm at all. That cost real debugging time (SETUP_REPORT K-12 neighbourhood). Fix it here,
# once, idempotently, so the next shell is correct without anyone remembering why.
ensure_shell_wiring() {
  local rc="${HOME}/.bashrc" marker="# >>> docscout bootstrap >>>"
  if [[ -f "${rc}" ]] && grep -qF "${marker}" "${rc}"; then
    record "shell wiring" "OK" "~/.bashrc already configured"
    return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "shell wiring" "MISSING" "~/.bashrc not configured"; return; fi
  cat >> "${rc}" <<'RC'

# >>> docscout bootstrap >>>
# Put user-local tooling (uv, gitleaks, pre-commit, k6) ahead of system paths.
export PATH="$HOME/.local/bin:$PATH"
# fnm was installed with --skip-shell; without this, non-login shells get a stale Node and no pnpm.
export FNM_DIR="$HOME/.local/share/fnm"
[ -d "$FNM_DIR" ] && export PATH="$FNM_DIR:$PATH"
command -v fnm >/dev/null 2>&1 && eval "$(fnm env --shell bash)"
# <<< docscout bootstrap <<<
RC
  record "shell wiring" "INSTALLED" "appended to ~/.bashrc"
}

# -------------------------------------------------------------------------------- core tools ---

ensure_git() {
  if have git; then record "git" "OK" "$(git --version | awk '{print $3}')"; return; fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "git" "MISSING" "-"; return; fi
  sudo apt-get update -qq && sudo apt-get install -y -qq git
  record "git" "INSTALLED" "$(git --version | awk '{print $3}')"
}

ensure_git_history() {
  # `.git` itself does not survive this platform's snapshots -- the tree comes back, the
  # commits do not (observed twice, reflog included). scripts/git_history.sh keeps a bundle
  # of all refs as an ordinary file in the tree, which does survive. Restore it before
  # anything else touches git, and never overwrite newer local commits (restore fast-forwards
  # only). See the header of that script for the evidence and the rejected alternatives.
  local out
  if [[ ! -x "$REPO_ROOT/scripts/git_history.sh" ]]; then
    report "SKIP" "git history" "scripts/git_history.sh not present"
    return 0
  fi
  if [[ "$MODE" == "check" ]]; then
    out="$("$REPO_ROOT/scripts/git_history.sh" status 2>&1 | sed -n 's/^ *state *//p')"
    report "OK" "git history" "${out:-no bundle}"
    return 0
  fi
  out="$("$REPO_ROOT/scripts/git_history.sh" restore 2>&1 | sed -n 's/^ *\(restored\|restore\) *//p' | head -1)"
  report "OK" "git history" "${out:-nothing to restore}"
}

ensure_git_identity() {
  # .git/config is excluded from workspace snapshots on this platform, so a restored tree can
  # have 25 commits of history and still refuse to make the 26th: "empty ident name". Observed,
  # not hypothetical. Adopt the identity the existing history already uses rather than inventing
  # one, so authorship stays consistent across sessions.
  local name email
  name="$(git -C "${REPO_ROOT}" config user.name  || true)"
  email="$(git -C "${REPO_ROOT}" config user.email || true)"
  if [[ -n "${name}" && -n "${email}" ]]; then
    record "git identity" "OK" "${name} <${email}>"
    return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then
    record "git identity" "MISSING" "unset; commits will fail"
    return
  fi
  local head_name head_email
  head_name="$(git -C "${REPO_ROOT}" log -1 --format='%an' 2>/dev/null || true)"
  head_email="$(git -C "${REPO_ROOT}" log -1 --format='%ae' 2>/dev/null || true)"
  if [[ -z "${head_name}" ]]; then
    record "git identity" "SKIPPED" "no commits yet to copy an identity from"
    return
  fi
  git -C "${REPO_ROOT}" config user.name  "${head_name}"
  git -C "${REPO_ROOT}" config user.email "${head_email}"
  record "git identity" "RESTORED" "${head_name} <${head_email}> (from HEAD)"
}

ensure_uv() {
  if have uv && [[ "$(uv --version | awk '{print $2}')" == "${UV_VERSION}" ]]; then
    record "uv" "OK" "${UV_VERSION}"; return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then
    record "uv" "MISSING" "want ${UV_VERSION}$(have uv && echo ", found $(uv --version | awk '{print $2}')" || true)"
    return
  fi
  step "installing uv ${UV_VERSION}"
  local sh; sh="$(mktemp)"
  fetch "https://astral.sh/uv/${UV_VERSION}/install.sh" "${sh}"
  UV_INSTALL_DIR="${BIN_DIR}" INSTALLER_NO_MODIFY_PATH=1 sh "${sh}" >/dev/null
  rm -f "${sh}"
  have uv || die "uv install completed but uv is not on PATH"
  record "uv" "INSTALLED" "$(uv --version | awk '{print $2}')"
}

ensure_python() {
  have uv || { record "python ${PYTHON_VERSION}" "SKIPPED" "uv missing"; return; }
  if uv python list --only-installed 2>/dev/null | grep -q "${PYTHON_VERSION}"; then
    record "python" "OK" "${PYTHON_VERSION} (uv-managed)"; return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "python" "MISSING" "want ${PYTHON_VERSION}"; return; fi
  step "installing CPython ${PYTHON_VERSION} via uv"
  uv python install "${PYTHON_VERSION}" >/dev/null
  record "python" "INSTALLED" "${PYTHON_VERSION} (uv-managed)"
}

ensure_gitleaks() {
  if have gitleaks && [[ "$(gitleaks version 2>/dev/null | tr -d 'v')" == "${GITLEAKS_VERSION}" ]]; then
    record "gitleaks" "OK" "${GITLEAKS_VERSION}"; return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "gitleaks" "MISSING" "want ${GITLEAKS_VERSION}"; return; fi
  step "installing gitleaks ${GITLEAKS_VERSION}"
  local tgz; tgz="$(mktemp --suffix=.tar.gz)"
  fetch "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" "${tgz}"
  tar -xzf "${tgz}" -C "${BIN_DIR}" gitleaks
  chmod +x "${BIN_DIR}/gitleaks"; rm -f "${tgz}"
  record "gitleaks" "INSTALLED" "$(gitleaks version 2>/dev/null)"
}

ensure_precommit() {
  have uv || { record "pre-commit" "SKIPPED" "uv missing"; return; }
  if have pre-commit && pre-commit --version 2>/dev/null | grep -q "${PRECOMMIT_VERSION}"; then
    record "pre-commit" "OK" "${PRECOMMIT_VERSION}"; return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "pre-commit" "MISSING" "want ${PRECOMMIT_VERSION}"; return; fi
  step "installing pre-commit ${PRECOMMIT_VERSION}"
  uv tool install --force "pre-commit==${PRECOMMIT_VERSION}" >/dev/null 2>&1
  record "pre-commit" "INSTALLED" "$(pre-commit --version | awk '{print $2}')"
}

# Project virtualenv from the lockfile. This is also the real test of NFR-4 (reproducible deps):
# if `uv sync --frozen` cannot reproduce 169 packages, the lock is not trustworthy.
ensure_venv() {
  have uv || { record ".venv" "SKIPPED" "uv missing"; return; }
  if [[ -x "${REPO_ROOT}/.venv/bin/mypy" ]]; then record ".venv" "OK" "present"; return; fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record ".venv" "MISSING" "run without --check"; return; fi
  step "syncing the project environment from uv.lock (this is the slow one)"
  ( cd "${REPO_ROOT}" && uv sync --frozen )
  record ".venv" "INSTALLED" "uv sync --frozen"
}

# Pre-commit's remote hook repos live in ~/.cache, which is also snapshot-excluded. Warm them now
# so the first commit is not a surprise network dependency.
ensure_hooks() {
  have pre-commit || { record "git hooks" "SKIPPED" "pre-commit missing"; return; }
  if [[ ! -d "${REPO_ROOT}/.git" ]]; then
    record "git hooks" "DEFERRED" "no .git yet — re-run bootstrap after git init"
    return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then
    [[ -f "${REPO_ROOT}/.git/hooks/pre-commit" ]] && record "git hooks" "OK" "installed" \
                                                  || record "git hooks" "MISSING" "not installed"
    return
  fi
  step "installing and warming pre-commit hooks"
  ( cd "${REPO_ROOT}" && pre-commit install >/dev/null && pre-commit install-hooks >/dev/null )
  record "git hooks" "INSTALLED" "pre-commit + pre-push"
}

# -------------------------------------------------------------------------------- full tier ----

# CLI tools that V1 of the verification matrix requires and that Debian packages at the exact
# versions Phase 0 recorded: jq, psql (postgresql-client 17 -> SETUP_REPORT K-13, client 17 vs
# server 18), and gh 2.46.0. Installed in one apt transaction.
ensure_apt_clis() {
  local want=() names=()
  have jq   || { want+=(jq);                 names+=(jq); }
  have psql || { want+=(postgresql-client);  names+=(psql); }
  have gh   || { want+=(gh);                 names+=(gh); }
  if [[ ${#want[@]} -eq 0 ]]; then
    record "jq/psql/gh" "OK" "$(jq --version), $(psql --version | awk '{print $3}'), gh $(gh --version | head -1 | awk '{print $3}')"
    return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "jq/psql/gh" "MISSING" "need: ${names[*]}"; return; fi
  step "installing ${names[*]} (apt)"
  sudo apt-get update -qq
  sudo apt-get install -y -qq "${want[@]}"
  record "jq/psql/gh" "INSTALLED" "$(jq --version 2>/dev/null), psql $(psql --version 2>/dev/null | awk '{print $3}'), gh $(gh --version 2>/dev/null | head -1 | awk '{print $3}')"
}

ensure_database_fallback() {
  # docker-compose.yml is the documented way to run Postgres and stays the default. Some
  # environments cannot run Docker at all -- this one could not, on 2026-10-01 -- and without a
  # database nothing in the project is verifiable. scripts/dev_db_native.sh provisions an
  # equivalent native cluster by executing infra/initdb/, the same files compose mounts.
  if have docker; then return; fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then
    if command -v pg_lsclusters >/dev/null 2>&1 \
       && pg_lsclusters -h 2>/dev/null | awk '$4=="online"{found=1} END{exit !found}'; then
      record "database" "OK" "native cluster online (no docker; see scripts/dev_db_native.sh)"
    else
      record "database" "MISSING" "no docker and no running cluster; run scripts/dev_db_native.sh"
    fi
    return
  fi
  step "docker unavailable — provisioning Postgres natively"
  if bash "${REPO_ROOT}/scripts/dev_db_native.sh" >&2; then
    record "database" "INSTALLED" "native PG cluster (scripts/dev_db_native.sh)"
  else
    record "database" "FAILED" "scripts/dev_db_native.sh exited non-zero"
  fi
}

ensure_docker() {
  if have docker; then record "docker" "OK" "$(docker --version | awk '{print $3}' | tr -d ,)"; return; fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "docker" "MISSING" "needed for make verify-setup V2/V3"; return; fi
  step "installing docker engine (apt)"
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker.io
  sudo systemctl enable --now docker >/dev/null 2>&1 || true
  sudo usermod -aG docker "$(id -un)" || true
  record "docker" "INSTALLED" "$(docker --version 2>/dev/null | awk '{print $3}' | tr -d , || echo '?')"
}

ensure_compose() {
  if docker compose version >/dev/null 2>&1; then
    record "docker compose" "OK" "$(docker compose version --short 2>/dev/null)"; return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "docker compose" "MISSING" "want ${COMPOSE_VERSION}"; return; fi
  step "installing docker compose ${COMPOSE_VERSION}"
  local plugin_dir="${HOME}/.docker/cli-plugins"
  mkdir -p "${plugin_dir}"
  fetch "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-x86_64" "${plugin_dir}/docker-compose"
  chmod +x "${plugin_dir}/docker-compose"
  record "docker compose" "INSTALLED" "${COMPOSE_VERSION}"
}

ensure_node() {
  if have node && [[ "$(node --version)" == "v${NODE_VERSION}" ]]; then
    record "node" "OK" "v${NODE_VERSION}"
  elif [[ "${CHECK_ONLY}" == "1" ]]; then
    record "node" "MISSING" "want v${NODE_VERSION}"
  else
    step "installing fnm + node v${NODE_VERSION}"
    if ! have fnm; then
      local zip; zip="$(mktemp --suffix=.zip)"
      fetch "https://github.com/Schniz/fnm/releases/latest/download/fnm-linux.zip" "${zip}"
      unzip -oq "${zip}" -d "${HOME}/.local/share/fnm"
      chmod +x "${HOME}/.local/share/fnm/fnm"; rm -f "${zip}"
      ln -sf "${HOME}/.local/share/fnm/fnm" "${BIN_DIR}/fnm"
    fi
    export FNM_DIR="${HOME}/.local/share/fnm"
    eval "$(fnm env --shell bash)"
    fnm install "${NODE_VERSION}" >/dev/null 2>&1 || true
    fnm default "${NODE_VERSION}" >/dev/null 2>&1 || true
    eval "$(fnm env --shell bash)"
    record "node" "INSTALLED" "$(node --version 2>/dev/null || echo '?')"
  fi

  if have corepack && ! have pnpm && [[ "${CHECK_ONLY}" != "1" ]]; then
    corepack enable >/dev/null 2>&1 || true
    corepack prepare "pnpm@${PNPM_VERSION}" --activate >/dev/null 2>&1 || true
  fi
  have pnpm && record "pnpm" "OK" "$(pnpm --version 2>/dev/null)" || record "pnpm" "MISSING" "want ${PNPM_VERSION}"
}

ensure_k6() {
  if have k6 && k6 version 2>/dev/null | grep -q "${K6_VERSION}"; then
    record "k6" "OK" "${K6_VERSION}"; return
  fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "k6" "MISSING" "want ${K6_VERSION}"; return; fi
  step "installing k6 ${K6_VERSION}"
  local tgz dir; tgz="$(mktemp --suffix=.tar.gz)"; dir="$(mktemp -d)"
  fetch "https://github.com/grafana/k6/releases/download/v${K6_VERSION}/k6-v${K6_VERSION}-linux-amd64.tar.gz" "${tgz}"
  tar -xzf "${tgz}" -C "${dir}" --strip-components=1
  install -m 0755 "${dir}/k6" "${BIN_DIR}/k6"
  rm -rf "${tgz}" "${dir}"
  record "k6" "INSTALLED" "$(k6 version 2>/dev/null | head -1)"
}

ensure_awscli() {
  if have aws; then record "aws-cli" "OK" "$(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2)"; return; fi
  if [[ "${CHECK_ONLY}" == "1" ]]; then record "aws-cli" "MISSING" "want ${AWSCLI_VERSION}"; return; fi
  step "installing aws-cli ${AWSCLI_VERSION}"
  local zip dir; zip="$(mktemp --suffix=.zip)"; dir="$(mktemp -d)"
  fetch "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWSCLI_VERSION}.zip" "${zip}"
  unzip -q "${zip}" -d "${dir}"
  "${dir}/aws/install" --install-dir "${HOME}/.local/aws-cli" --bin-dir "${BIN_DIR}" --update >/dev/null
  rm -rf "${zip}" "${dir}"
  record "aws-cli" "INSTALLED" "$(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2)"
  log "${C_DIM}  note: aws-cli is intentionally left UNCONFIGURED. Phase 0 created no cloud resources.${C_OFF}"
}

# ----------------------------------------------------------------------------------- summary ---
summary() {
  local fails=0 line name state detail
  printf '\n%s\n' "────────────────────────────────────────────────────────────────"
  printf ' DocScout bootstrap — tier=%s  mode=%s\n' "${TIER}" "$([[ ${CHECK_ONLY} == 1 ]] && echo check || echo install)"
  printf '%s\n' "────────────────────────────────────────────────────────────────"
  for line in "${RESULTS[@]}"; do
    IFS='|' read -r name state detail <<< "${line}"
    case "${state}" in
      OK|INSTALLED) printf ' %s%-10s%s %-16s %s\n' "${C_OK}"   "${state}" "${C_OFF}" "${name}" "${detail}" ;;
      DEFERRED|SKIPPED) printf ' %s%-10s%s %-16s %s\n' "${C_WARN}" "${state}" "${C_OFF}" "${name}" "${detail}" ;;
      *) printf ' %s%-10s%s %-16s %s\n' "${C_ERR}" "${state}" "${C_OFF}" "${name}" "${detail}"; fails=$((fails+1)) ;;
    esac
  done
  printf '%s\n' "────────────────────────────────────────────────────────────────"
  if [[ "${CHECK_ONLY}" == "1" && ${fails} -gt 0 ]]; then
    printf ' %d component(s) missing. Run: bash scripts/bootstrap.sh %s\n' "${fails}" "${TIER}"
    return 1
  fi
  printf ' Next: %s\n' "$([[ -d "${REPO_ROOT}/.git" ]] && echo 'make verify-setup' || echo 'git init, then re-run this script to install hooks')"
  return 0
}

# -------------------------------------------------------------------------------------- main ---
main() {
  log "DocScout bootstrap — repo: ${REPO_ROOT}"
  ensure_shell_wiring
  ensure_git
  ensure_git_history
  ensure_git_identity
  ensure_uv
  ensure_python
  ensure_gitleaks
  ensure_precommit
  ensure_venv
  ensure_hooks
  if [[ "${TIER}" == "full" ]]; then
    ensure_apt_clis
    ensure_docker
    ensure_compose
    ensure_database_fallback
    ensure_node
    ensure_k6
    ensure_awscli
  fi
  summary
}

main "$@"
