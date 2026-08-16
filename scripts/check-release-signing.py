#!/usr/bin/env python3
"""Pin fail-closed invariants in the downstream release signing workflow."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/pwragent-release.yml"
CHECK_WORKFLOW_PATH = ROOT / ".github/workflows/pwragent-release-check.yml"
WINDOWS_SIGNER_PATH = ROOT / "scripts/release/sign-windows-binary.ps1"
WINDOWS_SIGNING_PREPARER_PATH = (
    ROOT / "scripts/release/prepare-trusted-signing.ps1"
)
CSC_UPLOADER_PATH = ROOT / "scripts/release/upload-csc-link-from-1password.sh"
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
check_workflow = CHECK_WORKFLOW_PATH.read_text(encoding="utf-8")
windows_signer = WINDOWS_SIGNER_PATH.read_text(encoding="utf-8")
windows_signing_preparer = WINDOWS_SIGNING_PREPARER_PATH.read_text(encoding="utf-8")
csc_uploader = CSC_UPLOADER_PATH.read_text(encoding="utf-8")
runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

require(workflow, "id-token: none", "workflow")
require(workflow, "run: python3 scripts/check-release-signing.py", "metadata job")
require(workflow, "pull_request:", "workflow")
require(workflow, "- labeled", "workflow")
require(workflow, "- synchronize", "workflow")
require(workflow, "'ci:release-signing'", "workflow")
for fragment in (
    "github.event.action == 'labeled' || github.event.action == 'unlabeled'",
    "github.event.label.name != 'ci:release-signing'",
    "github.run_id",
    "github.event.action == 'synchronize'",
    "github.event.action == 'reopened'",
    "github.event.label.name == 'ci:release-signing'",
):
    require(workflow, fragment, "PR signing trigger guard")

macos_prepare = job(workflow, "macos-universal")
macos_sign = job(workflow, "macos-sign")
windows_prepare = job(workflow, "windows-prepare")
windows_sign = job(workflow, "windows-sign")
release_candidate = job(workflow, "release-candidate")
release = job(workflow, "release")

for name, section in (
    ("macos-universal", macos_prepare),
    ("windows-prepare", windows_prepare),
):
    if "environment:" in section or "secrets." in section:
        fail(f"{name} must remain a no-secret preparation job")
    require(section, "signing-input-sha256:", name)

for fragment in (
    "scripts/release/prepare-trusted-signing.ps1",
    "-OutputRoot signing-tools",
    "stage/windows-x86_64 signing-tools scripts/release",
):
    require(windows_prepare, fragment, "windows-prepare")

for fragment in (
    "startsWith(github.ref, 'refs/tags/pwragent-v')",
    "contains(github.event.pull_request.labels.*.name, 'ci:release-signing')",
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
    "startsWith(github.ref, 'refs/tags/pwragent-v')",
    "contains(github.event.pull_request.labels.*.name, 'ci:release-signing')",
    "environment: windows-signing",
    "scripts/release/sign-windows-binary.ps1",
    "-SigningToolsRoot signing-tools",
    "WIN_AZURE_SIGN_PUBLISHER_NAME: ${{ vars.WIN_AZURE_SIGN_PUBLISHER_NAME }}",
    "WIN_AZURE_SIGN_ENDPOINT: ${{ vars.WIN_AZURE_SIGN_ENDPOINT }}",
    "WIN_AZURE_SIGN_ACCOUNT: ${{ vars.WIN_AZURE_SIGN_ACCOUNT }}",
    "WIN_AZURE_SIGN_PROFILE: ${{ vars.WIN_AZURE_SIGN_PROFILE }}",
    "AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}",
    "AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}",
    "AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}",
):
    require(windows_sign, fragment, "windows-sign")

if "Install-Module" in windows_sign or "Save-Module" in windows_sign:
    fail("windows-sign must not acquire PowerShell modules inside the protected job")

for dependency in ("macos-sign", "windows-sign"):
    require(release_candidate, f"- {dependency}", "release-candidate")
require(
    release_candidate,
    "contains(github.event.pull_request.labels.*.name, 'ci:release-signing')",
    "release-candidate",
)
require(release_candidate, "test \"${#assets[@]}\" -eq 4", "release-candidate")
require(release_candidate, "name: signed-release-candidate", "release-candidate")
require(release_candidate, "contents: read", "release-candidate")
require(release, "- release-candidate", "release")
require(release, "name: signed-release-candidate", "release")
require(release, "contents: write", "release")

for fragment in (
    'WIN_AZURE_SIGN_PUBLISHER_NAME = $env:WIN_AZURE_SIGN_PUBLISHER_NAME',
    'AZURE_CLIENT_SECRET = $env:AZURE_CLIENT_SECRET',
    'Invoke-TrustedSigning @signingParameters',
    'Get-AuthenticodeSignature -LiteralPath $resolvedBinary',
    'SignatureStatus]::Valid',
    'TimeStamperCertificate',
    'CN=$expectedPublisher',
    '"modules/TrustedSigning/$trustedSigningVersion/TrustedSigning.psd1"',
    'Get-FileHash -Algorithm SHA256',
    'TrustedSigning input contains files not covered by SHA256SUMS',
    'Microsoft.Trusted.Signing.Client.1.0.95',
):
    require(windows_signer, fragment, "Windows signing script")

for fragment in (
    'trustedSigningVersion = "0.5.8"',
    "Save-Module",
    "-RequiredVersion $trustedSigningVersion",
    "Test-FileCatalog",
    "-Detailed",
    "$moduleFiles.FullName",
    'Name -ne "PSGetModuleInfo.xml"',
    "duplicate catalog leaf names",
    "SignatureStatus]::Valid",
    'catalogSigner -ne "Microsoft Corporation"',
    "Get-EveryDependency",
    'Join-Path $resolvedOutputRoot "SHA256SUMS"',
):
    require(windows_signing_preparer, fragment, "TrustedSigning preparer")

if "Install-PackageProvider" in windows_signing_preparer:
    fail("TrustedSigning preparer must not bootstrap the legacy NuGet provider")

for fragment in (
    "trusted-signing-preparation:",
    "runs-on: windows-2022",
    "timeout-minutes: 10",
    "scripts/release/prepare-trusted-signing.ps1",
    "-OutputRoot $env:RUNNER_TEMP/signing-tools",
    "id-token: none",
):
    require(check_workflow, fragment, "release signing check workflow")

if "environment:" in check_workflow or "secrets." in check_workflow:
    fail("release signing check workflow must not enter an environment or read secrets")

for fragment in (
    'repo="${GITHUB_REPOSITORY:-pwrdrvr/grok-build}"',
    'environment="${GITHUB_ENVIRONMENT:-apple-signing}"',
    "op read",
    "gh secret set CSC_LINK",
):
    require(csc_uploader, fragment, "CSC_LINK upload helper")

uploaded_secret_names = re.findall(r"gh secret set ([A-Z0-9_]+)", csc_uploader)
if uploaded_secret_names != ["CSC_LINK"]:
    fail(
        "CSC_LINK upload helper must upload exactly CSC_LINK; found "
        + repr(uploaded_secret_names)
    )

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
    "`ci:release-signing`",
    "`refs/pull/<PR number>/merge`",
    "`signed-release-candidate`",
):
    require(runbook, fragment, "release signing runbook")

print("release signing contract: ok")
