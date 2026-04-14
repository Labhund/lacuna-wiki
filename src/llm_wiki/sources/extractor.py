from __future__ import annotations

import subprocess
from pathlib import Path


def extract_text(path: Path) -> str:
    """Extract text from a source file.

    .md / .markdown — read directly (immutable raw content).
    .pdf            — shell out to pdftotext (requires poppler-utils).
    Anything else   — raises ValueError.
    """
    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")

    suffix = path.suffix.lower()

    if suffix in (".md", ".markdown"):
        return path.read_text(encoding="utf-8")

    if suffix == ".pdf":
        return _pdftotext(path)

    raise ValueError(f"Unsupported file type: {suffix!r}. Supported: .md, .pdf")


def _pdftotext(path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pdftotext failed (exit {result.returncode}): "
            f"{result.stderr.decode('utf-8', errors='replace')[:300]}"
        )
    return result.stdout.decode("utf-8", errors="replace")
