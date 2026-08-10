"""Tests for ``medsafe.config``.

Precedence is the thing worth pinning: a stale ``.env`` must never override an exported variable or
a docker-compose ``environment:`` block, or an operator changing a setting at deploy time would be
silently ignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from medsafe.config import Settings, load_settings, repo_root
from medsafe.errors import ConfigurationError


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n"
        "\n"
        "NEO4J_URI=bolt://from-file:7687\n"
        "NEO4J_PASSWORD=\"quoted-secret\"\n"
        "export FUZZY_CANDIDATE_THRESHOLD=91\n"
        "LOG_LEVEL=debug\n",
        encoding="utf-8",
    )
    return path


class TestEnvFileParsing:
    def test_values_are_read_from_the_file(self, env_file: Path):
        settings = load_settings(env_file=env_file)
        assert settings.neo4j_uri == "bolt://from-file:7687"
        assert settings.fuzzy_candidate_threshold == 91

    def test_quotes_are_stripped(self, env_file: Path):
        assert load_settings(env_file=env_file).neo4j_password == "quoted-secret"

    def test_export_prefix_is_tolerated(self, env_file: Path):
        assert load_settings(env_file=env_file).fuzzy_candidate_threshold == 91

    def test_comments_and_blank_lines_are_ignored(self, env_file: Path):
        assert load_settings(env_file=env_file).neo4j_user == "neo4j"

    def test_a_missing_file_falls_back_to_defaults(self, tmp_path: Path):
        settings = load_settings(env_file=tmp_path / "absent.env")
        assert settings.neo4j_uri == "bolt://localhost:7687"
        assert settings.fuzzy_candidate_threshold == 88

    def test_the_shipped_example_file_parses(self):
        settings = load_settings(env_file=repo_root() / ".env.example")
        assert settings.fuzzy_candidate_threshold == 88
        assert settings.neo4j_database == "neo4j"


class TestPrecedence:
    def test_process_environment_beats_the_env_file(self, env_file: Path, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://from-environ:7687")
        assert load_settings(env_file=env_file).neo4j_uri == "bolt://from-environ:7687"

    def test_explicit_overrides_beat_everything(self, env_file: Path, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://from-environ:7687")
        settings = load_settings(env_file=env_file, neo4j_uri="bolt://explicit:7687")
        assert settings.neo4j_uri == "bolt://explicit:7687"

    def test_an_empty_variable_does_not_shadow_a_default(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("NEO4J_DATABASE", "")
        assert load_settings(env_file=tmp_path / "absent.env").neo4j_database == "neo4j"

    def test_unrelated_variables_are_ignored(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("PATH_TO_SOMETHING_ELSE", "surprise")
        load_settings(env_file=tmp_path / "absent.env")  # must not raise


class TestPathHandling:
    def test_relative_data_paths_anchor_to_the_repo_root(self, tmp_path: Path):
        settings = load_settings(env_file=tmp_path / "absent.env")
        assert settings.data_processed_dir == repo_root() / "data" / "processed"
        assert settings.fuzzy_negative_blocklist.is_absolute()

    def test_absolute_paths_are_left_alone(self, tmp_path: Path):
        settings = load_settings(env_file=tmp_path / "absent.env", data_raw_dir=tmp_path)
        assert settings.data_raw_dir == tmp_path

    def test_seed_dir_is_optional(self, tmp_path: Path):
        assert load_settings(env_file=tmp_path / "absent.env").seed_dir is None


class TestValidation:
    def test_log_level_is_upper_cased(self, env_file: Path):
        assert load_settings(env_file=env_file).log_level == "DEBUG"

    def test_an_out_of_range_threshold_is_rejected(self, tmp_path: Path):
        with pytest.raises(ConfigurationError):
            load_settings(env_file=tmp_path / "absent.env", fuzzy_candidate_threshold=101)

    def test_an_unknown_graph_backend_is_rejected(self, tmp_path: Path):
        with pytest.raises(ConfigurationError):
            load_settings(env_file=tmp_path / "absent.env", graph_backend="postgres")

    def test_settings_are_immutable(self):
        from pydantic import ValidationError

        settings = Settings()
        with pytest.raises(ValidationError):
            settings.neo4j_uri = "bolt://mutated:7687"
