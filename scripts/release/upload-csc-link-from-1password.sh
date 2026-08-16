#!/usr/bin/env bash
set -euo pipefail

repo="${GITHUB_REPOSITORY:-pwrdrvr/grok-build}"
environment="${GITHUB_ENVIRONMENT:-apple-signing}"
vault_name="${OP_VAULT_NAME:-PwrDrvr LLC}"
item_title="${OP_ITEM_TITLE:-Apple Signing - PwrDrvr}"
p12_attachment_name="${OP_P12_ATTACHMENT_NAME:-${OP_ATTACHMENT_NAME:-PwrDrvr_DevID_Application.p12}}"

usage() {
  cat >&2 <<'EOF'
Uploads only CSC_LINK from 1Password to the pwrdrvr/grok-build
apple-signing GitHub Environment.

Usage:
  scripts/release/upload-csc-link-from-1password.sh
  scripts/release/upload-csc-link-from-1password.sh --list-accounts

Required:
  OP_ACCOUNT=<1Password account identifier>

Use the USER ID from `op account list` when the URL or email appears more than
once. The URL is ambiguous on machines with multiple accounts on the same
1Password domain.

Optional overrides:
  GITHUB_REPOSITORY=pwrdrvr/grok-build
  GITHUB_ENVIRONMENT=apple-signing
  OP_VAULT_NAME="PwrDrvr LLC"
  OP_ITEM_TITLE="Apple Signing - PwrDrvr"
  OP_P12_ATTACHMENT_NAME=PwrDrvr_DevID_Application.p12

Example:
  OP_ACCOUNT=<USER_ID_FROM_OP_ACCOUNT_LIST> scripts/release/upload-csc-link-from-1password.sh

This script intentionally does not upload CSC_KEY_PASSWORD or notarization
credentials. Configure any other required environment secrets separately.
EOF
}

print_accounts() {
  local accounts_json
  if ! accounts_json="$(op account list --format json 2>/dev/null)"; then
    echo "Could not list configured 1Password accounts." >&2
    return 1
  fi

  if ! jq -e 'length > 0' <<<"$accounts_json" >/dev/null; then
    echo "No configured 1Password accounts found." >&2
    return 1
  fi

  cat >&2 <<'EOF'
Configured 1Password accounts:

NAME		URL			EMAIL			USER ID
EOF

  while IFS=$'\t' read -r user_uuid url email; do
    local account_json
    local name
    if account_json="$(op account get --account "$user_uuid" --format json 2>/dev/null)"; then
      name="$(jq -r '.name // "(name unavailable)"' <<<"$account_json")"
    else
      name="(name unavailable)"
    fi
    printf '%s\t%s\t%s\t%s\n' "$name" "$url" "$email" "$user_uuid" >&2
  done < <(jq -r '.[] | [.user_uuid, .url, .email] | @tsv' <<<"$accounts_json")

  cat >&2 <<'EOF'

Use the USER ID for the account that contains the configured vault.
Run again with:
  OP_ACCOUNT=<USER ID> ./scripts/release/upload-csc-link-from-1password.sh
EOF
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 127
  fi
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--list-accounts" ]]; then
  require_command op
  require_command jq
  print_accounts
  exit 0
fi

require_command jq
require_command op

if [[ -z "${OP_ACCOUNT:-}" ]]; then
  cat >&2 <<'EOF'
Set OP_ACCOUNT to the 1Password account identifier first.

Use the USER ID column when the URL or email appears more than once.
EOF
  print_accounts
  exit 2
fi

require_command gh
require_command base64

vault_id="$(
  op vault list --account "$OP_ACCOUNT" --format json \
    | jq -r --arg name "$vault_name" 'first(.[] | select(.name == $name) | .id) // empty'
)"
if [[ -z "$vault_id" ]]; then
  echo "Could not find vault '$vault_name' in 1Password account '$OP_ACCOUNT'." >&2
  exit 1
fi

item_id="$(
  op item list --account "$OP_ACCOUNT" --vault "$vault_id" --format json \
    | jq -r --arg title "$item_title" 'first(.[] | select(.title == $title) | .id) // empty'
)"
if [[ -z "$item_id" ]]; then
  echo "Could not find item '$item_title' in vault '$vault_name'." >&2
  exit 1
fi

item_json="$(op item get "$item_id" --account "$OP_ACCOUNT" --vault "$vault_id" --format json)"
if ! jq -e --arg name "$p12_attachment_name" '.files[]? | select(.name == $name)' <<<"$item_json" >/dev/null; then
  echo "Could not find attachment '$p12_attachment_name' on item '$item_title'." >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

p12_path="$tmpdir/$p12_attachment_name"
op read \
  --account "$OP_ACCOUNT" \
  --out-file "$p12_path" \
  "op://$vault_id/$item_id/$p12_attachment_name" \
  >/dev/null
if [[ ! -s "$p12_path" ]]; then
  echo "Attachment '$p12_attachment_name' downloaded as an empty file." >&2
  exit 1
fi

base64 < "$p12_path" \
  | tr -d '\n' \
  | gh secret set CSC_LINK --repo "$repo" --env "$environment"

echo "Uploaded CSC_LINK from $p12_attachment_name to $repo environment '$environment'."
