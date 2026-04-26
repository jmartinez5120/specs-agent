"""Network utilities (Docker host rewriting, etc.)."""

from specs_agent.net.docker_hosts import (
    rewrite_for_display,
    rewrite_localhost_for_docker,
    running_in_docker,
)

__all__ = [
    "rewrite_for_display",
    "rewrite_localhost_for_docker",
    "running_in_docker",
]
