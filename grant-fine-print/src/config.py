"""Configuration loading for Grant Fine Print.

The single source of truth is ``config.yaml``. This module only reads it and
resolves relative paths against the project root (the directory that contains
the config file), so the pipeline works from any working directory.

Importing this module has no side effects: nothing is read until
:func:`load_config` is called.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

DEFAULT_PATH = "config.yaml"

# Keys whose values are paths. Relative values are made absolute against the
# project root at load time.
_PATH_KEY_SUFFIXES = ("_dir", "_path")


def load_config(path: str = DEFAULT_PATH) -> dict:
    """Load ``path`` as YAML and resolve relative paths to absolute paths.

    The returned dict is a plain (mutable) mapping. A private ``_project_root``
    key is added pointing at the directory that contained the config file; it
    is used to locate sample/offline data without relying on the cwd.
    """
    config_path = Path(path).resolve()
    if not config_path.exists():
        return {"_project_root": str(Path(path).resolve().parent)}
    # Shell/Render variables take precedence over the local .env file.
    load_dotenv(config_path.parent / ".env", override=False)
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    if not isinstance(config, dict):
        raise ValueError(f"Config root must be a mapping, got {type(config).__name__}")

    root = config_path.parent
    _resolve_paths(config, root, parent_key="")
    _apply_environment_overrides(config)
    config["_project_root"] = str(root)
    return config


def _apply_environment_overrides(config: dict[str, Any]) -> None:
    """Apply non-secret runtime settings from environment variables.

    Secrets such as API keys remain in the process environment and are read by
    the provider adapter. Model IDs and provider settings are safe to expose as
    deployment configuration, so they can be supplied through .env or Render.
    """
    overrides = {
        "GFP_PROVIDER_BASE_URL": "extract.provider_base_url",
        "GFP_PROVIDER": "extract.provider",
        "GFP_BASE_MODEL": "extract.base_model",
        "GFP_FINE_TUNED_MODEL": "extract.fine_tuned_model",
        "GFP_SUPPORT_EMAIL": "app.support_email",
        "GFP_SUPPORT_PHONE": "app.support_phone",
    }
    for env_name, dotted_key in overrides.items():
        value = os.environ.get(env_name)
        if value is None:
            continue
        current: dict[str, Any] = config
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        current[parts[-1]] = value


def _resolve_paths(node: Any, root: Path, parent_key: str = "") -> None:
    """Recursively resolve path-looking string values in place.

    The ``api`` section is skipped: keys like ``search2_path`` are URL paths,
    not filesystem paths, and must not be rewritten.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "api":
                continue
            if (
                isinstance(key, str)
                and key.endswith(_PATH_KEY_SUFFIXES)
                and isinstance(value, str)
                and value
            ):
                candidate = Path(value)
                if not candidate.is_absolute():
                    node[key] = str((root / candidate).resolve())
            else:
                _resolve_paths(value, root, parent_key=key if isinstance(key, str) else "")
    elif isinstance(node, list):
        for item in node:
            _resolve_paths(item, root, parent_key=parent_key)


def get(config: dict, dotted_key: str, default: Any = None) -> Any:
    """Return ``config['a']['b']`` for ``dotted_key='a.b'`` or ``default``.

    Missing keys, non-dict intermediates, and empty keys all yield ``default``.
    """
    if not dotted_key:
        return default
    current: Any = config
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current
