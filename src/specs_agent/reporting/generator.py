"""Report generation — HTML (and optional PDF) from test results."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from specs_agent.models.results import Report
from specs_agent.reporting.formatters import (
    format_duration,
    format_latency,
    method_color,
    status_badge,
    status_color,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
# Fallback for dev layouts where the template still lives under repo_root/assets/.
_LEGACY_TEMPLATE_DIR = Path(__file__).parent.parent.parent.parent / "assets"


def generate_html_report(report: Report, output_path: str) -> str:
    """Render a Report to an HTML file.

    Args:
        report: The test report data.
        output_path: File path to write the HTML to.

    Returns:
        The output file path.
    """
    search_paths = [str(TEMPLATE_DIR)]
    if _LEGACY_TEMPLATE_DIR.is_dir():
        search_paths.append(str(_LEGACY_TEMPLATE_DIR))
    env = Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=False,
    )
    template = env.get_template("report_template.html")
    html = template.render(
        report=report,
        generated_at=datetime.now(timezone.utc).isoformat(),
        format_duration=format_duration,
        format_latency=format_latency,
        status_badge=status_badge,
        status_color=status_color,
        method_color=method_color,
    )
    out = Path(output_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return str(out)


def generate_pdf_report(report: Report, output_path: str) -> str:
    """Render a Report to PDF via weasyprint (optional dependency).

    Args:
        report: The test report data.
        output_path: File path to write the PDF to.

    Returns:
        The output file path.

    Raises:
        ImportError: If weasyprint is not installed.
    """
    html_path = output_path.replace(".pdf", ".html")
    generate_html_report(report, html_path)

    try:
        from weasyprint import HTML
    except ImportError:
        raise ImportError(
            "weasyprint is required for PDF reports. "
            "Install it with: pip install 'specs-agent[pdf]'"
        )

    HTML(filename=html_path).write_pdf(output_path)
    # Clean up intermediate HTML
    Path(html_path).unlink(missing_ok=True)
    return output_path
