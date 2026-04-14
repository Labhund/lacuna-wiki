"""Vault-level configuration.

Config is read from {vault_root}/.lacuna.toml.
Environment variables override the file for one-off overrides or CI.

Load order (highest wins):
  1. Environment variable  (LACUNA_EMBED_URL, LACUNA_EMBED_MODEL)
  2. .lacuna.toml in vault root
  3. Built-in defaults
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

import tomli_w

CONFIG_FILE = ".lacuna.toml"

_DEFAULTS: dict = {
    "embed_url": "http://localhost:8005",
    "embed_model": "nomic-embed-text:v1.5",
    "embed_dim": 768,
    "mcp_port": 7654,
}


def load_config(vault_root: Path) -> dict:
    """Load config for vault_root, applying env var overrides.

    Returns a flat dict with keys: embed_url, embed_model.
    """
    config = dict(_DEFAULTS)

    cfg_file = vault_root / CONFIG_FILE
    if cfg_file.exists():
        data = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
        embed = data.get("embed", {})
        if "url" in embed:
            config["embed_url"] = embed["url"]
        if "model" in embed:
            config["embed_model"] = embed["model"]
        if "dim" in embed:
            config["embed_dim"] = int(embed["dim"])

    if cfg_file.exists():
        mcp = data.get("mcp", {})
        if "port" in mcp:
            config["mcp_port"] = int(mcp["port"])

    # Env var overrides (for CI / one-off runs without editing the file)
    if val := os.environ.get("LACUNA_EMBED_URL"):
        config["embed_url"] = val
    if val := os.environ.get("LACUNA_EMBED_MODEL"):
        config["embed_model"] = val
    if val := os.environ.get("LACUNA_EMBED_DIM"):
        config["embed_dim"] = int(val)
    if val := os.environ.get("LACUNA_MCP_PORT"):
        config["mcp_port"] = int(val)

    return config


def write_default_config(vault_root: Path) -> Path:
    """Write .lacuna.toml with defaults if it doesn't already exist.

    Returns the path to the config file.
    """
    cfg_file = vault_root / CONFIG_FILE
    if cfg_file.exists():
        return cfg_file

    data = {
        "embed": {
            "url": "http://localhost:11434",  # Ollama default — change if using another server
            "model": _DEFAULTS["embed_model"],
            "dim": _DEFAULTS["embed_dim"],
        },
        "mcp": {
            "port": _DEFAULTS["mcp_port"],
        },
    }
    cfg_file.write_bytes(tomli_w.dumps(data).encode("utf-8"))
    return cfg_file
