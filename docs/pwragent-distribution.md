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

Tag pushes build all targets and create the GitHub Release. A manual workflow
dispatch builds the same matrix as short-retention workflow artifacts without
publishing a release.

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
