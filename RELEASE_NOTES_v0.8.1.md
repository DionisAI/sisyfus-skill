# Sisyfus v0.8.1

v0.8.1 adds versioned, atomic self-update and rollback for the Engine and Skill.

```bash
sisyfus update --check
sisyfus update --yes
sisyfus update --version 0.8.1 --yes
sisyfus update --status
sisyfus update --rollback
```

Stable releases prefer GitHub Release archives verified by SHA-256 manifests.
Automatic Notify or Auto mode uses systemd user timers on Linux and LaunchAgents
on macOS. Auto installs defer while research, verifier, Continuation, Decision,
or unknown-commit work is active. Restart the coding-agent session after a switch.


## Integrity and activation details

- Engine and Skill resolve through one `current` symlink, so activation is one
  compatibility-unit switch rather than two sequential copies.
- Installed release contents carry a local SHA-256 tree hash and are verified
  before reuse or rollback.
- Scheduled automatic installation requires a SHA-256 Release Manifest and is
  restricted to the Stable channel; Beta and Edge can be monitored in Notify mode.
- Any non-terminal research run, active attempt, verifier operation,
  Continuation, Decision, or unknown commit defers activation.
