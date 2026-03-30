"""Tests for the Ollama model management utilities."""

import subprocess
from unittest.mock import MagicMock, patch

from a2a_handler.server.ollama import check_ollama_model, get_ollama_models


class TestGetOllamaModels:
    """Tests for get_ollama_models function."""

    @patch("a2a_handler.server.ollama.subprocess.run")
    def test_get_ollama_models_success(self, mock_run):
        """Test successful parsing of ollama list output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="NAME\nllama3.2:latest\ngemma:7b\n",
        )

        models = get_ollama_models()

        assert models == ["llama3.2:latest", "gemma:7b"]
        mock_run.assert_called_once_with(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    @patch("a2a_handler.server.ollama.subprocess.run")
    def test_get_ollama_models_failure(self, mock_run):
        """Test non-zero return code returns empty list."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        models = get_ollama_models()

        assert models == []

    @patch("a2a_handler.server.ollama.subprocess.run")
    def test_get_ollama_models_not_installed(self, mock_run):
        """Test FileNotFoundError when ollama is not installed."""
        mock_run.side_effect = FileNotFoundError("ollama not found")

        models = get_ollama_models()

        assert models == []

    @patch("a2a_handler.server.ollama.subprocess.run")
    def test_get_ollama_models_timeout(self, mock_run):
        """Test TimeoutExpired returns empty list."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ollama list", timeout=10)

        models = get_ollama_models()

        assert models == []

    @patch("a2a_handler.server.ollama.subprocess.run")
    def test_get_ollama_models_empty_output(self, mock_run):
        """Test output with only header line returns empty list."""
        mock_run.return_value = MagicMock(returncode=0, stdout="NAME\n")

        models = get_ollama_models()

        assert models == []


class TestCheckOllamaModel:
    """Tests for check_ollama_model function."""

    @patch("a2a_handler.server.ollama.get_ollama_models")
    def test_check_ollama_model_found(self, mock_get_models):
        """Test model is found when it matches exactly."""
        mock_get_models.return_value = ["llama3.2:latest", "gemma:7b"]

        assert check_ollama_model("llama3.2:latest") is True

    @patch("a2a_handler.server.ollama.get_ollama_models")
    def test_check_ollama_model_not_found(self, mock_get_models):
        """Test model is not found."""
        mock_get_models.return_value = ["llama3.2:latest", "gemma:7b"]

        assert check_ollama_model("mistral:latest") is False

    @patch("a2a_handler.server.ollama.get_ollama_models")
    def test_check_ollama_model_matches_base_name(self, mock_get_models):
        """Test model matches by base name prefix."""
        mock_get_models.return_value = ["llama3.2:latest"]

        assert check_ollama_model("llama3.2:1b") is True
