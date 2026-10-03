"""Produces index.html from the bundled template, the way the Java reporter's TemplateRenderer does.

template.html is an exact snapshot of dist/template.html from the Node.js reporter, so the report layout, CSS
and JS are identical across ports. It carries three placeholders: __RL_DATA__ (the JSON payload, mandatory),
__RL_ACCENT_CSS__ and __RL_CUSTOM_CSS__.
"""
from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any, Dict

_P_DATA = "__RL_DATA__"
_P_ACCENT = "__RL_ACCENT_CSS__"
_P_CUSTOM = "__RL_CUSTOM_CSS__"
_HTML_TAG = re.compile(r"<html\b[^>]*>")
_FONT_BLOCK = re.compile(r"<style>@font-face[\s\S]*?</style>")
_GOOGLE_FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
                 '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">')
_cached: Dict[str, str] = {}


def template() -> str:
    if "html" not in _cached:
        _cached["html"] = resources.files("reporting_labs").joinpath("template.html").read_text("utf-8")
    return _cached["html"]


def to_json(data: Any) -> str:
    # A </script sequence inside a JSON string would end the rl-data script tag early. Same defence as the JS reporter.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).replace("</script", "<\\/script")


def render(data: Dict[str, Any]) -> str:
    opts = data.get("options") or {}
    accent = (opts.get("accent") or "").strip()
    accent_css = ":root{--accent:" + re.sub(r"[^#A-Za-z0-9(),.% -]", "", accent) + "!important}" if accent else ""
    custom_css = opts.get("customCss") or ""
    html = template()
    html = _replace_or_inject_style(html, _P_ACCENT, accent_css)
    html = _replace_or_inject_style(html, _P_CUSTOM, custom_css)
    if _P_DATA not in html:
        raise RuntimeError("reporting-labs: template.html is missing the __RL_DATA__ placeholder; the package is damaged")
    html = html.replace(_P_DATA, to_json(data), 1)
    if opts.get("embedFonts") is False:
        html = _FONT_BLOCK.sub(_GOOGLE_FONTS, html, count=1)
    html = _apply_theme(html, opts.get("theme") or "auto", opts.get("palette") or "lab")
    html = html.replace("<title></title>", "<title>" + _esc(str(data.get("title") or "Test report")) + "</title>", 1)
    return html


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _replace_or_inject_style(html: str, needle: str, css: str) -> str:
    if needle in html:
        return html.replace(needle, css, 1)
    if not css:
        return html
    i = html.find("</head>")
    return html if i < 0 else html[:i] + "<style>" + css + "</style>" + html[i:]


def _apply_theme(html: str, theme: str, palette: str) -> str:
    m = _HTML_TAG.search(html)
    if not m:
        return html
    tag = re.sub(r'\s+data-theme="[^"]*"', "", m.group(0))
    tag = re.sub(r'\s+data-palette="[^"]*"', "", tag)
    attrs = ""
    if theme and theme != "auto":
        attrs += ' data-theme="' + re.sub(r"[^A-Za-z0-9_-]", "", theme) + '"'
    if palette:
        attrs += ' data-palette="' + re.sub(r"[^A-Za-z0-9_-]", "", palette) + '"'
    tag = tag[:-1] + attrs + ">"
    return html[:m.start()] + tag + html[m.end():]
