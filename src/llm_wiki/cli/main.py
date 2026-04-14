import click


@click.group()
def cli():
    """llm-wiki v2 — personal research knowledge substrate."""
    pass


from llm_wiki.cli.add_source import add_source  # noqa: E402
from llm_wiki.cli.init import init               # noqa: E402
from llm_wiki.cli.status import status           # noqa: E402
from llm_wiki.cli.daemon import start, stop      # noqa: E402

cli.add_command(add_source)
cli.add_command(init)
cli.add_command(status)
cli.add_command(start)
cli.add_command(stop)
