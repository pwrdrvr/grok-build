#!/usr/bin/env python3
"""Pin fail-closed invariants in the downstream release signing workflow."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/pwragent-release.yml"
WINDOWS_SIGNER_PATH = ROOT / "scripts/release/sign-windows-binary.ps1"
INSTALLER_PATH = ROOT / "scripts/release/install-trusted-signing.ps1"
RUNBOOK_PATH = ROOT / "docs/pwragent-distribution.md"


def fail(message: str) -> None:
    print(f"release signing contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def require(text: str, fragment: str, scope: str) -> None:
    if fragment not in text:
        fail(f"{scope} must contain {fragment!r}")


def job(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z0-9][a-z0-9-]*:\n|\Z)",
        workflow,
    )
    if match is None:
        fail(f"workflow job {name!r} is missing")
    return match.group(0)


workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
windows_signer = WINDOWS_SIGNER_PATH.read_text(encoding="utf-8")
installer = INSTALLER_PATH.read_text(encoding="utf-8")
runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

require(workflow, "id-token: none", "workflow")
require(workflow, "run: python3 scripts/check-release-signing.py", "metadata job")

macos_prepare = job(workflow, "macos-universal")
macos_sign = job(workflow, "macos-sign")
windows_prepare = job(workflow, "windows-prepare")
windows_sign = job(workflow, "windows-sign")
release = job(workflow, "release")

for name, section in (
    ("macos-universal", macos_prepare),
    ("windows-prepare", windows_prepare),
):
    if "environment:" in section or "secrets." in section:
        fail(f"{name} must remain a no-secret preparation job")
    require(section, "signing-input-sha256:", name)

for fragment in (
    "if: startsWith(github.ref, 'refs/tags/pwragent-v')",
    "environment: apple-signing",
    "CSC_LINK: ${{ secrets.CSC_LINK }}",
    "CSC_KEY_PASSWORD: ${{ secrets.CSC_KEY_PASSWORD }}",
    "APPLE_TEAM_ID: T44CNHC4UH",
    "Developer ID Application: PwrDrvr LLC (${APPLE_TEAM_ID})",
    "--options runtime",
    "--timestamp",
    "codesign --verify --all-architectures --strict",
    "TeamIdentifier=${APPLE_TEAM_ID}",
):
    require(macos_sign, fragment, "macos-sign")

for fragment in (
    "if: startsWith(github.ref, 'refs/tags/pwragent-v')",
    "environment: windows-signing",
    "scripts/release/install-trusted-signing.ps1",
    "scripts/release/sign-windows-binary.ps1",
    "WIN_AZURE_SIGN_PUBLISHER_NAME: ${{ vars.WIN_AZURE_SIGN_PUBLISHER_NAME }}",
    "WIN_AZURE_SIGN_ENDPOINT: ${{ vars.WIN_AZURE_SIGN_ENDPOINT }}",
    "WIN_AZURE_SIGN_ACCOUNT: ${{ vars.WIN_AZURE_SIGN_ACCOUNT }}",
    "WIN_AZURE_SIGN_PROFILE: ${{ vars.WIN_AZURE_SIGN_PROFILE }}",
    "AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}",
    "AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}",
    "AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}",
):
    require(windows_sign, fragment, "windows-sign")

for dependency in ("macos-sign", "windows-sign"):
    require(release, f"- {dependency}", "release")
require(release, "test \"${#assets[@]}\" -eq 4", "release")
require(release, "contents: write", "release")

for fragment in (
    'WIN_AZURE_SIGN_PUBLISHER_NAME = $env:WIN_AZURE_SIGN_PUBLISHER_NAME',
    'AZURE_CLIENT_SECRET = $env:AZURE_CLIENT_SECRET',
    'Invoke-TrustedSigning @signingParameters',
    'Get-AuthenticodeSignature -LiteralPath $resolvedBinary',
    'SignatureStatus]::Valid',
    'TimeStamperCertificate',
    'CN=$expectedPublisher',
):
    require(windows_signer, fragment, "Windows signing script")

for fragment in (
    "-Name TrustedSigning",
    "-MinimumVersion 0.5.0",
    "Get-Command Invoke-TrustedSigning",
):
    require(installer, fragment, "TrustedSigning installer")

for fragment in (
    "Developer ID Application: PwrDrvr LLC (T44CNHC4UH)",
    "`CSC_LINK`",
    "`CSC_KEY_PASSWORD`",
    "`WIN_AZURE_SIGN_ACCOUNT` | `pwrdrvrsigning`",
    "`WIN_AZURE_SIGN_ENDPOINT` | `https://eus.codesigning.azure.net/`",
    "`WIN_AZURE_SIGN_PUBLISHER_NAME` | `PwrDrvr LLC`",
    "`WIN_AZURE_SIGN_PROFILE` | `pwrdrvr-public-trust`",
    "`AZURE_TENANT_ID`",
    "`AZURE_CLIENT_ID`",
    "`AZURE_CLIENT_SECRET`",
    "Artifact Signing Certificate Profile Signer",
    "2028-09-29",
):
    require(runbook, fragment, "release signing runbook")

print("release signing contract: ok")
