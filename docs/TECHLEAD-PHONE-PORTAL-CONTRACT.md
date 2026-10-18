# Phone Portal S1 candidate contract v1 (2026-10-08)

This additive slice implements the Lead NEW4 proposal, not full-delivery acceptance.
Requested implementer: gpt-6.1-sol; runtime identity requires separate attestation.
Only portal_gateway/page/runtime/cli.py are production writes. Original share/lead/node source and old tests stay byte-identical.

## Frozen boundaries
- Password required, ShareGateway sessions/Host/Origin/CSP/nonce/deadline/admission/revoke retained. Operator bearer stays server-side. Default share unchanged.
- One controller-selected normalized absolute spec, SHA pinned; ONE chat create or explicit --chat-id adoption. No inventories/raw spec/argv/source/path/chat_id/mission_id public inputs or node enrollment.
- Binding/audit store, not task truth: fsync request before create/context; uncertain calls fenced, never resent (including after refresh). New exclusive 0600 files in owned runtime; no plaintext message/password/token saved.
- Guard actual source/spec_path/spec SHA/RSI config on every mutation; block existing chat_directory.directive and chat_rsi.instruction before upstream chat side effects. Normal chat state/proposal retained after whitelist projection.
- Prepare requires literal true + approval hash, Start requires ACK + same hash + separate literal true. Public placement restricted to actual frozen tasks and explicit 0..4 node allowlist (node_ + 32 hex). Node namespace never treated as Hub mission ID.
- One mutation in flight; persist hash-only request/outcome to fence UNKNOWN. Exactly repeated request returns readback, conflicting payload rejects. 201 chat creation and 202 chat mutation are admitted only on fixed Console endpoints; upstream total deadline remains 10s.
- Graph/progress/result from one snapshot capture; pinned report is separately versioned. Strict public field projections; remove secret/credential/raw-spec/argv fields recursively.
- Page: Chinese light 360px one-column, nonce CSP; memory-only session, timeout UNKNOWN and GET-only reconciliation, stale poll visible, refresh login/readback, clear private logout/401, no automatic resend.
- Stop/pause/resume remain local controller in S1; no public /api/control. No browser/native/provider/SSH/CF/password/physical phone call in implementation run.

## Evidence gates
Frozen new tests -> valid missing-public-feature assertion RED -> candidate GREEN using retained runner. DI HTTP fixtures and actual public Console/ChatSessions with fixture driver are separately labeled. S1 code tests do not establish independent Opus review, browser viewport, HTTPS, physical phone A8 or second host A7. These gates stay PENDING.

CLI: python -m sisyfus.workers.portal_cli --console-origin http://127.0.0.1:PORT --operator-token-file ABS --runtime-directory NEW_ABS --password-file ABS --spec-file ABS [--chat-id c_HEX32] [--node-id node_HEX32] [--report ABS] [--local-only]. Controller deployment uses the frozen APPROVED-DELIVERY-SPEC.json; synthetic test files are fixture-only.
