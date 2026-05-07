from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])

# routes/config.py → api/ → multi_agent/ → src/ → multi-agent-system/ → config/
_CONFIG_DIR = Path(__file__).parent.parent.parent.parent.parent / "config"


def _read_yaml(filename: str) -> dict[str, Any]:
    """Read and parse a YAML file from the config dir. Raises 404 if missing."""
    path = _CONFIG_DIR / filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config file '{filename}' not found",
        )
    try:
        with path.open("r") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Config file '{filename}' is not a YAML mapping",
            )
        return data
    except yaml.YAMLError as exc:
        logger.error("Failed to parse %s: %s", filename, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid YAML in '{filename}'",
        ) from exc


@router.get("/limits")
def get_limits_config() -> dict[str, Any]:
    """Return the raw contents of limits.yaml."""
    return _read_yaml("limits.yaml")


@router.get("/buckets")
def get_buckets_config() -> dict[str, Any]:
    """Return the raw contents of buckets.yaml."""
    return _read_yaml("buckets.yaml")
