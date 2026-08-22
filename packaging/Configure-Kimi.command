#!/usr/bin/env bash
set -euo pipefail

data_root="${COMPANION_PORTABLE_DATA_ROOT:-$HOME/Library/Application Support/ClinicalReportExtractorLite}"
runtime_root="$data_root/.runtime"
key_path="$runtime_root/kimi-api-key.txt"

printf 'Kimi API key（输入内容不会显示）: '
IFS= read -r -s api_key
printf '\n'
if (( ${#api_key} < 20 || ${#api_key} > 512 )); then
  unset api_key
  echo '密钥长度无效，未保存。' >&2
  exit 1
fi

umask 077
mkdir -p "$runtime_root"
printf '%s' "$api_key" >"$key_path"
chmod 600 "$key_path"
unset api_key

echo 'Kimi 密钥已保存。请退出并重新打开 ClinicalReportExtractorLite.app。'
