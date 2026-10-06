"""Options: the same keys and defaults as ReportingLabsOptions in the Node.js reporter.

Sources, lowest to highest: built-in defaults, `[tool.reporting-labs]` in pyproject.toml, `reporting-labs.config.json`
(or the file REPORTING_LABS_CONFIG names), `reporting_labs_*` keys in pytest's ini file, then runtime overrides
from the environment: REPORTING_LABS_METADATA_<KEY> sets a header chip, REPORTING_LABS_TITLE / _THEME / _PALETTE /
_ACCENT / _LOGO / _OUTPUT_FOLDER / _OPEN the matching option. Keys may be written camelCase (as in Node) or snake_case.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .envdetect import detect_env_name

DEFAULTS: Dict[str, Any] = {
    "title": "Test report",
    "logo": None,
    "accent": None,
    "theme": "auto",
    "palette": "lab",
    "outputFolder": "reporting-labs",
    "outputFile": "index.html",
    "emitJson": True,
    "jsonFile": "report.json",
    "pdf": True,                 # also write a print-ready report.pdf (Playwright's Chromium, or an installed Chrome / Edge)
    "pdfFile": "report.pdf",
    "chromePath": None,          # the browser that prints report.pdf, when it is not found on its own (or CHROME_PATH)
    "embedAttachments": True,
    "embedLimit": 2 * 1024 * 1024,
    "embedVideos": False,
    "metadata": {},
    "envVar": None,
    "sections": [],
    "widgets": {},
    "dimensions": ["priority", "severity", "feature", "owner"],
    "dimensionOrder": {},
    "customCss": "",
    "embedFonts": True,
    "announce": True,
    "warnMissingMeta": True,
    "open": "on-failure",
    "project": None,
    "links": {},
    "maskKeys": [],
    "maskValues": [],
    "maskFromEnv": True,
    "history": {"enabled": True, "file": "reporting-labs.history.json", "keep": 30},
    "env": {},
    "editorLinks": None,
    "bdd": None,
    # Python-only
    "captureApi": True,          # record requests / httpx calls
    "apiMaxBody": 64 * 1024,     # bytes of a request or response body kept
    "screenshotOnFailure": True, # Playwright / Selenium: a screenshot of every live page when a test fails
    "stepsFromTools": True,      # Playwright / Selenium actions as steps
}

WIDGET_KEYS = ["runStrip", "outcome", "attention", "dimensions", "timeline", "durations", "tags", "slowest", "projects", "flaky", "environment", "skipped"]
META_KEYS = ["priority", "severity", "owner", "feature", "epic", "story", "issue", "testcaseid", "component", "team", "sprint", "ticket", "jira"]
SCALAR_ENV = {"TITLE": "title", "THEME": "theme", "PALETTE": "palette", "ACCENT": "accent", "LOGO": "logo", "OUTPUT_FOLDER": "outputFolder", "OPEN": "open"}


def camel(key: str) -> str:
    parts = key.replace("-", "_").split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:]) if len(parts) > 1 else key


def normalize(raw: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        ck = camel(str(k))
        if ck in ("history", "widgets", "project") and isinstance(v, Mapping):
            v = {camel(str(x)): y for x, y in v.items()}
        out[ck] = v
    return out


def _read_pyproject(root: Path) -> Dict[str, Any]:
    f = root / "pyproject.toml"
    if not f.is_file():
        return {}
    try:
        try:
            import tomllib  # Python 3.11+
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        data = tomllib.loads(f.read_text("utf-8"))
        return dict(data.get("tool", {}).get("reporting-labs", {}) or {})
    except Exception:
        return {}


def _read_json(file: Path) -> Dict[str, Any]:
    try:
        data = json.loads(file.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def find_config_file(root: Path, explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else root / p
    env = os.environ.get("REPORTING_LABS_CONFIG")
    if env:
        return Path(env)
    for name in ("reporting-labs.config.json", "reporting-labs.json"):
        if (root / name).is_file():
            return root / name
    return None


class Options:
    """Resolved options plus the folder they are relative to (`base`)."""

    def __init__(self, values: Dict[str, Any], base: Path, root: Path) -> None:
        self.values = values
        self.base = base
        self.root = root

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    @property
    def out_dir(self) -> Path:
        p = Path(str(self.values["outputFolder"]))
        return p if p.is_absolute() else self.base / p

    @property
    def history_file(self) -> Path:
        h = self.values["history"] or {}
        p = Path(str(h.get("file") or "reporting-labs.history.json"))
        return p if p.is_absolute() else self.base / p

    def history_enabled(self) -> bool:
        h = self.values["history"]
        return bool(h.get("enabled", True)) if isinstance(h, Mapping) else bool(h)

    def history_keep(self) -> int:
        h = self.values["history"]
        return int(h.get("keep", 30)) if isinstance(h, Mapping) else 30

    def dimensions(self) -> List[str]:
        return [str(d).lower() for d in (self.values.get("dimensions") or DEFAULTS["dimensions"])]

    def meta_keys(self) -> List[str]:
        seen: List[str] = []
        for k in [*self.dimensions(), *META_KEYS, *[str(x).lower() for x in (self.values.get("links") or {})]]:
            if k != "*" and k not in seen:
                seen.append(k)
        return seen

    def link_template(self, key: str) -> Any:
        star = None
        for k, v in (self.values.get("links") or {}).items():
            if str(k).lower() == key:
                return v
            if k == "*":
                star = v
        return star

    def link_urls(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for k, v in (self.values.get("links") or {}).items():
            out[str(k).lower()] = v if isinstance(v, str) else str((v or {}).get("url", ""))
        return out

    def report_options(self, logo: Optional[str], editor_links_default: bool) -> Dict[str, Any]:
        v = self.values
        widgets = {k: bool((v.get("widgets") or {}).get(k, True)) for k in WIDGET_KEYS}
        order = {"priority": ["P0", "P1", "P2", "P3", "P4"],
                 "severity": ["blocker", "critical", "major", "high", "medium", "normal", "minor", "low", "trivial"]}
        order.update({str(k): [str(x) for x in xs] for k, xs in (v.get("dimensionOrder") or {}).items()})
        out: Dict[str, Any] = {
            "theme": v.get("theme") or "auto", "palette": v.get("palette") or "lab", "embedFonts": v.get("embedFonts") is not False,
            "sections": list(v.get("sections") or []), "widgets": widgets, "dimensions": self.dimensions(), "dimensionOrder": order,
            "links": self.link_urls(), "customCss": v.get("customCss") or "",
            "editorLinks": editor_links_default if v.get("editorLinks") is None else bool(v.get("editorLinks")),
        }
        if logo:
            out["logo"] = logo
        if v.get("accent"):
            out["accent"] = v["accent"]
        if v.get("project"):
            out["project"] = v["project"]
        return out


def load(root: Path, overrides: Optional[Mapping[str, Any]] = None, config_file: Optional[str] = None,
         environ: Optional[Mapping[str, str]] = None) -> Options:
    """`root` is the project folder (pytest's rootdir, Robot's output dir). `overrides` come from the test
    framework's own config (pytest ini keys, Robot listener arguments) and sit above the files."""
    env = os.environ if environ is None else environ
    values: Dict[str, Any] = json.loads(json.dumps(DEFAULTS))
    base = root
    values.update(normalize(_read_pyproject(root)))
    cfg = find_config_file(root, config_file)
    if cfg and cfg.is_file():
        values.update(normalize(_read_json(cfg)))
        base = cfg.parent
    if overrides:
        values.update(normalize(overrides))
    # metadata: config, CI chips (branch / commit / ci) under it, then the environment name by convention, then explicit overrides.
    from .envdetect import ci_metadata
    metadata: Dict[str, str] = {}
    metadata.update(ci_metadata(env))
    metadata.update({str(k): str(v) for k, v in (values.get("metadata") or {}).items()})
    explicit_env = False
    for k, v in env.items():
        m = re.match(r"^REPORTING_LABS_METADATA_([A-Z0-9_]+)$", k)
        if m and v and v.strip():
            metadata[m.group(1).lower()] = v.strip()
            if m.group(1) == "ENV":
                explicit_env = True
    if not explicit_env:
        detected = detect_env_name(env, values.get("envVar"))
        if detected:
            metadata["env"] = detected
    values["metadata"] = metadata
    for ek, key in SCALAR_ENV.items():
        v = env.get("REPORTING_LABS_" + ek)
        if v and v.strip():
            values[key] = v.strip()
    if not isinstance(values.get("history"), Mapping):
        values["history"] = {"enabled": bool(values.get("history")), "file": "reporting-labs.history.json", "keep": 30}
    return Options(values, base, root)
