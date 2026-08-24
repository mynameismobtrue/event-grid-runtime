from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .core import sanitized_public


def node(node_id, status, *, inputs=None, outputs=None, evidence=None, failure_codes=None, side_effects=None, unlocked=None):
    now = datetime.now(timezone.utc).isoformat()
    return {"node_id": node_id, "status": status, "started_at": now, "completed_at": now,
            "inputs": inputs or {}, "outputs": outputs or {}, "evidence": evidence or [],
            "failure_codes": failure_codes or [], "side_effects": side_effects or [],
            "next_nodes_unlocked": unlocked or []}


def _checkpoint_safe(value: Any) -> Any:
    """Public checkpoints may contain aggregate state only, never live URLs, provider IDs or credentials."""
    cleaned = sanitized_public(value)
    if isinstance(cleaned, dict):
        return {str(key): _checkpoint_safe(item) for key, item in cleaned.items()}
    if isinstance(cleaned, list):
        return [_checkpoint_safe(item) for item in cleaned]
    if isinstance(cleaned, str) and cleaned.lower().startswith(("http://", "https://")):
        return "[REDACTED_URL]"
    return cleaned


def save_checkpoint(path: Path, **states):
    payload = _checkpoint_safe(states)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
