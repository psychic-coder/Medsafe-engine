"""Application configuration.

Single source of truth for runtime settings, loaded from environment variables (and a local
``.env``) into a Pydantic v2 settings model: Neo4j connection details (URI, user, password,
database), API host/port/log level, the ``data/{raw,processed,manual}`` directory paths used by the
ingestion scripts, and entity-resolution tuning — the fuzzy *candidate* threshold and the path to
``fuzzy_negative_blocklist.csv``. The fuzzy threshold governs which pairs enter the human-review
queue only; it is never an auto-accept threshold (see ``docs/schema.md``). Every other module reads
configuration from here rather than touching ``os.environ`` directly.

``.env`` parsing is deliberately hand-rolled (~30 lines) rather than pulling in
``pydantic-settings``
or ``python-dotenv``: the format in ``.env.example`` is plain ``KEY=VALUE``, and the dependency set
is meant to stay small. Precedence is process environment > ``.env`` file > declared default, so an
exported variable or a docker-compose ``environment:`` block always wins over a stale local file.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from medsafe.errors import ConfigurationError

__all__ = ["Settings", "get_settings", "load_settings", "reset_settings_cache", "repo_root"]

# The repo root is three parents up from this file: src/medsafe/config.py -> src/medsafe -> src -> .
_REPO_ROOT = Path(__file__).resolve().parents[2]

GraphBackend = Literal["neo4j", "memory"]


def repo_root() -> Path:
    """Absolute path to the repository root, used to anchor the relative ``data/`` paths."""
    return _REPO_ROOT


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` ``.env`` file. Blank lines and ``#`` comments are ignored."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


class Settings(BaseModel):
    """Validated runtime settings. Construct via :func:`get_settings`, not directly."""

    # validate_default is required, not cosmetic: without it Pydantic skips the path-anchoring
    # validator for any field left at its default, so an unset DATA_PROCESSED_DIR would stay
    # relative and resolve against the current working directory instead of the repo root.
    model_config = {"frozen": True, "extra": "ignore", "validate_default": True}

    # --- Neo4j connection ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # Browser clients (the Next.js web UI) are blocked by the same-origin policy unless the API
    # sends CORS headers. Comma-separated origin list; "*" allows any origin, which is convenient
    # for local development but should be narrowed for any deployment.
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Graph backend selection ---
    # "neo4j" is the real backend. "memory" runs the same read/write contract against an in-process
    # store seeded from ``seed_dir`` — it exists so tests and a local run do not require a database.
    # It is a backend swap, not a dataset swap: point ``seed_dir`` at ``data/processed`` to serve
    # the real catalogue without Neo4j. ``data/demo`` is a 15-molecule test fixture and must not be
    # served to a user, who would get real-looking answers from a catalogue that omits their drug.
    graph_backend: GraphBackend = "neo4j"
    seed_dir: Path | None = None

    # --- Data paths (relative paths are resolved against the repo root) ---
    data_raw_dir: Path = Path("data/raw")
    data_processed_dir: Path = Path("data/processed")
    data_manual_dir: Path = Path("data/manual")

    # --- Entity resolution tuning ---
    # Scores at/above this become human-review CANDIDATES. Never an auto-accept threshold.
    fuzzy_candidate_threshold: int = Field(default=88, ge=0, le=100)
    fuzzy_max_candidates: int = Field(default=5, ge=1, le=50)
    fuzzy_negative_blocklist: Path = Path("data/manual/fuzzy_negative_blocklist.csv")

    # --- Combination brands ---
    # Emitted by scripts/build_brand_aliases.py. Absent file => combination pack names do not
    # resolve, which is the same fail-closed direction as the other side artifacts.
    combinations_file: Path = Path("data/processed/combinations.csv")

    # --- Interaction coverage ---
    # Manifest emitted by scripts/ingest_ddinter.py recording which ATC groups a load actually
    # covered. Absent manifest => nothing is provably covered => every pair reports "not checked".
    coverage_manifest: Path = Path("data/processed/ddinter_coverage.json")

    @property
    def cors_origin_list(self) -> list[str]:
        """``cors_allow_origins`` split into the list Starlette's middleware expects."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @field_validator(
        "data_raw_dir",
        "data_processed_dir",
        "data_manual_dir",
        "fuzzy_negative_blocklist",
        "coverage_manifest",
        "combinations_file",
        "seed_dir",
        mode="after",
    )
    @classmethod
    def _anchor_to_repo_root(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        return value if value.is_absolute() else (_REPO_ROOT / value)

    @field_validator("log_level", mode="after")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()


# Maps environment variable names to Settings field names. Anything not listed is ignored, so an
# unrelated variable in the ambient environment can never silently alter engine behaviour.
_ENV_MAP: dict[str, str] = {
    "NEO4J_URI": "neo4j_uri",
    "NEO4J_USER": "neo4j_user",
    "NEO4J_PASSWORD": "neo4j_password",
    "NEO4J_DATABASE": "neo4j_database",
    "API_HOST": "api_host",
    "API_PORT": "api_port",
    "LOG_LEVEL": "log_level",
    "CORS_ALLOW_ORIGINS": "cors_allow_origins",
    "MEDSAFE_GRAPH_BACKEND": "graph_backend",
    "MEDSAFE_SEED_DIR": "seed_dir",
    "DATA_RAW_DIR": "data_raw_dir",
    "DATA_PROCESSED_DIR": "data_processed_dir",
    "DATA_MANUAL_DIR": "data_manual_dir",
    "FUZZY_CANDIDATE_THRESHOLD": "fuzzy_candidate_threshold",
    "FUZZY_MAX_CANDIDATES": "fuzzy_max_candidates",
    "FUZZY_NEGATIVE_BLOCKLIST": "fuzzy_negative_blocklist",
    "COVERAGE_MANIFEST": "coverage_manifest",
    "COMBINATIONS_FILE": "combinations_file",
}


def load_settings(env_file: Path | str | None = None, **overrides: object) -> Settings:
    """Build a :class:`Settings` from ``.env`` + process environment, uncached.

    Precedence: ``overrides`` > ``os.environ`` > ``env_file`` > field defaults.
    """
    env_path = Path(env_file) if env_file is not None else _REPO_ROOT / ".env"
    merged: dict[str, str] = _parse_env_file(env_path)
    merged.update(os.environ)

    values: dict[str, object] = {}
    for env_key, field_name in _ENV_MAP.items():
        raw = merged.get(env_key)
        if raw is not None and raw != "":
            values[field_name] = raw
    values.update(overrides)

    try:
        return Settings(**values)
    except ValidationError as exc:  # pragma: no cover - exercised via test_config
        raise ConfigurationError("Invalid runtime configuration", detail=exc.errors()) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings. This is the accessor every other module should use."""
    return load_settings()


def reset_settings_cache() -> None:
    """Clear the cached settings. For tests and for reload after an environment change."""
    get_settings.cache_clear()
