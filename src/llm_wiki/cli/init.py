import click

@click.command()
@click.argument("path", default=".", type=click.Path())
def init(path: str) -> None:
    """Initialise a new llm-wiki vault at PATH."""
    pass
