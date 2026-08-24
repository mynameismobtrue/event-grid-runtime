from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

def node(node_id, status, *, inputs=None, outputs=None, evidence=None, failure_codes=None, side_effects=None, unlocked=None):
    now = datetime.now(timezone.utc).isoformat()
    return {"node_id": node_id, "status": status, "started_at": now, "completed_at": now,
            "inputs": inputs or {}, "outputs": outputs or {}, "evidence": evidence or [],
            "failure_codes": failure_codes or [], "side_effects": side_effects or [],
            "next_nodes_unlocked": unlocked or []}

def save_checkpoint(path: Path, **states):
    prohibited = ("api_key", "authorization", "token", "cookie", "booking_url")
    payload = {k: v for k, v in states.items() if not any(x in k.lower() for x in prohibited)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
