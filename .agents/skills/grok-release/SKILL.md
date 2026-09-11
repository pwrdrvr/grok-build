---
name: grok-release
description: Cut or verify a signed PwrDrvr downstream grok-build prerelease, including source-version selection, release tags, protected signing jobs, and published assets.
---

# Grok downstream releases

Use the existing release pipeline in `pwrdrvr/grok-build`. A release request does
not itself request an upstream rebase or a PwrAgent consumer-version change.

## Source of truth

Read [the distribution guide](../../../docs/pwragent-distribution.md) for the
packaging/signing contract and [the release workflow](../../../.github/workflows/pwragent-release.yml)
for current triggers, jobs, and commands. Read the guide's setup or PR signing
rehearsal sections only when that operation is needed; ordinary releases do not
require changing environment protection rules.

## Select and publish the tag

1. Inspect the working tree, branch, remotes, and exact intended commit. Fetch
   downstream refs before comparing local `pwragent` to its remote. In this repo,
   `origin` is normally xAI upstream and `pwrdrvr` is the publishing fork; verify
   URLs rather than assuming `origin` is writable. Do not include unrelated work.
2. Determine the upstream version from the selected commit's
   `crates/codegen/xai-grok-pager-bin/Cargo.toml`, which the workflow uses for
   development versions. Compare source history if its provenance is unclear.
   A newer announced upstream release does not change the version of our source.
   Report discrepancies instead of relabeling old code or silently rebasing it.
3. Use version `<upstream>-pwragent.<N>` and tag
   `pwragent-v<upstream>-pwragent.<N>`. Inspect remote tags and releases to select
   the next unused suffix for that upstream version, including failed attempts.
   If the requested tag already exists, inspect its target/run before proceeding.
   Deleting or retargeting a tag requires explicit authorization.
4. Run `python3 scripts/check-release-signing.py` and use relevant test/build
   evidence for the selected source. Do not treat a compile-only test command as
   executed tests. Resolve actionable failures before publishing.
5. Once release publication is authorized, push any intended source commits to
   downstream using explicit refs, then create a signed annotated tag with
   `git tag -s <tag> <exact-sha> -m <release-message>` and inspect it before
   pushing `refs/tags/<tag>` to `pwrdrvr`. Use configured signing credentials,
   not a hardcoded key. An SSH signature with missing local allowed-signers
   configuration is not a verified signer identity; report that distinction.

Tag pushes trigger the signed release. Ordinary `pwragent` pushes and manual
dispatches build unsigned development artifacts, not releases. The explicit
label-gated PR rehearsal can sign a candidate but cannot publish a release.

## Follow the release

Find the run for the exact tag and head SHA, not merely the newest workflow run.
For long builds, use the available durable monitor workflow with the repository,
run ID, expected SHA/tag, and terminal verification requirements. Do not pass
parent-local command session handles. If unavailable, use bounded status checks.

`in_progress` and `waiting` are not terminal failures, even after many polls.
Check protected environment approvals when signing waits. Ask the operator for
required approval; do not approve, reject, cancel, or weaken protection rules
merely to get the pipeline moving or make logs available.

On failure, identify the failed job and first actionable log error. Distinguish
compiler failures, signing-tool preparation, environment rejection, and signature
validation. Do not bypass checksum/catalog/signer checks. Stop for operator input
when new authority or credentials are needed; do not start repeated release
attempts without resolving the cause. Default to a new suffix after a source fix.

## Verify and report

Require workflow status `completed` with conclusion `success`, successful signing
and publication jobs, and the GitHub prerelease for the intended tag/commit.
Verify these exact assets, substituting the complete downstream version:

- `pwragent-grok-<version>-macos-universal.tar.gz`
- `pwragent-grok-<version>-linux-x86_64.tar.gz`
- `pwragent-grok-<version>-linux-aarch64.tar.gz`
- `pwragent-grok-<version>-windows-x86_64.zip`
- `SHA256SUMS`

Download to a fresh temporary directory, verify final archive checksums, and
inspect packaged `SOURCE_REV`/`PWRAGENT-BUILD.txt` against the selected source and
version. Confirm both macOS architectures and successful timestamped Developer
ID verification (Team ID `T44CNHC4UH`), plus valid timestamped Windows
Authenticode verification for PwrDrvr LLC. Use platform signing-job evidence
when independent local verification is unavailable, and say so. The raw macOS
executable is signed, not separately notarized; do not claim otherwise.

Report tag, source version/SHA, run and release links, prerelease flag, job
conclusions, signing evidence, and asset/checksum results. Clearly distinguish
pending approval, build failure, published release, and independently verified
downloads. A pushed tag or green compilation alone is not release completion.
