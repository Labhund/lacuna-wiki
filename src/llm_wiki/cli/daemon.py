import click

@click.command()
def start() -> None:
    """Start the file-watcher daemon."""
    pass

@click.command()
def stop() -> None:
    """Stop the file-watcher daemon."""
    pass
