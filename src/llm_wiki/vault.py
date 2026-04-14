from __future__ import annotations

import hashlib
from pathlib import Path

_STATE_ROOT = Path.home() / ".llm-wiki" / "vaults"


def state_dir_for(vault_root: Path) -> Path:
    """Derive a stable state directory path for a given vault root."""
    resolved = str(vault_root.resolve())
    slug = resolved.strip("/").replace("/", "-")[:60]
    short_hash = hashlib.sha256(resolved.encode()).hexdigest()[:8]
    return _STATE_ROOT / f"{slug}-{short_hash}"


def db_path(vault_root: Path) -> Path:
    """Path to the DuckDB file for this vault."""
    return state_dir_for(vault_root) / "vault.db"


def find_vault_root(start: Path | None = None) -> Path | None:
    """Walk up the directory tree from `start` to find a vault root.

    A vault root is a directory containing both wiki/ and raw/ subdirectories.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "wiki").is_dir() and (candidate / "raw").is_dir():
            return candidate
    return None
