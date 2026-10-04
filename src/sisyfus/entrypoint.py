"""Thin opt-in CLI dispatch; the legacy command implementation stays unchanged."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "workers":
        from .workers.cli import main as workers_main
        return workers_main(args[1:])
    if args and args[0] == "techlead":
        from .workers.lead_cli import main as techlead_main
        return techlead_main(args[1:])
    from .cli import main as legacy_main
    return legacy_main(args)
