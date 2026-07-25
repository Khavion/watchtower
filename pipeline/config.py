"""Config + path helpers. YAML is loaded fresh per call site that needs it;
these files are small and runs are minutes apart."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
BRAIN_DIR = REPO_ROOT / "brain"
DATA_DIR = REPO_ROOT / "data"


def load_yaml(name: str, config_dir: Path | None = None) -> dict:
    path = (config_dir or CONFIG_DIR) / f"{name}.yaml"
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def caps() -> dict:
    return load_yaml("caps")


def sources() -> dict:
    return load_yaml("sources")


def schedule() -> dict:
    return load_yaml("schedule")


def providers() -> dict:
    return load_yaml("providers")


def ensure_data_dirs() -> None:
    for sub in ("accounts", "solicitations", "runs"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
