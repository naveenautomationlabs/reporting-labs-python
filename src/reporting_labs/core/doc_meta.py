"""Meta written in a docstring or a comment, so a team can tag tests without calling meta():

    def test_places_order(page):
        \"\"\"Places an order with a saved card.

        @owner naveen  @priority P0  @jira SHOP-12
        @smoke
        \"\"\"

`@key value` pairs become meta; a bare `@word` becomes a tag (so `@P0` / `@critical` still set priority and
severity). The same works in `#` comments right above the `def` (or its decorators), and on the class and the
module, which apply to every test inside. The test's own wins over its class, the class over the module;
@pytest.mark.meta and meta() in the test win over all of them. Same syntax as the Node.js reporter."""
from __future__ import annotations

import inspect
import re
from typing import Any, Dict, List, Optional, Tuple

_JSDOC = {"param", "arg", "argument", "returns", "return", "type", "typedef", "template", "example", "see", "link",
          "throws", "raises", "exception", "deprecated", "since", "property", "override", "default", "description",
          "summary", "version", "license", "file", "internal", "ignore"}
_PAIR = re.compile(r"(?:^|\s)@([A-Za-z][\w.-]*)(?:[ \t]*[:=][ \t]*|[ \t]+(?!@))?(.*?)(?=\s+@[A-Za-z][\w.-]*|$)")


def parse(text: str) -> Tuple[Dict[str, str], List[str]]:
    """`@key value` pairs and bare `@tags` in a docstring or comment. A value runs to the next ` @key` or the line end."""
    meta: Dict[str, str] = {}
    tags: List[str] = []
    for line in (text or "").splitlines():
        for m in _PAIR.finditer(line):
            key = m.group(1)
            if key.lower() in _JSDOC or key.startswith("pytest."):
                continue
            value = re.sub(r"^(['\"`])(.*)\1$", r"\2", m.group(2).strip()).strip()  # @owner 'naveen' -> naveen
            if value:
                meta[key.lower()] = value
            elif key not in tags:
                tags.append(key)
    return meta, tags


def _comment_above(lines: List[str], idx: int) -> str:
    """`#` comment lines directly above line index `idx` (0-based), skipping decorators."""
    i = idx - 1
    while i >= 0 and lines[i].strip().startswith("@"):
        i -= 1
    out: List[str] = []
    while i >= 0 and lines[i].strip().startswith("#"):
        out.insert(0, re.sub(r"^\s*#+\s?", "", lines[i]))
        i -= 1
    return "\n".join(out)


def _first_line(obj: Any) -> Optional[int]:
    try:
        return inspect.getsourcelines(obj)[1] - 1
    except (OSError, TypeError):
        return None


def for_item(item: Any) -> Tuple[Dict[str, str], List[str]]:
    """Meta and tags for a pytest item: module, then class, then the test function (each later one wins)."""
    cached = getattr(item, "_rl_doc_meta", None)
    if cached is not None:
        return cached
    meta: Dict[str, str] = {}
    tags: List[str] = []

    def add(text: str) -> None:
        m, t = parse(text)
        meta.update(m)
        tags.extend(x for x in t if x not in tags)

    module = getattr(item, "module", None)
    lines: List[str] = []
    try:
        lines = inspect.getsource(module).splitlines() if module is not None else []
    except (OSError, TypeError):
        lines = []
    if module is not None:
        add(inspect.getdoc(module) or "")
    for obj in (getattr(item, "cls", None), getattr(item, "function", None) or getattr(item, "obj", None)):
        if obj is None:
            continue
        start = _first_line(obj)
        if start is not None and lines:
            add(_comment_above(lines, start))
        add(getattr(obj, "__doc__", None) or "")
    result = (meta, tags)
    try:
        item._rl_doc_meta = result
    except Exception:
        pass
    return result
