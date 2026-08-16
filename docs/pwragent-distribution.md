# PwrAgent downstream distribution

This fork packages Grok Build as an ACP runtime distributed with PwrAgent.
It is not an upstream xAI release.

## Branch and remote topology

- `origin/main` is the read-only upstream source line from
  `xai-org/grok-build`.
- `pwragent` is the maintained downstream branch in `pwrdrvr/grok-build`.
- Downstream changes should stay small and be rebased or merged onto each new
  upstream source sync.

The upstream repository is an export of an internal monorepo and does not
accept external patches. Keeping the GitHub fork relationship makes upstream
comparison and synchronization visible while allowing PwrDrvr-owned Actions
and release assets.

## Release targets

The `Build PwrAgent Grok distribution` workflow produces:

| PwrAgent target | Grok artifact |
| --- | --- |
| macOS universal (Intel + Apple Silicon) | `pwragent-grok-<version>-macos-universal.tar.gz` |
| Ubuntu x64 | `pwragent-grok-<version>-linux-x86_64.tar.gz` |
| Ubuntu arm64 | `pwragent-grok-<version>-linux-aarch64.tar.gz` |
| Windows x64 | `pwragent-grok-<version>-windows-x86_64.zip` |

Each archive contains the renamed `grok` executable, Apache 2.0 license,
third-party notices, upstream `SOURCE_REV`, and downstream build provenance.
The release also includes `SHA256SUMS`.

Release-tag builds sign the universal macOS executable with PwrDrvr LLC's
Developer ID Application identity and Authenticode-sign the Windows x64
executable with PwrDrvr LLC's Azure Artifact Signing certificate before either
archive is eligible for publication. Linux archives remain checksum-verified
but are not platform-signed.

Windows arm64 is intentionally omitted until PwrAgent ships a Windows arm64
desktop build. Linux arm64 remains included because PwrAgent already packages
an arm64 Debian artifact.

## Cutting a downstream release

Use a SemVer prerelease suffix so downstream builds never look like official
xAI releases:

```sh
git switch pwragent
git fetch origin main
git merge --ff-only origin/main
# Reapply or merge the small downstream patch stack when a fast-forward is not possible.

git tag -s pwragent-v0.2.112-pwragent.1 -m "PwrAgent Grok 0.2.112-pwragent.1"
git push pwrdrvr pwragent
git push pwrdrvr pwragent-v0.2.112-pwragent.1
```

Tag pushes build all targets, pause at the protected signing environments, and
create the GitHub Release only after both protected jobs have verified their
signatures. A manual workflow dispatch builds the same matrix as
short-retention workflow artifacts without using signing credentials or
publishing a release. Its macOS and Windows artifact names include `unsigned`
so they cannot be confused with release payloads.

## Release signing trust boundary

The workflow deliberately separates untrusted compilation from credentialed
signing:

1. macOS arm64 and x86_64 jobs build without secrets. A no-secret job merges
   them into one universal binary, archives the signing input, and exports its
   SHA-256 digest.
2. The `macos-sign` job is gated by the `apple-signing` GitHub Environment. It
   does not check out source. It downloads and verifies the exact prepared
   archive, imports the Developer ID certificate into an ephemeral keychain,
   applies a hardened-runtime timestamped signature, and requires both
   `codesign --verify` and Team ID `T44CNHC4UH` before packaging.
3. The `windows-prepare` job builds `grok.exe`, downloads the exact
   `TrustedSigning` 0.5.8 module plus its pinned signing-client dependencies,
   validates the Microsoft module catalog, records a per-file checksum
   manifest, and archives all of that without an environment or credentials.
   It exports the complete archive SHA-256.
4. The `windows-sign` job is gated by the `windows-signing` GitHub Environment.
   It does not check out source or run project dependency installation. It
   verifies the complete prepared archive and the nested signing-tool checksum
   manifest, signs through Azure Artifact Signing, and requires a valid
   timestamped Authenticode signature whose subject begins `CN=PwrDrvr LLC`.
   Its only network calls are the irreducible Azure signing and timestamp
   requests; acquisition of build and signing tools happened before the
   protected boundary.
5. The `release-candidate` job depends on both protected signing jobs and the
   Linux builds, downloads only `release-*` artifacts, requires exactly four
   platform archives, calculates `SHA256SUMS` from the final signed packages,
   and uploads one `signed-release-candidate` workflow artifact.
6. The tag-only release job downloads that exact assembled candidate and
   creates the immutable GitHub Release. It never rebuilds, resigns, or gathers
   platform outputs independently.

This dependency chain is fail closed: a missing environment approval, missing
secret or variable, bad certificate, digest mismatch, signing-service failure,
wrong signer, or missing timestamp prevents release creation. Signing material
is never available to build jobs or manual-dispatch builds. Pull requests gain
access only through the deliberately label-gated, environment-approved signing
test described below.

`scripts/check-release-signing.py` pins these workflow invariants. The
`Check PwrAgent release signing` workflow runs it on relevant pull requests and
changes to the downstream `pwragent` branch. A separate Windows job in that
check downloads and validates the pinned TrustedSigning client and its
dependencies without compiling Grok, entering a protected environment, or
reading secrets. This catches signing-tool preparation failures before an
expensive end-to-end release rehearsal.

The raw Grok executable is Developer ID signed but is not submitted separately
for Apple notarization. It is normally embedded during PwrAgent's no-secret
packaging stage and then covered by PwrAgent's signed and notarized application
bundle. If this repository later distributes Grok as a standalone macOS app,
package, or disk image, add notarization for that container before calling it a
Gatekeeper-ready standalone download.

## Testing protected signing from a pull request

The `ci:release-signing` label runs the same preparation, protected signing,
signature verification, and release-candidate assembly used by a tag. It does
not run the `release` job and therefore cannot create or modify a GitHub
Release. The result is a seven-day `signed-release-candidate` workflow artifact
containing all four platform archives and their final `SHA256SUMS`.

This is intentionally not available to every pull request. Before applying the
label:

1. Inspect the complete PR diff, including the workflow and every script that
   enters a signing input archive.
2. In both `apple-signing` and `windows-signing`, temporarily add the exact
   **branch** rule `refs/pull/<PR number>/merge`. Keep the existing
   `pwragent-v*` tag rule.
3. Apply `ci:release-signing` to the PR. GitHub runs the workflow from
   `refs/pull/<PR number>/merge`; each signing job still waits for the required
   `huntharo` environment approval before it can read secrets.
4. After both approvals, wait for `Assemble signed release candidate` and
   inspect/download the `signed-release-candidate` artifact. No release is
   published from a pull-request event.
5. Remove the label and delete the temporary `refs/pull/<PR number>/merge`
   branch rule from both environments when the test is complete.

The workflow uses `pull_request`, never `pull_request_target`, so the tested
source and merge ref are explicit. Removing the label triggers a no-op run and
cancels an in-progress signing-test run for the same pull-request ref.

## One-time operator setup for `pwrdrvr/grok-build`

Do not add any signing material as repository secrets. Configure these two
GitHub Environments under **Settings → Environments** in
`pwrdrvr/grok-build`.

### `apple-signing` environment

Environment protection:

- Required reviewer: `huntharo` (Harold).
- Deployment branches and tags: choose **Selected branches and tags**, add the
  tag rule `pwragent-v*`, and add no branch rule.
- Do not approve a run until its tag, commit, downstream version, and
  `SOURCE_REV` are the intended release.

Required certificate:

- Apple **Developer ID Application** certificate with the exact identity
  `Developer ID Application: PwrDrvr LLC (T44CNHC4UH)`.
- The exported `.p12` must include its private key and be protected with a
  strong export password. The certificate currently used by the PwrAgent
  desktop release may be reused; do not commit the `.p12` or its password.

Environment secrets:

| Secret | Exact value/source |
| --- | --- |
| `CSC_LINK` | Base64 of the password-protected Developer ID `.p12`. A `data:application/x-pkcs12;base64,` prefix is accepted but not required. |
| `CSC_KEY_PASSWORD` | Password used when exporting that `.p12`. |

No App Store Connect API key is required for this binary-only signing job; the
workflow does not notarize this raw executable.

To prepare `CSC_LINK` locally without writing the base64 to the repository:

```sh
base64 < PwrDrvr-Developer-ID-Application.p12 | tr -d '\n'
```

If using that manual command, paste its result directly into the environment
secret, then clear the shell history/clipboard according to the operator's
secret-handling policy.

If the existing PwrDrvr Developer ID `.p12` remains in the documented
1Password item, the repository helper performs that upload without exposing the
base64 in the terminal or uploading any other secret:

```sh
OP_ACCOUNT=<USER_ID_FROM_OP_ACCOUNT_LIST> \
  scripts/release/upload-csc-link-from-1password.sh
```

### `windows-signing` environment

PwrDrvr's existing Azure resources can be reused. The current source-of-truth
configuration is the **PwrDrvr Azure** subscription, resource group
`rg-pwrdrvr-signing`, region **East US**, Artifact Signing account
`pwrdrvrsigning`, and **Public Trust** certificate profile
`pwrdrvr-public-trust`. The expected certificate subject is:

```text
CN=PwrDrvr LLC, O=PwrDrvr LLC, L=Aberdeen, S=New Jersey, C=US
```

Environment protection:

- Required reviewer: `huntharo` (Harold).
- Deployment branches and tags: choose **Selected branches and tags**, add the
  tag rule `pwragent-v*`, and add no branch rule.
- Do not approve a run until its tag, commit, downstream version, and
  `SOURCE_REV` are the intended release.

Environment variables (not secrets):

| Variable | Exact value |
| --- | --- |
| `WIN_AZURE_SIGN_ACCOUNT` | `pwrdrvrsigning` |
| `WIN_AZURE_SIGN_ENDPOINT` | `https://eus.codesigning.azure.net/` |
| `WIN_AZURE_SIGN_PUBLISHER_NAME` | `PwrDrvr LLC` |
| `WIN_AZURE_SIGN_PROFILE` | `pwrdrvr-public-trust` |

Environment secrets from the existing Entra app registration
`pwragent-release-signing`:

| Secret | Exact value/source |
| --- | --- |
| `AZURE_TENANT_ID` | Microsoft Entra **Directory (tenant) ID**. |
| `AZURE_CLIENT_ID` | App registration **Application (client) ID**. |
| `AZURE_CLIENT_SECRET` | The client-secret **Value**, not its Secret ID. |

Confirm that the app registration's service principal has the
**Artifact Signing Certificate Profile Signer** RBAC role on the signing
account or `pwrdrvr-public-trust` profile. The similarly named Artifact Signing
Identity Verifier role is insufficient. Also confirm that the certificate
profile type is **Public Trust**, not **Public Trust Test**.

The Azure certificate profile issues rolling short-lived certificates; its
near-term certificate date does not require rotation. Calendar the credentials
that actually expire: renew the Entra client secret before its expiry and the
PwrDrvr identity validation before **2028-09-29**, then update only the
environment secret/configuration as needed.

After the first approved tag run, download the published archives and verify
the final payloads independently:

```sh
tar -xzf pwragent-grok-<version>-macos-universal.tar.gz
codesign --verify --all-architectures --strict --verbose=2 grok
codesign --display --verbose=4 grok 2>&1 | grep 'TeamIdentifier=T44CNHC4UH'
```

```powershell
Expand-Archive pwragent-grok-<version>-windows-x86_64.zip -DestinationPath grok-release
$signature = Get-AuthenticodeSignature grok-release/grok.exe
$signature | Format-List Status, StatusMessage, SignerCertificate, TimeStamperCertificate
if ($signature.Status -ne "Valid") { throw "Invalid Authenticode signature" }
```

## PwrAgent embedding contract

PwrAgent should download one pinned downstream tag during its no-secret
packaging phase, verify the selected archive against `SHA256SUMS`, and place
the executable under an application resource directory such as
`Resources/agents/grok/`.

The packaged launch descriptor should:

- invoke the embedded absolute path with `agent stdio`;
- set `NO_COLOR=1`;
- set `GROK_INSTALLER=pwragent` so the embedded, code-signed executable does
  not replace itself with an xAI-managed download;
- allow an explicit user-selected local Grok executable to override the
  embedded copy.

macOS signing/notarization must happen after the universal Grok executable is
embedded. Linux and Windows packaging must embed the matching native artifact.

## License and naming

First-party source is Apache-2.0, while vendored components retain their own
licenses. PwrAgent distributions must preserve `LICENSE`,
`THIRD-PARTY-NOTICES`, and the fork's source/provenance link. Product UI and
release notes should identify this as a PwrDrvr downstream build rather than an
official xAI binary.
