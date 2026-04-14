import importlib.metadata

import click

_version = importlib.metadata.version("lacuna-wiki")


@click.group()
@click.version_option(_version, "--version", "-V", prog_name="lacuna")
def cli():
    """lacuna — personal research knowledge substrate."""
    pass


from lacuna_wiki.cli.add_source import add_source  # noqa: E402
from lacuna_wiki.cli.init import init               # noqa: E402
from lacuna_wiki.cli.status import status           # noqa: E402
from lacuna_wiki.cli.daemon import start, stop, daemon_run  # noqa: E402
from lacuna_wiki.cli.mcp_cmd import mcp_command     # noqa: E402
from lacuna_wiki.cli.claims import claims_command              # noqa: E402
from lacuna_wiki.cli.adversary_commit import adversary_commit  # noqa: E402
from lacuna_wiki.cli.install_skills import install_skills      # noqa: E402
from lacuna_wiki.cli.move_source import move_source            # noqa: E402
from lacuna_wiki.cli.sync import sync                          # noqa: E402

cli.add_command(add_source)
cli.add_command(init)
cli.add_command(status)
cli.add_command(start)
cli.add_command(stop)
cli.add_command(daemon_run)
cli.add_command(mcp_command)
cli.add_command(claims_command)
cli.add_command(adversary_commit)
cli.add_command(install_skills)
cli.add_command(move_source)
cli.add_command(sync)
