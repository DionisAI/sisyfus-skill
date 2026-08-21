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
