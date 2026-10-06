"""Writes index.html and report.json, prints the announcement, opens the browser."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .options import Options
from .render import render


def write(data: Dict[str, Any], options: Options) -> Path:
    out_dir = options.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / str(options.get("outputFile") or "index.html")
    html.write_text(render(data), "utf-8")
    if options.get("emitJson") is not False:
        (out_dir / str(options.get("jsonFile") or "report.json")).write_text(json.dumps(data, ensure_ascii=False, default=str), "utf-8")
    if options.get("pdf") is not False:
        try:
            write_pdf(html, options)
        except Exception:
            pass  # a PDF failure must never fail the run; the HTML report and its Export PDF button remain
    return html


def write_pdf(html: Path, options: Options) -> Optional[Path]:
    """Render the report's print layout to report.pdf. Tries the Chromium that Playwright ships, then an
    installed Chrome, Edge or Chromium with --print-to-pdf. Returns the path on success, else None."""
    pdf = html.parent / str(options.get("pdfFile") or "report.pdf")
    try:
        pdf.unlink()  # never leave a previous run's PDF next to this run's report
    except OSError:
        pass
    url = html.resolve().as_uri()
    explicit = options.get("chromePath") or os.environ.get("CHROME_PATH")
    # 1) Playwright, if it and its Chromium are installed (skipped when a browser is named explicitly)
    if not explicit:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    page = browser.new_page()
                    page.goto(url, wait_until="load")
                    page.evaluate("async () => { if (window.reportingLabsPreparePrint) await window.reportingLabsPreparePrint(); }")
                    page.pdf(path=str(pdf), print_background=True, prefer_css_page_size=True)
                finally:
                    browser.close()
            if pdf.is_file() and pdf.stat().st_size:
                return pdf
        except Exception:
            pass
    # 2) an installed Chrome / Edge / Chromium, driven headless (the report builds its print layout on ?rl-print)
    chrome = str(explicit) if explicit and Path(str(explicit)).is_file() else _find_chrome()
    if chrome:
        try:
            subprocess.run(
                [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                 "--virtual-time-budget=8000", "--run-all-compositor-stages-before-draw",
                 "--print-to-pdf=" + str(pdf), url + "?rl-print=1"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=False)
            if pdf.is_file() and pdf.stat().st_size:
                return pdf
        except Exception:
            pass
    return None


def _find_chrome() -> Optional[str]:
    """Any Chromium-based browser can print the report: Chrome, Edge (on every Windows machine) or Chromium."""
    candidates: List[str] = []
    if sys.platform == "darwin":
        candidates += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                       "/Applications/Chromium.app/Contents/MacOS/Chromium",
                       "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    elif os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                               os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")]
    for c in candidates:
        if Path(c).is_file():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
                 "microsoft-edge", "microsoft-edge-stable", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    for c in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium"):
        if Path(c).is_file():
            return c
    return None


def announce_lines(html: Path, data: Dict[str, Any], options: Options) -> List[str]:
    if options.get("announce") is False:
        return []
    try:
        rel = os.path.relpath(html)
    except ValueError:
        rel = str(html)
    lines = [f"reporting-labs: report written to {rel}"]
    if options.get("pdf") is not False:
        pdf = html.parent / str(options.get("pdfFile") or "report.pdf")
        if pdf.is_file() and pdf.stat().st_size:
            try:
                prel = os.path.relpath(pdf)
            except ValueError:
                prel = str(pdf)
            lines.append(f"reporting-labs: PDF written to {prel}")
        else:
            lines.append("reporting-labs: PDF skipped - no Chrome, Edge or Chromium found "
                         "(set chromePath, or pdf: false to silence)")
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
    lines.append("    Add meta(priority='P1', owner='name', feature='area') to the test, or put it in the docstring:")
    lines.append('    """@priority P1 @owner name @feature area""". Set warnMissingMeta: false to hide this.')
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
