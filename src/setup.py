"""Initialize the per-user MCP-tools configuration directory."""

from __future__ import annotations

import shutil

from .shared.paths import REPOSITORY_ROOT, config_path


def main() -> None:
    """Create the user config directory and seed config.toml when needed."""
    path = config_path()
    if path.exists():
        print(f"MCP-tools configuration: {path}")
        return

    example = REPOSITORY_ROOT / "config.example.toml"
    if not example.is_file():
        raise SystemExit(f"Configuration template not found: {example}")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(example, path)
    print(f"Created MCP-tools configuration: {path}")
    print("Edit this file, then configure credentials with `python -m src.credentials set <jira|xwiki|sheets>`.")


if __name__ == "__main__":
    main()
