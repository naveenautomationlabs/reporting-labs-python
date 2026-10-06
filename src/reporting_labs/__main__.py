"""python -m reporting_labs snippets [--force]: VS Code snippets for meta in docstrings and comments."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

USAGE = """reporting_labs

  python -m reporting_labs snippets          add VS Code snippets: rlmeta (docstring meta), rltest (pytest test)
  python -m reporting_labs snippets --force  replace an existing .vscode/reporting-labs.code-snippets

pytest needs nothing else: the plugin turns itself on when the package is installed.
"""


def snippets(force: bool = False) -> str:
    target = Path(".vscode") / "reporting-labs.code-snippets"
    if target.exists() and not force:
        return ".vscode/reporting-labs.code-snippets already exists (use --force to replace it)."
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("snippets.code-snippets"), target)
    return "Created .vscode/reporting-labs.code-snippets: in VS Code type rlmeta or rltest and press Tab."


def main(argv: list) -> int:
    if argv[:1] == ["snippets"]:
        print(snippets("--force" in argv))
        return 0
    print(USAGE)
    return 0 if not argv else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
