# Grok Build — PwrAgent downstream fork

This is **not** the upstream Grok Build repository. It is PwrDrvr's downstream
fork of [`xai-org/grok-build`](https://github.com/xai-org/grok-build), and its
default branch is `pwragent`.

## Why this repo exists

[PwrAgent](https://github.com/pwrdrvr/PwrAgent) drives coding agents from chat
apps (Telegram, Discord, Slack, Mattermost, Feishu/Lark, LINE) and talks to
them over the [Agent Client Protocol](https://agentclientprotocol.com) (ACP).
Grok Build is one of those agent backends.

Making Grok Build work well as a PwrAgent backend needed changes the upstream
tree didn't have at the time:

- **ACP features PwrAgent depends on** — mid-turn steering, session-scoped
  workflow budgets, and tool updates carrying enough metadata for a remote
  client to render them.
- **Startup and resume performance** — every chat message PwrAgent relays waits
  on a cold `session/load`, so seconds of unused TLS/HTTP client setup were
  directly visible to users.
- **A distributable, signed build** — PwrAgent ships Grok Build as a bundled
  runtime on macOS, Linux, and Windows, which upstream does not publish in a
  form PwrAgent can redistribute.

Upstream is an export of an internal xAI monorepo and
[does not accept external patches](CONTRIBUTING.md), so these changes live here
and are rebased onto each upstream sync. `origin/main` tracks the upstream
source line unchanged; `pwragent` is the maintained downstream branch.

## What this fork changes

### ACP functionality

| Change | Summary |
|---|---|
| [#7](https://github.com/pwrdrvr/grok-build/pull/7) | Adds `x.ai/session/steer` for mid-turn steering of a resident session (reporting whether text lands in the current or next turn) and `x.ai/session/workflow_budget` for session-scoped workflow child-agent limits. |
| [#6](https://github.com/pwrdrvr/grok-build/pull/6) | Keeps the human-readable title, kind, and arguments on completed tool updates, so ACP clients render real labels instead of placeholder rows. Consumer side: [PwrAgent#1525](https://github.com/pwrdrvr/PwrAgent/pull/1525). |

### Performance

| Change | Summary |
|---|---|
| [#4](https://github.com/pwrdrvr/grok-build/pull/4) | Defers the five tool HTTP clients until first use and caches native TLS roots once per process — host-observed ACP `session/load` restore dropped from 856 ms to 171 ms (5×) in matched release builds. |
| [#5](https://github.com/pwrdrvr/grok-build/pull/5) | Fetches the model catalog and `/v1/settings` concurrently during cold-start prefetch, cutting ~40 ms from spawn-to-ACP-initialize. |

The two performance changes also exist as standalone, upstream-shaped PRs
against this fork's untouched `main` mirror, with isolated measurements and
reproduction steps:
[#2](https://github.com/pwrdrvr/grok-build/pull/2) (lazy tool HTTP clients),
[#1](https://github.com/pwrdrvr/grok-build/pull/1) (cached native TLS roots),
and [#3](https://github.com/pwrdrvr/grok-build/pull/3) (the two combined, with
the end-to-end ACP restore benchmark).

### Distribution and release signing

| Change | Summary |
|---|---|
| [#8](https://github.com/pwrdrvr/grok-build/pull/8) | Splits release builds into unprivileged build jobs and protected signing jobs: Developer ID signing for the macOS universal binary, Azure Artifact Signing for Windows x64, digests carried across both boundaries, plus a label-gated signing test that cannot publish a release. |
| [#9](https://github.com/pwrdrvr/grok-build/pull/9) | Fixes the signing-tool checksum manifest to cover hidden files and report the exact uncovered paths on mismatch. |

Earlier downstream commits landed directly on `pwragent` before the PR flow
was in place:

| Commit | Summary |
|---|---|
| [`4796c4a`](https://github.com/pwrdrvr/grok-build/commit/4796c4a) | Adds the PwrAgent ACP distribution: release workflow, archive layout, and provenance for the four supported targets. |
| [`cad78a8`](https://github.com/pwrdrvr/grok-build/commit/cad78a8) | Marks downstream releases as prereleases so they never look like official xAI builds. |
| [`9a498d4`](https://github.com/pwrdrvr/grok-build/commit/9a498d4) | Pins the release build toolchain. |
| [`df85fb6`](https://github.com/pwrdrvr/grok-build/commit/df85fb6), [`15dff34`](https://github.com/pwrdrvr/grok-build/commit/15dff34) | Makes proto codegen work on Windows CI without DotSlash. |
| [`f6e5c5c`](https://github.com/pwrdrvr/grok-build/commit/f6e5c5c) | Works around the MSVC PDB linker limit in release builds. |
| [`87272ef`](https://github.com/pwrdrvr/grok-build/commit/87272ef) | Fixes the macOS universal-binary architecture check. |

## Releases

Downstream builds are published as prereleases tagged
`pwragent-v<upstream-version>-pwragent.<n>` — macOS universal, Linux x86_64,
Linux aarch64, and Windows x64 archives plus `SHA256SUMS`. See
[`docs/pwragent-distribution.md`](docs/pwragent-distribution.md) for the
release process, signing boundaries, and target rationale.

For where this fork stands against stable ACP v1 — what's supported, what's an
`x.ai/*` extension, and what PwrAgent actually consumes — see
[`docs/acp-compatibility.md`](docs/acp-compatibility.md).

## Using Grok Build itself

This README covers the fork. For the product — what Grok Build is, installing
the official binary, building from source, the user guide, and repository
layout — see the
[upstream README](https://github.com/xai-org/grok-build/blob/main/README.md)
and [docs.x.ai/build/overview](https://docs.x.ai/build/overview).

`SOURCE_REV` records the upstream monorepo commit this tree was synced from.

## Contributing

This fork exists to serve PwrAgent; it is not a general-purpose distribution of
Grok Build. Upstream does not accept external patches — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

First-party code remains under the **Apache License, Version 2.0** — see
[`LICENSE`](LICENSE). Third-party and vendored code remains under its original
licenses; see [`THIRD-PARTY-NOTICES`](THIRD-PARTY-NOTICES) and
[`third_party/NOTICE`](third_party/NOTICE).
