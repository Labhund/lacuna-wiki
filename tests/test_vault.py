from pathlib import Path
import pytest
from llm_wiki.vault import find_vault_root, state_dir_for, db_path


def test_find_vault_root_from_vault_root(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    assert find_vault_root(tmp_path) == tmp_path


def test_find_vault_root_from_subdir(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    subdir = tmp_path / "wiki" / "ml" / "attention"
    subdir.mkdir(parents=True)
    assert find_vault_root(subdir) == tmp_path


def test_find_vault_root_returns_none_outside_vault(tmp_path):
    assert find_vault_root(tmp_path) is None


def test_find_vault_root_requires_both_dirs(tmp_path):
    (tmp_path / "wiki").mkdir()
    # raw/ is missing
    assert find_vault_root(tmp_path) is None


def test_state_dir_for_is_deterministic(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    d1 = state_dir_for(tmp_path)
    d2 = state_dir_for(tmp_path)
    assert d1 == d2


def test_state_dir_for_different_vaults_differ(tmp_path):
    vault_a = tmp_path / "vault_a"
    vault_b = tmp_path / "vault_b"
    for v in [vault_a, vault_b]:
        (v / "wiki").mkdir(parents=True)
        (v / "raw").mkdir(parents=True)
    assert state_dir_for(vault_a) != state_dir_for(vault_b)


def test_db_path_is_inside_state_dir(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    assert db_path(tmp_path).parent == state_dir_for(tmp_path)
    assert db_path(tmp_path).name == "vault.db"
