from pathlib import Path
import pytest
from lacuna_wiki.config import load_config, write_default_config, CONFIG_FILE, _DEFAULTS


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    return tmp_path


def test_load_config_returns_defaults_when_no_file(vault):
    config = load_config(vault)
    assert config["embed_url"] == _DEFAULTS["embed_url"]
    assert config["embed_model"] == _DEFAULTS["embed_model"]


def test_load_config_reads_file(vault):
    (vault / CONFIG_FILE).write_text(
        '[embed]\nurl = "http://myserver:9000"\nmodel = "my-model"\n'
    )
    config = load_config(vault)
    assert config["embed_url"] == "http://myserver:9000"
    assert config["embed_model"] == "my-model"


def test_load_config_partial_override(vault):
    (vault / CONFIG_FILE).write_text('[embed]\nurl = "http://myserver:9000"\n')
    config = load_config(vault)
    assert config["embed_url"] == "http://myserver:9000"
    assert config["embed_model"] == _DEFAULTS["embed_model"]


def test_load_config_env_var_overrides_file(vault, monkeypatch):
    (vault / CONFIG_FILE).write_text('[embed]\nurl = "http://myserver:9000"\n')
    monkeypatch.setenv("LACUNA_EMBED_URL", "http://envserver:1234")
    config = load_config(vault)
    assert config["embed_url"] == "http://envserver:1234"


def test_load_config_env_var_overrides_defaults(vault, monkeypatch):
    monkeypatch.setenv("LACUNA_EMBED_MODEL", "custom-model")
    config = load_config(vault)
    assert config["embed_model"] == "custom-model"


def test_write_default_config_creates_file(vault):
    cfg = write_default_config(vault)
    assert cfg.exists()
    assert cfg.name == CONFIG_FILE


def test_write_default_config_is_valid_toml(vault):
    import tomllib
    write_default_config(vault)
    data = tomllib.loads((vault / CONFIG_FILE).read_text())
    assert "embed" in data
    assert "url" in data["embed"]
    assert "model" in data["embed"]


def test_write_default_config_does_not_overwrite(vault):
    (vault / CONFIG_FILE).write_text('[embed]\nurl = "http://custom:9999"\n')
    write_default_config(vault)
    config = load_config(vault)
    assert config["embed_url"] == "http://custom:9999"
