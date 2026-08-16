# ACP compatibility review for PwrAgent

Reviewed against the stable ACP v1 documentation and the PwrAgent source on
2026-07-26. ACP v2 is still documented as draft and is not a release target
for this fork yet.

The negotiated `protocolVersion`, not the Rust crate version, determines ACP
wire compatibility. Optional v1 features are then selected through exchanged
capabilities. Grok Build currently pins `agent-client-protocol` 0.10.4 with
its `unstable` feature set, so several now-stable v1 types are compiled in but
are not routed or implemented by Grok's local `xai-acp-lib` gateway.

## Current interoperability matrix

Legend: **Yes** is end-to-end support, **Partial** is implemented with a
capability/adapter limitation, **Extension** is an xAI-specific method rather
than the stable ACP method, and **No** is not currently implemented.

| Capability | Stable ACP v1 | Grok Build agent | PwrAgent ACP client | PwrAgent Codex App Server backend |
| --- | --- | --- | --- | --- |
| Initialize and capability negotiation | Yes | Yes | Yes | Yes, through App Server `initialize` |
| Implementation name/version | `clientInfo` / `agentInfo` | Partial: consumes client metadata but does not return standard `agentInfo` | Sends `clientInfo` | Sends client metadata and records server identity |
| Authentication | Methods, login, logout | Partial: auth methods and `authenticate`; no standard `logout` | No interactive ACP auth call; relies on an already-usable agent environment | Rich account/login/logout support |
| Start a session/thread | `session/new` | Yes | Yes | `thread/start` |
| Restore with replay | `session/load` | Yes | Yes | `thread/read` plus `thread/resume` |
| List sessions | `session/list` | Extension: `x.ai/session/list` | No standard call; uses PwrAgent-owned session metadata | `thread/list` |
| Resume without replay | `session/resume` | No standard method | No | `thread/resume` |
| Close active session | `session/close` | Extension: `x.ai/session/close` | No | Turn interruption and process lifecycle management |
| Delete history | `session/delete` | Extension: `x.ai/session/delete` | No | Archive/unarchive; PwrAgent does not equate archive with destructive deletion |
| Fork history | Draft/extension in the pinned SDK; v2 direction | Extension: `x.ai/session/fork` | No live ACP handoff/fork | `thread/fork` |
| Text prompts | Baseline | Yes | Yes | Yes |
| Resource links | Baseline | Yes | Client prompt builder does not emit them | Rich typed input and local context |
| Embedded resources | Capability-gated | Yes and advertised | Client prompt builder does not emit them | Rich typed input and local context |
| Image prompts | Capability-gated | **Yes after this fork advertises the already-implemented path** | Yes, including composer gating and transcript persistence | Yes, including URL and local-image items |
| Audio prompts | Capability-gated | No | No | Not exposed by PwrAgent's Codex composer |
| Agent message and thought streaming | Session updates | Yes | Yes | Yes, with richer item/delta events |
| Tool-call lifecycle and content | Session updates | Yes | Yes for text/status/location; image tool content is not promoted into transcript image parts | Yes for commands, file changes, MCP, dynamic tools, and other item types |
| Permission requests | Reverse request | Yes | Yes | Yes, with command/file-change approval variants |
| Structured elicitation | Reverse request | No standard method | No; reverse requests other than permission are rejected | Yes for `requestUserInput` and MCP elicitation |
| Client filesystem methods | Optional client capability | Agent can call them | PwrAgent advertises `false` and does not handle them | App Server owns its filesystem/sandbox boundary |
| Client terminal methods | Optional client capability | Agent can call them | PwrAgent advertises `false` and does not handle them | App Server owns command execution and streaming |
| Prompt cancellation | `session/cancel` | Yes | Yes | `turn/interrupt` |
| JSON-RPC request cancellation | `$/cancel_request` | No gateway routing | No | Connection layer handles App Server request lifecycle |
| Modes and models | Legacy mode/model methods and config options | Mode and model selectors | Yes, including compatibility fallbacks | Model, reasoning effort, collaboration mode, personality, approval policy, and sandbox settings |
| Generic/boolean config options | `session/set_config_option` | No generic implementation | Client can consume and set advertised options | Native App Server settings |
| Plans | Plan session update | Yes | Yes | `turn/plan/updated` and plan item deltas |
| Slash commands | Available-command update | Yes | Yes | Skills and command surfaces through App Server |
| MCP servers | Session setup and agent transport capabilities | HTTP and SSE advertised; session MCP configuration accepted | Supplies configured MCP servers | Native Codex MCP configuration and events |
| Additional workspace roots | Session lifecycle capability | No standard capability | PwrAgent linked directories are not passed through ACP | PwrAgent manages linked directories around App Server threads |
| Session usage/cost updates | Session update | Extension: `x.ai/session/usage` and xAI notifications | Partial custom normalization | Token-usage and rate-limit notifications |
| Session title/info updates | Session info update | xAI summary notification | Grok-specific title normalization | Native thread-name/status notifications |
| Message IDs | Optional stable v1 fields | Not advertised through the pinned gateway | Synthesizes stable local IDs when absent | Native thread/turn/item IDs |

## Image path

Grok's image data path already existed before this fork:

1. `session/prompt` accepts `ContentBlock::Image`.
2. `prompt_parser` separates image blocks from text and resources.
3. `image_normalize` validates, compresses, and re-encodes attachments.
4. The sampling layer sends native image content or uses the configured image
   description fallback.
5. Persistence and replay retain image content blocks.
6. File/PDF tools can emit ACP image content.

The interoperability bug was the initialization response:
`PromptCapabilities::new().embedded_context(true)` serialized `image: false`.
ACP requires omitted or false capabilities to be treated as unsupported.
This fork sets `.image(true)` and pins the wire shape with a regression test.

## Recommended implementation order

1. Ship the image capability fix and exercise it through PwrAgent's existing
   ACP image composer path.
2. Bundle the downstream executable and disable self-update for only that
   bundled launch descriptor.
3. Add a standard `agentInfo` response for compatibility diagnostics.
4. Upgrade Grok's gateway routing for the now-stable v1 lifecycle methods:
   `session/list`, `session/resume`, `session/close`, and `session/delete`.
   Reuse the existing xAI extension implementations where their semantics
   match.
5. Add PwrAgent client calls for standard session close/list/delete and
   structured elicitation.
6. Promote generic session config options, standard usage/info updates,
   additional directories, request cancellation, and message IDs.
7. Evaluate ACP v2 only after the stable v1 surface above is covered. The v2
   draft removes client filesystem/terminal methods and makes list, resume,
   and close part of the required session lifecycle, so it should be handled
   as a deliberate gateway migration rather than an SDK version bump.

## Primary references

- [ACP v1 initialization and capabilities](https://agentclientprotocol.com/protocol/v1/initialization)
- [ACP v1 authentication](https://agentclientprotocol.com/protocol/v1/authentication)
- [ACP v1 session setup](https://agentclientprotocol.com/protocol/v1/session-setup)
- [ACP v1 session list](https://agentclientprotocol.com/protocol/v1/session-list)
- [ACP v1 session delete](https://agentclientprotocol.com/protocol/v1/session-delete)
- [ACP v1 content blocks](https://agentclientprotocol.com/protocol/v1/content)
- [ACP v1 session config options](https://agentclientprotocol.com/protocol/v1/session-config-options)
- [ACP v1 elicitation](https://agentclientprotocol.com/protocol/v1/elicitation)
- [ACP v1 cancellation](https://agentclientprotocol.com/protocol/v1/cancellation)
- [ACP v1 schema](https://agentclientprotocol.com/protocol/v1/schema)
- [ACP v2 migration draft](https://agentclientprotocol.com/protocol/v2/migration)
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
