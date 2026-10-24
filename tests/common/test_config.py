"""Tests for the config file helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from a2a_handler.common import config


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "handler"
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", config_dir / "config.json")
    return config_dir / "config.json"


def test_theme_defaults_when_there_is_no_config(config_file: Path) -> None:
    assert not config_file.exists()
    assert config.get_theme() == config.DEFAULT_THEME


def test_save_theme_round_trips(config_file: Path) -> None:
    config.save_theme("nord")
    assert json.loads(config_file.read_text()) == {"theme": "nord"}
    assert config.get_theme() == "nord"


def test_save_theme_keeps_other_settings(config_file: Path) -> None:
    config_file.parent.mkdir()
    config_file.write_text(json.dumps({"theme": "nord", "other": 1}))
    config.save_theme("dracula")
    assert json.loads(config_file.read_text()) == {"theme": "dracula", "other": 1}


def test_corrupt_config_falls_back_to_defaults(
    config_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_file.parent.mkdir()
    config_file.write_text("{not json")
    with caplog.at_level(logging.WARNING, logger="a2a_handler.common.config"):
        assert config.get_theme() == config.DEFAULT_THEME
    assert "Failed to load config" in caplog.text


def test_unwritable_config_is_logged_not_raised(
    config_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_file.mkdir(parents=True)
    with caplog.at_level(logging.WARNING, logger="a2a_handler.common.config"):
        config.save_theme("nord")
    assert "Failed to save config" in caplog.text
