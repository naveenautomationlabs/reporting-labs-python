"""Writes index.html and report.json, prints the announcement, opens the browser."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from .options import Options
from .render import render


def write(data: Dict[str, Any], options: Options) -> Path:
    out_dir = options.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / str(options.get("outputFile") or "index.html")
    html.write_text(render(data), "utf-8")
    if options.get("emitJson") is not False:
        (out_dir / str(options.get("jsonFile") or "report.json")).write_text(json.dumps(data, ensure_ascii=False, default=str), "utf-8")
    return html


def announce_lines(html: Path, data: Dict[str, Any], options: Options) -> List[str]:
    if options.get("announce") is False:
        return []
    try:
        rel = os.path.relpath(html)
    except ValueError:
        rel = str(html)
    lines = [f"reporting-labs: report written to {rel}"]
    lines += missing_meta(data["tests"], options)
    return lines


def missing_meta(tests: List[Dict[str, Any]], options: Options) -> List[str]:
    """One short list of tests that carry no meta at all, like printMissingMeta in reporter.ts."""
    if options.get("warnMissingMeta") is False:
        return []
    seen = set()
    missing = []
    for t in tests:
        where = f"{t['file']}:{t['line']}"
        if not t["meta"] and where not in seen:
            seen.add(where)
            missing.append(t)
    if not missing:
        return []
    total = len({f"{t['file']}:{t['line']}" for t in tests})
    show = missing[:15]
    width = max(len(f"{t['file']}:{t['line']}") for t in show)
    lines = [f"reporting-labs: {len(missing)} of {total} tests have no meta"]
    lines += [f"    {(t['file'] + ':' + str(t['line'])).ljust(width)}  {t['title']}" for t in show]
    if len(missing) > len(show):
        lines.append(f"    … and {len(missing) - len(show)} more")
    lines.append("    Add meta(priority='P1', owner='name', feature='area') to the test. Set warnMissingMeta: false to hide this.")
    return lines


def maybe_open(html: Path, run_status: str, options: Options) -> None:
    """Open the report in the default browser, like the other reporters. Never in CI."""
    mode = options.get("open") or "on-failure"
    if mode == "never" or os.environ.get("CI"):
        return
    if mode == "on-failure" and run_status == "passed":
        return
    try:
        f = str(html.resolve())
        if sys.platform == "darwin":
            cmd = ["open", f]
        elif sys.platform.startswith("win"):
            os.startfile(f)  # type: ignore[attr-defined]
            return
        else:
            cmd = ["xdg-open", f]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass   # no opener available; the path was printed
