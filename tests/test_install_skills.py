from pathlib import Path
import pytest
from lacuna_wiki.cli.install_skills import copy_skills, SKILLS_DIR


def test_skills_dir_exists():
    assert SKILLS_DIR.is_dir()


def test_skills_dir_contains_ingest():
    assert (SKILLS_DIR / "ingest.md").exists()


def test_skills_dir_contains_adversary():
    assert (SKILLS_DIR / "adversary.md").exists()


def test_copy_skills_creates_subdirs(tmp_path):
    copy_skills(tmp_path)
    assert (tmp_path / "lacuna-ingest" / "SKILL.md").exists()
    assert (tmp_path / "lacuna-adversary" / "SKILL.md").exists()


def test_copy_skills_file_has_content(tmp_path):
    copy_skills(tmp_path)
    content = (tmp_path / "lacuna-ingest" / "SKILL.md").read_text()
    assert len(content) > 200
    assert "lacuna" in content


def test_copy_skills_overwrites_stale(tmp_path):
    dest_dir = tmp_path / "lacuna-ingest"
    dest_dir.mkdir()
    (dest_dir / "SKILL.md").write_text("old stale content")
    copy_skills(tmp_path)
    content = (dest_dir / "SKILL.md").read_text()
    assert content != "old stale content"
    assert len(content) > 200


def test_copy_skills_creates_target_dir(tmp_path):
    target = tmp_path / "new" / "subdir"
    copy_skills(target)
    assert (target / "lacuna-ingest" / "SKILL.md").exists()


def test_copy_skills_returns_paths(tmp_path):
    copied = copy_skills(tmp_path)
    assert len(copied) == 3
    names = {p.name for p in copied}
    assert names == {"SKILL.md"}
    # Each path should be inside its own lacuna-* dir
    parents = {p.parent.name for p in copied}
    assert "lacuna-ingest" in parents
    assert "lacuna-adversary" in parents
    assert "lacuna-query" in parents
