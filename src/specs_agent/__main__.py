"""Entry point for `python -m specs_agent`."""

import click

from specs_agent.app import SpecsAgentApp


@click.command()
@click.option("--spec", "-s", type=str, default=None, help="Path or URL to an OpenAPI spec file")
def main(spec: str | None) -> None:
    """Launch the specs-agent API Testing TUI."""
    app = SpecsAgentApp(spec_source=spec)
    app.run()


if __name__ == "__main__":
    main()
