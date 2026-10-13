"""Operator-owned dispatch configuration: allowlisted projects, hosts and agent policy."""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_HOME = Path("~/.sisyfus/dispatch")
DEFAULT_PORT = 8790
CONFIG_SCHEMA = "sisyfus.dispatch.config.v1"
_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class ConfigError(ValueError):
    """The operator configuration is missing or invalid."""


@dataclass
class DispatchConfig:
    home: Path
    projects: dict[str, str] = field(default_factory=dict)
    agent_command: list[str] = field(default_factory=lambda: ["claude"])
    model: str | None = None
    max_budget_usd: float = 20.0
    max_concurrent: int = 2
    allow_web: bool = False

    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    @property
    def password_path(self) -> Path:
        return self.home / "password.json"

    @property
    def sessions_path(self) -> Path:
        return self.home / "sessions.json"

    @property
    def jobs_dir(self) -> Path:
        return self.home / "jobs"

    def project_path(self, name: str) -> Path:
        if name not in self.projects:
            raise ConfigError(f"unknown project: {name}")
        return Path(self.projects[name])

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("home")
        return {"schema_version": CONFIG_SCHEMA, **data}


def resolve_home(home: str | Path | None) -> Path:
    return Path(home or DEFAULT_HOME).expanduser().resolve()


def ensure_home(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)


def write_private_json(path: Path, value: Any) -> None:
    """Atomically write a 0600 JSON file (configuration, sessions, verifier)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_config(home: str | Path | None = None) -> DispatchConfig:
    root = resolve_home(home)
    path = root / "config.json"
    if not path.exists():
        raise ConfigError(f"no dispatch configuration at {path}; run `sisyfus dispatch init` first")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"unreadable dispatch configuration: {exc}") from exc
    if raw.get("schema_version") != CONFIG_SCHEMA:
        raise ConfigError("unsupported dispatch configuration schema")
    config = DispatchConfig(
        home=root,
        projects={str(k): str(v) for k, v in (raw.get("projects") or {}).items()},
        agent_command=[str(part) for part in raw.get("agent_command") or ["claude"]],
        model=raw.get("model") or None,
        max_budget_usd=float(raw.get("max_budget_usd") or 20.0),
        max_concurrent=max(1, int(raw.get("max_concurrent") or 2)),
        allow_web=bool(raw.get("allow_web")),
    )
    # Only names are checked here: a project folder that later disappears must not block
    # `serve` or `project remove`; launching a job in it reports the problem instead.
    for name in config.projects:
        if not _PROJECT_NAME.match(name):
            raise ConfigError(f"invalid project name in configuration: {name}")
    return config


def save_config(config: DispatchConfig) -> None:
    ensure_home(config.home)
    write_private_json(config.config_path, config.to_json())


def validate_project(name: str, path: Path) -> Path:
    if not _PROJECT_NAME.match(name):
        raise ConfigError("project names use letters, digits, '.', '_' or '-' (max 64)")
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise ConfigError(f"project directory does not exist: {resolved}")
    if resolved == Path(resolved.anchor) or resolved == Path.home():
        raise ConfigError("refusing to allow a filesystem root or the home directory as a project")
    return resolved
