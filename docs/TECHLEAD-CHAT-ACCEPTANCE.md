# Conversational UI acceptance

This is the local `codex/techlead-chat` extension, not an update to the installed
0.9.0 release. Root `/` is the Chinese light chat UI; `/console` remains the
original developer console. Design context is in `.impeccable.md`.

## Required contract

- Discuss goals with real native read-only Opus before binding a mission.
- Reuse an existing operator-approved engineering contract, or attach a spec
  file through settings; no model-generated executable checks or JSON editor
  in the main conversation.
- Display advisory architecture/task/acceptance outlines, not fake execution.
- A proposal enables **检查并准备开工** even if project/checks are missing.
  Inspection renders separate proposal/source/acceptance/native-state requirements,
  is read-only, and never creates directories, reserves calls or dispatches agents.
  Offline or uncertain submissions show cached-state warnings and fence execution.
- Chat prose paths are not project bindings. Textual acceptance is not an approved
  executable contract. Explicit user chat directives now drive a separate
  controller-owned directory capability: reserve before exclusive mkdir, bind the
  exact prepared path, reset stale native cwd/session, and report the result.
  Existing paths, symbolic links, ambiguity and revoked instructions need chat
  clarification; no overwrite or unreceipted retry. Operator approval is not a
  requirement to handwrite code. Automatic checker generation remains pending;
  do not borrow unrelated demo checks.
- Confirm local execution deliberately and bind the exact displayed plan hash.
  A changed plan/source/approved contract invalidates old confirmation; ordinary
  unconfirmed chat updates do not announce a fictitious withdrawn approval.
- Keep the original approved goal, constraints, deliverables, checks, role
  models and budgets; append the confirmed conversational goal.
- Delegate execution, task truth and acceptance to the existing MissionHub and
  LeadMission. Chat messages and opening pages never start Sol.
- Durable request IDs prevent duplicate message/start dispatch; unreceipted
  in-flight work remains UNKNOWN on restart. Known pre-spawn errors remain
  actionable ERROR. Transport/native/draft errors remain observable.
- Retain independent review, deterministic checks and integration; ACK/native
  completion remains separate from acceptance. Missing runtime model telemetry
  is visibly missing; ambiguous/wrong native chat identities are rejected.

## Evidence

The browser created a conversation, reused the retained polling engineering
contract, sent a native planning message and displayed the returned plan.
Its actual runtime model was `claude-opus-5-5`. The operator-confirmation section
was checked with the execution checkbox unset: dispatch was disabled. This UI
validation did not start a new Sol mission or overwrite the source project.

Native Opus reviewed the chat backend. Initial findings and fixes are retained;
the final targeted review returned PASS with no findings, and runtime identity
was `claude-opus-5-5`.

Private receipts and screenshots are kept under
`artifacts/techlead/chat-ui-20261004/` (ignored by Git). Native raw events remain
private; they are never returned by the chat API. Chat drafts live in `.chats`,
while each task's existing autonomy database remains the task truth source.

Tests and final browser/responsive readback are recorded in the delivery receipt
in that private evidence directory, rather than treating this document as a
live status database.

### Directory-preparation follow-up

The controller created and bound the user's previously requested project path
through the real chat UI. Its exclusive-creation receipt matches the empty
0700 directory identity; existing messages and proposal remain intact. Native
receipt counts and mission inventory are unchanged. Acceptance remains unbound.

Focused chat/HTTP/page tests pass (192); the full workers suite passes (544).
The page harness additionally checks the directory button, native-state fences
and exact request-ID reconciliation. Preparation-to-native-context behavior is
covered by a protocol fixture, not a new provider invocation. The prior native
review above predates this directory follow-up. Private evidence is retained in
`artifacts/techlead/directory-20261005/`.
