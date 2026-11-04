#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: install.sh {gitleaks|actionlint|shellcheck}\n' >&2
  exit 1
fi

tool="$1"
version_args=(--version)
case "$tool" in
  gitleaks)
    version=8.30.1
    repository=gitleaks/gitleaks
    archive_name="gitleaks_${version}_linux_x64.tar.gz"
    archive_binary=gitleaks
    checksum=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
    version_args=(version)
    ;;
  actionlint)
    version=1.7.12
    repository=rhysd/actionlint
    archive_name="actionlint_${version}_linux_amd64.tar.gz"
    archive_binary=actionlint
    checksum=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
    ;;
  shellcheck)
    version=0.11.0
    repository=koalaman/shellcheck
    archive_name="shellcheck-v${version}.linux.x86_64.tar.xz"
    archive_binary="shellcheck-v${version}/shellcheck"
    checksum=8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198
    ;;
  *)
    printf 'Unsupported native tool: choose gitleaks, actionlint, or shellcheck.\n' >&2
    exit 1
    ;;
esac

if [[ "${RUNNER_OS:-}" != Linux || "${RUNNER_ARCH:-}" != X64 || "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  printf 'Native CI tools require a Linux X64 GitHub runner; use installed tools locally.\n' >&2
  exit 1
fi

if [[ ! -d "${RUNNER_TEMP:?RUNNER_TEMP must name the runner temporary directory}" || ! -f "${GITHUB_PATH:?GITHUB_PATH must name the runner path file}" ]]; then
  printf 'Runner temporary directory and path file must already exist.\n' >&2
  exit 1
fi
if [[ "$RUNNER_TEMP" != /* || "$RUNNER_TEMP" == *$'\n'* ]]; then
  printf 'RUNNER_TEMP must be an absolute path without newlines.\n' >&2
  exit 1
fi

for required_command in curl sha256sum tar install mktemp; do
  if ! command -v "$required_command" >/dev/null; then
    printf 'Required native tool installer command is missing: %s\n' "$required_command" >&2
    exit 1
  fi
done

work_dir="$(mktemp -d "${RUNNER_TEMP}/native-tool.XXXXXX")"
trap 'rm -rf -- "$work_dir"' EXIT
archive="${work_dir}/${archive_name}"
url="https://github.com/${repository}/releases/download/v${version}/${archive_name}"
curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
  --tlsv1.2 --connect-timeout 10 --max-time 120 --output "$archive" "$url"
if ! printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check --status; then
  printf 'Checksum mismatch for the approved %s download.\n' "$tool" >&2
  exit 1
fi
tar --extract --file "$archive" --directory "$work_dir" "$archive_binary"

tool_bin="${RUNNER_TEMP}/tool-bin"
mkdir -p -- "$tool_bin"
install -m 0755 "${work_dir}/${archive_binary}" "${tool_bin}/${tool}"
version_output="$("${tool_bin}/${tool}" "${version_args[@]}")"
if [[ "$tool" == shellcheck ]]; then
  actual_version="$(printf '%s\n' "$version_output" | sed -n 's/^version: //p')"
else
  actual_version="${version_output%%$'\n'*}"
fi
if [[ "$actual_version" != "$version" ]]; then
  printf 'Installed %s version does not match the approved pin.\n' "$tool" >&2
  exit 1
fi
printf '%s\n' "$version_output"
printf '%s\n' "$tool_bin" >> "$GITHUB_PATH"
