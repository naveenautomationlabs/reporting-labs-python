"""The rolling run history next to the config: the same file and format as the Node.js and Java reporters."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

OUTCOME_CODE = {"passed": "p", "flaky": "k", "skipped": "s"}


def load(file: Path) -> List[Dict[str, Any]]:
    try:
        data = json.loads(file.read_text("utf-8"))
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except Exception:
        return []   # first run, or a corrupt file: start fresh


def entry(start: float, duration: float, stats: Dict[str, int], tests: List[Dict[str, Any]], label: Optional[str]) -> Dict[str, Any]:
    per_test: Dict[str, list] = {}
    for t in tests:
        last = t["results"][-1] if t["results"] else None
        per_test[t["key"]] = [OUTCOME_CODE.get(t["outcome"], "f"), round(last["duration"] if last else t["duration"])]
    e: Dict[str, Any] = {
        "time": start, "duration": duration,
        "passed": stats["passed"], "failed": stats["failed"] + stats["timedOut"] + stats["interrupted"],
        "flaky": stats["flaky"], "skipped": stats["skipped"], "total": stats["total"],
    }
    if label:
        e["label"] = label
    e["tests"] = per_test
    return e


def roll(entries: List[Dict[str, Any]], current: Dict[str, Any], keep: int) -> List[Dict[str, Any]]:
    out = entries + [current]
    return out[-keep:] if keep > 0 else out


def save(file: Path, entries: List[Dict[str, Any]]) -> None:
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(entries, indent=1), "utf-8")
    except OSError:
        pass   # read-only file system
