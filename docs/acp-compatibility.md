# ACP compatibility review for PwrAgent

Reviewed against the stable ACP v1 documentation and the PwrAgent source on
2026-08-14. ACP v2 is still documented as draft and is not a release target
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
| Mid-turn steering | No stable v1 method | Extension: `x.ai/session/steer` (legacy alias `x.ai/interject`) | Can invoke the extension on a resident Grok ACP session | Native mid-turn steering |
| JSON-RPC request cancellation | `$/cancel_request` | No gateway routing | No | Connection layer handles App Server request lifecycle |
| Modes and models | Legacy mode/model methods and config options | Mode and model selectors | Yes, including compatibility fallbacks | Model, reasoning effort, collaboration mode, personality, approval policy, and sandbox settings |
| Generic/boolean config options | `session/set_config_option` | No generic implementation | Client can consume and set advertised options | Native App Server settings |
| Workflow child-agent budget | No standard option | Extension: `x.ai/session/workflow_budget` | Can set a resident Grok session policy through the extension | Backend-specific collaboration controls |
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

## Mid-turn steering extension

Stable ACP v1 has prompt submission and cancellation, but no operation that
adds user context to a turn without cancelling it. Grok exposes the logical
extension method `x.ai/session/steer`; because ACP custom methods carry a `_`
prefix on raw JSON-RPC, clients send `_x.ai/session/steer` on the wire.
`x.ai/interject` remains an equivalent compatibility alias.

Request params use the existing Grok interjection shape:

```json
{
  "sessionId": "session-id",
  "text": "Keep the current work, but add a regression test.",
  "interjectionId": "optional-client-dedup-id",
  "content": []
}
```

`sessionId` and non-blank `text` are required. `interjectionId` is optional
and is echoed only on Grok's `x.ai/session/interjection` broadcast so an
originating UI can deduplicate its optimistic rendering. `content` is
optional; it may carry ACP text and image blocks. The first non-blank text
block is the model-safe text override, while image blocks use the same image
normalization path as native steering.

A successful ACP extension response retains Grok's extension envelope:

```json
{
  "result": {
    "status": "queued",
    "delivery": "currentTurn"
  }
}
```

`delivery` is `currentTurn` when the resident actor buffered the message for
the next native safe gap (loop top, after a tool batch, or before turn return).
It is `nextTurn` when the active turn settled before the actor accepted the
command; in that race Grok promotes the message to the next standalone turn
instead of dropping it. Success acknowledges actor acceptance, not that the
model has already consumed the message; cancelling before a safe gap retains
native cancellation semantics.

Malformed or blank input returns ACP/JSON-RPC `invalid_params`. An unknown
session returns `resource_not_found`. A closed or stopped resident session
returns `internal_error`; the handler no longer reports success after a
failed mailbox write.

## Session workflow-budget extension

Grok's ACP surface has no standard config option for workflow `agent_budget`.
The logical extension `x.ai/session/workflow_budget` (raw wire method
`_x.ai/session/workflow_budget`) reads or partially updates the resident
session policy:

```json
{
  "sessionId": "session-id",
  "defaultAgentBudget": 64,
  "maxAgentBudget": 256
}
```

Both budget fields are optional, so omitting one preserves its current value;
omitting both reads the policy. The response is
`{"result":{"defaultAgentBudget":64,"maxAgentBudget":256}}`.
Values must be integers in `1..=1024`, and the default cannot exceed the
maximum.

These fields have deliberately different semantics:

- `defaultAgentBudget` replaces the built-in default of 128 only when a new
  workflow omits its per-workflow `agent_budget`.
- `maxAgentBudget` defaults to 1024 and is an enforced ceiling for every later
  workflow launch or resume. An explicit per-workflow value still overrides
  the default, but a value above the session maximum is rejected rather than
  silently clamped.

The policy is resident-session state and is not persisted. Changing it does
not rewrite an already active run's admitted budget. A later resume is a new
admission and must satisfy the then-current maximum. Invalid policy updates
return `invalid_params`; missing/stopped sessions use the same errors as the
steering extension.

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
