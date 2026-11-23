"""Resolve per-user configuration paths for MCP-tools."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


APP_NAME = "mcp-tools"
APP_AUTHOR = "Capunix"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LEGACY_CONFIG_PATH = REPOSITORY_ROOT / "config.toml"
LEGACY_ENV_PATH = REPOSITORY_ROOT / ".env"


def config_dir() -> Path:
    """Return the OS-standard per-user configuration directory.

    ``MCP_TOOLS_CONFIG_DIR`` is an optional override for managed deployments
    and tests. Normal installs use the platform's standard application config
    directory.
    """
    override = os.environ.get("MCP_TOOLS_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / APP_AUTHOR / APP_NAME
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def migrate_legacy_config(source: Path, destination: Path) -> bool:
    """Move an old checkout-local config once, without overwriting user data."""
    if destination.exists() or not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return True


def config_path(*, migrate: bool = True) -> Path:
    """Return the config file path, migrating the old checkout file if needed."""
    directory = config_dir()
    path = directory / "config.toml"
    if migrate and "MCP_TOOLS_CONFIG_DIR" not in os.environ:
        migrate_legacy_config(LEGACY_CONFIG_PATH, path)
    return path


def env_path() -> Path:
    """Return a user config `.env`, falling back to the legacy checkout file."""
    path = config_dir() / ".env"
    if path.is_file():
        return path
    if "MCP_TOOLS_CONFIG_DIR" in os.environ:
        return path
    if LEGACY_ENV_PATH.is_file():
        return LEGACY_ENV_PATH
    return path
