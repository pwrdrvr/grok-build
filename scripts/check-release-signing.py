#!/usr/bin/env python3
"""Pin fail-closed invariants in the downstream release signing workflow."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/pwragent-release.yml"
CHECK_WORKFLOW_PATH = ROOT / ".github/workflows/pwragent-release-check.yml"
TRUSTED_SIGNING_CHECK_WORKFLOW_PATH = (
    ROOT / ".github/workflows/pwragent-trusted-signing-check.yml"
)
WINDOWS_SIGNER_PATH = ROOT / "scripts/release/sign-windows-binary.ps1"
WINDOWS_SIGNING_PREPARER_PATH = (
    ROOT / "scripts/release/prepare-trusted-signing.ps1"
)
WINDOWS_SIGNING_VERIFIER_PATH = (
    ROOT / "scripts/release/verify-trusted-signing-tools.ps1"
)
CSC_UPLOADER_PATH = ROOT / "scripts/release/upload-csc-link-from-1password.sh"
RUNBOOK_PATH = ROOT / "docs/pwragent-distribution.md"


def fail(message: str) -> None:
    print(f"release signing contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def require(text: str, fragment: str, scope: str) -> None:
    if fragment not in text:
        fail(f"{scope} must contain {fragment!r}")


def require_absent(text: str, fragment: str, scope: str) -> None:
    if fragment in text:
        fail(f"{scope} must not contain {fragment!r}")


def require_count(text: str, fragment: str, expected: int, scope: str) -> None:
    actual = text.count(fragment)
    if actual != expected:
        fail(
            f"{scope} must contain {fragment!r} exactly {expected} times; "
            f"found {actual}"
        )


def require_before(text: str, first: str, second: str, scope: str) -> None:
    require(text, first, scope)
    require(text, second, scope)
    if text.index(first) >= text.index(second):
        fail(f"{scope} must place {first!r} before {second!r}")


def job(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z0-9][a-z0-9-]*:\n|\Z)",
        workflow,
    )
    if match is None:
        fail(f"workflow job {name!r} is missing")
    return match.group(0)


def step(job_section: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^      - name: {re.escape(name)}\n"
        rf"(.*?)(?=^      - name: |\Z)",
        job_section,
    )
    if match is None:
        fail(f"workflow step {name!r} is missing")
    return match.group(0)


SIGNED_JOB_GUARD = """if: >-
      (github.event_name == 'push'
      && startsWith(github.ref, 'refs/tags/pwragent-v'))
      || (github.event_name == 'pull_request'
      && contains(github.event.pull_request.labels.*.name, 'ci:release-signing'))"""
SIGNED_STEP_GUARD = """if: >-
          (github.event_name == 'push'
          && startsWith(github.ref, 'refs/tags/pwragent-v'))
          || (github.event_name == 'pull_request'
          && contains(github.event.pull_request.labels.*.name, 'ci:release-signing'))"""
UNSIGNED_EVENT_GUARD = """github.event_name == 'workflow_dispatch'
          || (github.event_name == 'push'
          && github.ref == 'refs/heads/pwragent')"""
UNSIGNED_STEP_GUARD = "if: >-\n          " + UNSIGNED_EVENT_GUARD
RELEASE_JOB_GUARD = """if: >-
      github.event_name == 'push'
      && startsWith(github.ref, 'refs/tags/pwragent-v')"""
METADATA_JOB_GUARD = """if: >-
      github.event_name != 'pull_request'
      || (contains(github.event.pull_request.labels.*.name, 'ci:release-signing')
      && (github.event.action == 'synchronize'
      || github.event.action == 'reopened'
      || github.event.label.name == 'ci:release-signing'))"""


workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
check_workflow = CHECK_WORKFLOW_PATH.read_text(encoding="utf-8")
trusted_signing_check_workflow = TRUSTED_SIGNING_CHECK_WORKFLOW_PATH.read_text(
    encoding="utf-8"
)
windows_signer = WINDOWS_SIGNER_PATH.read_text(encoding="utf-8")
windows_signing_preparer = WINDOWS_SIGNING_PREPARER_PATH.read_text(encoding="utf-8")
windows_signing_verifier = WINDOWS_SIGNING_VERIFIER_PATH.read_text(encoding="utf-8")
csc_uploader = CSC_UPLOADER_PATH.read_text(encoding="utf-8")
runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

require(workflow, "id-token: none", "workflow")
require(workflow, "run: python3 scripts/check-release-signing.py", "metadata job")
require(workflow, "pull_request:", "workflow")
require(workflow, "- labeled", "workflow")
require(workflow, "- synchronize", "workflow")
require(workflow, "'ci:release-signing'", "workflow")
require(
    workflow,
    'version="${upstream_version}-pwragent.dev.${GITHUB_RUN_NUMBER}"',
    "development version",
)
require(
    workflow,
    'push:\n    branches:\n      - pwragent\n    tags:\n      - "pwragent-v*"',
    "workflow branch and tag triggers",
)
for fragment in (
    "github.event.action == 'labeled' || github.event.action == 'unlabeled'",
    "github.event.label.name != 'ci:release-signing'",
    "github.run_id",
    "github.event.action == 'synchronize'",
    "github.event.action == 'reopened'",
    "github.event.label.name == 'ci:release-signing'",
):
    require(workflow, fragment, "PR signing trigger guard")

metadata = job(workflow, "metadata")
build = job(workflow, "build")
macos_prepare = job(workflow, "macos-universal")
macos_sign = job(workflow, "macos-sign")
windows_prepare = job(workflow, "windows-prepare")
windows_sign = job(workflow, "windows-sign")
release_candidate = job(workflow, "release-candidate")
release = job(workflow, "release")

metadata_preamble = metadata.split("\n    steps:", maxsplit=1)[0]
require(metadata_preamble, METADATA_JOB_GUARD, "metadata job guard")
for name, section in (
    ("build", build),
    ("macos-universal", macos_prepare),
    ("windows-prepare", windows_prepare),
):
    preamble = section.split("\n    steps:", maxsplit=1)[0]
    require_absent(preamble, "\n    if:", f"{name} job branch-build scope")

linux_release_upload = step(build, "Upload Linux release asset")
require(
    linux_release_upload,
    "runner.os == 'Linux'\n"
    "          && ((github.event_name == 'push'\n"
    "          && startsWith(github.ref, 'refs/tags/pwragent-v'))\n"
    "          || (github.event_name == 'pull_request'\n"
    "          && contains(github.event.pull_request.labels.*.name, "
    "'ci:release-signing')))",
    "Linux release artifact upload",
)
require(linux_release_upload, "name: release-${{ matrix.platform }}", "Linux release artifact")

linux_unsigned_upload = step(build, "Upload unsigned Linux development artifact")
require(linux_unsigned_upload, UNSIGNED_EVENT_GUARD, "unsigned Linux artifact upload")
require(
    linux_unsigned_upload,
    "name: unsigned-${{ matrix.platform }}",
    "unsigned Linux artifact upload",
)

for name, section in (
    ("macos-sign", macos_sign),
    ("windows-sign", windows_sign),
    ("release-candidate", release_candidate),
):
    preamble = section.split("\n    steps:", maxsplit=1)[0]
    require(preamble, SIGNED_JOB_GUARD, f"{name} job guard")

release_preamble = release.split("\n    steps:", maxsplit=1)[0]
require(release_preamble, RELEASE_JOB_GUARD, "release publication job guard")

for name, section, step_names in (
    (
        "macos-universal",
        macos_prepare,
        ("Archive macOS signing input", "Upload macOS signing input"),
    ),
    (
        "windows-prepare",
        windows_prepare,
        (
            "Prepare pinned TrustedSigning client",
            "Archive Windows signing input",
            "Upload Windows signing input",
        ),
    ),
):
    for step_name in step_names:
        require(step(section, step_name), SIGNED_STEP_GUARD, f"{step_name} guard")

for name, section in (
    ("macos-universal", macos_prepare),
    ("windows-prepare", windows_prepare),
):
    unsigned_package = step(section, "Package unsigned development artifact")
    require(
        unsigned_package,
        UNSIGNED_STEP_GUARD,
        f"{name} unsigned package guard",
    )
    require(unsigned_package, "-unsigned", f"{name} unsigned package filename")
    unsigned_upload = step(section, "Upload unsigned development artifact")
    require(
        unsigned_upload,
        UNSIGNED_STEP_GUARD,
        f"{name} unsigned upload guard",
    )
    require(unsigned_upload, "name: unsigned-", f"{name} unsigned artifact name")
    require(unsigned_upload, "-unsigned", f"{name} unsigned artifact path")

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

macos_codesign = step(macos_sign, "Sign and verify macOS binary")
macos_notarize = step(macos_sign, "Notarize signed macOS binary")
macos_package = step(macos_sign, "Package signed macOS distribution")
macos_upload = step(macos_sign, "Upload signed macOS release asset")

for fragment in (
    "id: sign",
    'binary_sha256="$(shasum -a 256 stage/grok',
    'echo "binary-sha256=$binary_sha256" >> "$GITHUB_OUTPUT"',
):
    require(macos_codesign, fragment, "macOS codesign digest")

for fragment in (
    "APPLE_API_KEY_P8: ${{ secrets.APPLE_API_KEY_P8 }}",
    "APPLE_API_KEY_ID: ${{ secrets.APPLE_API_KEY_ID }}",
    "APPLE_API_ISSUER_ID: ${{ secrets.APPLE_API_ISSUER_ID }}",
    "EXPECTED_BINARY_SHA256: ${{ steps.sign.outputs.binary-sha256 }}",
    "ditto -c -k stage/grok",
    'cmp stage/grok "$submission_contents/grok"',
    'xcrun notarytool submit "$submission_archive"',
    '--key "$api_key"',
    '--key-id "$APPLE_API_KEY_ID"',
    '--issuer "$APPLE_API_ISSUER_ID"',
    "--wait",
    "--timeout 30m",
    "--output-format json",
    '[[ "$submission_status" != "Accepted" ]]',
    'test "$actual_sha256" = "$EXPECTED_BINARY_SHA256"',
):
    require(macos_notarize, fragment, "macOS notarization")

for fragment in (
    "EXPECTED_BINARY_SHA256: ${{ steps.sign.outputs.binary-sha256 }}",
    'cmp stage/grok "$published_contents/grok"',
    'test "$published_sha256" = "$EXPECTED_BINARY_SHA256"',
    "codesign --verify --all-architectures --strict",
    '-R="notarized" --check-notarization',
    "spctl --assess --type execute --verbose=4",
    "-verify_arch arm64 x86_64",
):
    require(macos_package, fragment, "published macOS payload verification")

require_before(
    macos_sign,
    "- name: Sign and verify macOS binary",
    "- name: Notarize signed macOS binary",
    "macOS signing and notarization order",
)
require_before(
    macos_sign,
    "- name: Notarize signed macOS binary",
    "- name: Package signed macOS distribution",
    "macOS notarization and packaging order",
)
require_before(
    macos_sign,
    "- name: Package signed macOS distribution",
    "- name: Upload signed macOS release asset",
    "macOS package verification and upload order",
)
require(macos_upload, "name: release-macos-universal", "macOS release upload")
require_count(workflow, "xcrun notarytool submit", 1, "release workflow")
require_absent(macos_sign, "stapler", "standalone macOS binary workflow")
require_absent(macos_prepare, "notarytool", "ordinary macOS preparation job")

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
    'verify-trusted-signing-tools.ps1',
    '$verifiedSigningTools.ModuleManifest',
    '$verifiedSigningTools.LocalAppDataRoot',
):
    require(windows_signer, fragment, "Windows signing script")

for fragment in (
    '"modules/TrustedSigning/$trustedSigningVersion/TrustedSigning.psd1"',
    'Get-FileHash -Algorithm SHA256',
    'Get-ChildItem -LiteralPath $resolvedSigningToolsRoot -File -Recurse -Force',
    'TrustedSigning input files are not covered by SHA256SUMS',
    '$uncoveredFiles -join',
    'Microsoft.Trusted.Signing.Client.1.0.95',
):
    require(windows_signing_verifier, fragment, "TrustedSigning verifier")

for fragment in (
    '$expectedPSGallerySource = "https://www.powershellgallery.com/api/v2"',
    'Get-PSRepository -Name "PSGallery" -ErrorAction SilentlyContinue',
    """if ($psGalleryRepositories.Count -eq 0) {
  Register-PSRepository -Default -ErrorAction Stop
  $psGalleryRepositories = @(
    Get-PSRepository -Name "PSGallery" -ErrorAction Stop
  )
}""",
    "Register-PSRepository -Default -ErrorAction Stop",
    'Get-PSRepository -Name "PSGallery" -ErrorAction Stop',
    "$psGalleryRepositories.Count -ne 1",
    "[System.Uri]::TryCreate(",
    "[System.StringComparison]::OrdinalIgnoreCase",
    '$psGallery.PackageManagementProvider -ne "NuGet"',
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
    "-File -Recurse -Force",
    "$filesToChecksum",
    'Join-Path $resolvedOutputRoot "SHA256SUMS"',
    "$global:LASTEXITCODE = 0",
):
    require(windows_signing_preparer, fragment, "TrustedSigning preparer")

for fragment in (
    'Get-PSRepository -Name "PSGallery" -ErrorAction SilentlyContinue',
    "Register-PSRepository -Default -ErrorAction Stop",
    '$psGallery.PackageManagementProvider -ne "NuGet"',
):
    require_before(
        windows_signing_preparer,
        fragment,
        "Save-Module",
        "TrustedSigning PSGallery preparation",
    )

require_before(
    windows_signing_preparer,
    "$checksumLines | Set-Content",
    "$global:LASTEXITCODE = 0",
    "TrustedSigning stale native exit-code reset",
)
require_before(
    windows_signing_preparer,
    "$global:LASTEXITCODE = 0",
    'Write-Host "Prepared pinned TrustedSigning',
    "TrustedSigning stale native exit-code reset",
)

if "Install-PackageProvider" in windows_signing_preparer:
    fail("TrustedSigning preparer must not bootstrap the legacy NuGet provider")

for fragment in (
    '".github/workflows/pwragent-trusted-signing-check.yml"',
    '"docs/pwragent-distribution.md"',
    '"scripts/check-release-signing.py"',
    '"scripts/release/**"',
    "release-signing-contract:",
    "run: python3 scripts/check-release-signing.py",
    "id-token: none",
):
    require(check_workflow, fragment, "release signing contract check workflow")

for fragment in (
    '".github/workflows/pwragent-trusted-signing-check.yml"',
    '"docs/pwragent-distribution.md"',
    '"scripts/check-release-signing.py"',
    '"scripts/release/**"',
):
    require_count(
        check_workflow,
        fragment,
        2,
        "release signing contract pull-request and push trigger scope",
    )

require_absent(
    check_workflow,
    "trusted-signing-preparation:",
    "release signing contract check workflow",
)

for fragment in (
    '".github/workflows/pwragent-release.yml"',
    '".github/workflows/pwragent-trusted-signing-check.yml"',
    '"scripts/release/prepare-trusted-signing.ps1"',
    '"scripts/release/verify-trusted-signing-tools.ps1"',
    "trusted-signing-preparation:",
    "runs-on: windows-2022",
    "timeout-minutes: 10",
    "Remove PSGallery to exercise self-registration",
    'Unregister-PSRepository -Name "PSGallery" -ErrorAction Stop',
    "$remainingRepositories.Count -ne 0",
    "scripts/release/prepare-trusted-signing.ps1",
    "-OutputRoot $env:RUNNER_TEMP/signing-tools",
    "Verify signing client after archive round-trip",
    "tar.exe -czf",
    "tar.exe -xzf",
    "scripts/release/verify-trusted-signing-tools.ps1",
    "id-token: none",
):
    require(
        trusted_signing_check_workflow,
        fragment,
        "TrustedSigning preparation check workflow",
    )

for fragment in (
    '".github/workflows/pwragent-release.yml"',
    '".github/workflows/pwragent-trusted-signing-check.yml"',
    '"scripts/release/prepare-trusted-signing.ps1"',
    '"scripts/release/verify-trusted-signing-tools.ps1"',
):
    require_count(
        trusted_signing_check_workflow,
        fragment,
        2,
        "TrustedSigning pull-request and push trigger scope",
    )
require(
    trusted_signing_check_workflow,
    "push:\n    branches:\n      - pwragent",
    "TrustedSigning downstream push trigger",
)

for fragment in (
    '"docs/pwragent-distribution.md"',
    '"scripts/check-release-signing.py"',
    '"scripts/release/sign-windows-binary.ps1"',
    '"scripts/release/upload-csc-link-from-1password.sh"',
):
    require_absent(
        trusted_signing_check_workflow,
        fragment,
        "TrustedSigning preparation trigger scope",
    )

for name, contents in (
    ("release signing contract check workflow", check_workflow),
    ("TrustedSigning preparation check workflow", trusted_signing_check_workflow),
):
    if "environment:" in contents or "secrets." in contents:
        fail(f"{name} must not enter an environment or read secrets")
    require_absent(contents, "notarytool", f"{name} ordinary CI scope")

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
    "Every ordinary push to `pwragent`",
    "`unsigned-*` workflow artifacts",
    "`Check PwrAgent TrustedSigning preparation`",
    "documentation-only",
    "`APPLE_API_KEY_P8`",
    "`APPLE_API_KEY_ID`",
    "`APPLE_API_ISSUER_ID`",
    "App Store Connect team API key",
    "temporary ZIP",
    "notarytool",
    "Accepted",
    "cannot be stapled",
    "--check-notarization",
    "spctl --assess --type execute",
):
    require(runbook, fragment, "release signing runbook")

print("release signing contract: ok")
