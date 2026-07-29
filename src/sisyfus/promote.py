from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .paths import ensure_layout
from .storage import MemoryBroker
from .utils import slugify, utc_now, write_json


def promote_repeated_failures(root: Path, *, threshold: int = 2) -> dict[str, Any]:
    sf = ensure_layout(root)
    broker = MemoryBroker(root)
    failures = broker.read_failures()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in failures:
        sig = f.get("signature") or slugify(f.get("claim", "unknown"))
        grouped[sig].append(f)

    generated = []
    out_root = sf / "promotions" / "skill-candidates"
    out_root.mkdir(parents=True, exist_ok=True)
    for sig, items in grouped.items():
        if len(items) < threshold:
            continue
        first = items[0]
        slug = slugify(first.get("claim", sig))[:80]
        skill_dir = out_root / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"""---\nname: avoid-{slug}\ndescription: Avoid repeated failure mode: {first.get('claim', sig)}\n---\n\n# Repeated Failure Mode\n\nGenerated: {utc_now()}\nSignature: `{sig}`\nOccurrences: {len(items)}\n\n## Claim\n\n{first.get('claim', '')}\n\n## Evidence\n\n"""
        for item in items[:10]:
            ev = item.get("evidence", {})
            content += f"- Run `{ev.get('run_id')}` command `{ev.get('command')}` exit `{ev.get('exit_code')}`\n"
        content += "\n## Guidance\n\nBefore attempting similar work, inspect the evidence above and design a narrower verifier-backed fix.\n"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        generated.append({"signature": sig, "count": len(items), "path": str(skill_dir / "SKILL.md")})

    result = {"generated_at": utc_now(), "threshold": threshold, "generated": generated}
    write_json(sf / "promotions" / "last_promote.json", result)
    return result
