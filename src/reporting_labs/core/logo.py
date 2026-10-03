"""The logo option: a file path (embedded as a data URI), an http(s) URL or a data URI."""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path
from typing import Optional

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon"}


def resolve(logo: Optional[str], base: Path) -> Optional[str]:
    if not logo:
        return None
    if re.match(r"^(https?:|data:)", logo, re.I):
        return logo
    file = Path(logo) if Path(logo).is_absolute() else base / logo
    if not file.is_file():
        print(f"reporting-labs: logo not found at {file}", file=sys.stderr)
        return None
    mime = MIME.get(file.suffix.lower())
    if not mime:
        print(f"reporting-labs: logo {logo} is not a png, jpg, svg, gif, webp or ico file", file=sys.stderr)
        return None
    return f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode("ascii")
