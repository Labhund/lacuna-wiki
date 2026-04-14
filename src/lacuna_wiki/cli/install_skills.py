"""lacuna install-skills — copy skill documents to Hermes or Claude Code."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

# Skills live alongside this package at src/lacuna_wiki/skills//
SKILLS_DIR = Path(__file__).parent.parent / "skills"


def copy_skills(target: Path) -> list[Path]:
    """Copy all skill .md files from the package to target directory.

    Each skill gets its own subdirectory: target/lacuna-{name}/SKILL.md
    This matches the Claude Code skill discovery convention.
    Creates target if it doesn't exist. Overwrites existing files.
    Returns list of destination paths.
    """
    copied: list[Path] = []
    for skill_file in sorted(SKILLS_DIR.glob("*.md")):
        skill_name = skill_file.stem  # e.g. "ingest", "adversary"
        dest_dir = target / f"lacuna-{skill_name}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "SKILL.md"
        shutil.copy2(skill_file, dest)
        copied.append(dest)
    return copied


@click.command("install-skills")
@click.option(
    "--hermes",
    "hermes_path",
    default=None,
    metavar="PATH",
    help="Copy to this Hermes skills directory.",
)
@click.option(
    "--hermes-global",
    "hermes_global",
    is_flag=True,
    default=False,
    help="Copy to ~/.hermes/skills/ (Hermes global skills).",
)
@click.option(
    "--openclaw-global",
    "openclaw_global",
    is_flag=True,
    default=False,
    help="Copy to ~/.openclaw/skills/ (OpenClaw global skills).",
)
@click.option(
    "--claude-global",
    "claude_global",
    is_flag=True,
    default=False,
    help="Copy to ~/.claude/skills/ (Claude Code global skills).",
)
@click.option(
    "--claude-project",
    "claude_project",
    default=None,
    metavar="PATH",
    help="Copy to .claude/skills/ inside this directory (default: current dir).",
)
def install_skills(
    hermes_path: str | None,
    hermes_global: bool,
    openclaw_global: bool,
    claude_global: bool,
    claude_project: str | None,
) -> None:
    """Copy lacuna skill documents to Hermes, OpenClaw, or Claude Code skill directories."""
    targets: list[Path] = []

    if hermes_global:
        targets.append(Path.home() / ".hermes" / "skills")

    if openclaw_global:
        targets.append(Path.home() / ".openclaw" / "skills")

    if hermes_path:
        targets.append(Path(hermes_path))

    if claude_global:
        targets.append(Path.home() / ".claude" / "skills")

    if claude_project is not None:
        base = Path(claude_project) if claude_project else Path.cwd()
        targets.append(base / ".claude" / "skills")

    if not targets:
        click.echo(
            "Specify a target: --claude-global, --hermes PATH, or --claude-project [PATH]",
            err=True,
        )
        sys.exit(1)

    for target in targets:
        copied = copy_skills(target)
        click.echo(f"Installed {len(copied)} skill(s) → {target}")
        for f in copied:
            click.echo(f"  {f.name}")
