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
  executable contract. New-project preparation and automatic checker generation
  are not yet implemented in chat; the UI states this explicitly and links to
  the relevant settings without borrowing unrelated demo checks.
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
