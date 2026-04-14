"""Test config modal -- configure base URL, auth, performance settings."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from specs_agent.models.config import PerformanceConfig, RampStage, TestRunConfig


class TestConfigModal(ModalScreen[TestRunConfig | None]):
    """Overlay for configuring test run settings."""

    DEFAULT_CSS = """
    TestConfigModal {
        align: center middle;
        background: transparent;
    }
    #config-frame {
        width: 90%;
        height: 95%;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 1 2;
    }
    #config-title {
        dock: top;
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
    }
    #config-scroll {
        height: 1fr;
        margin: 1 0;
    }
    .form-section {
        margin-top: 1;
        color: #cc9944;
        text-style: bold;
    }
    .form-label {
        color: #7a7a9a;
        margin-top: 1;
    }
    Checkbox {
        background: transparent;
        padding: 0;
        margin: 0;
        color: #c0c0d0;
    }
    Checkbox:focus {
        background: transparent;
    }
    Select {
        background: transparent;
        border: tall #333355;
        color: #c0c0d0;
    }
    Select:focus {
        border: tall #55cc55;
    }
    SelectOverlay {
        background: #222240;
        color: #c0c0d0;
        border: tall #333355;
    }
    SelectCurrent {
        background: transparent;
        color: #55cc55;
    }
    #config-footer {
        dock: bottom;
        height: 3;
        align-horizontal: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save & Run"),
    ]

    def __init__(self, config: TestRunConfig, base_url: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.run_config = config
        self._default_base_url = base_url

    def compose(self) -> ComposeResult:
        with Vertical(id="config-frame"):
            yield Static("TEST CONFIGURATION", id="config-title")
            with VerticalScroll(id="config-scroll"):
                # Connection
                yield Label("Connection", classes="form-section")
                yield Label("Base URL", classes="form-label")
                yield Input(
                    value=self.run_config.base_url or self._default_base_url,
                    placeholder="https://api.example.com/v1",
                    id="base-url-input",
                )
                yield Label("Timeout (seconds)", classes="form-label")
                yield Input(
                    value=str(self.run_config.timeout_seconds),
                    id="timeout-input",
                )
                yield Checkbox(
                    "Follow redirects",
                    value=self.run_config.follow_redirects,
                    id="redirects-check",
                )
                yield Checkbox(
                    "Verify SSL",
                    value=self.run_config.verify_ssl,
                    id="ssl-check",
                )

                # Auth
                yield Label("Authentication", classes="form-section")
                yield Label("Auth type", classes="form-label")
                yield Select(
                    [(t, t) for t in ["none", "bearer", "api_key", "basic"]],
                    value=self.run_config.auth_type,
                    id="auth-type-select",
                )
                yield Label("Token / Key / user:pass", classes="form-label")
                yield Input(
                    value=self.run_config.auth_value,
                    placeholder="Token or API key",
                    password=self.run_config.auth_type == "bearer",
                    id="auth-value-input",
                )

                # Performance
                yield Label("Performance Testing", classes="form-section")
                yield Checkbox(
                    "Enable performance tests",
                    value=self.run_config.performance.enabled,
                    id="perf-enabled-check",
                )
                yield Label("Concurrent users", classes="form-label")
                yield Input(
                    value=str(self.run_config.performance.concurrent_users),
                    id="perf-users-input",
                )
                yield Label("Duration (seconds)", classes="form-label")
                yield Input(
                    value=str(self.run_config.performance.duration_seconds),
                    id="perf-duration-input",
                )
                yield Label("Ramp-up seconds (0 = instant)", classes="form-label")
                yield Input(
                    value=str(self.run_config.performance.ramp_up_seconds),
                    id="perf-rampup-input",
                )
                yield Label("Target TPS (0 = unlimited)", classes="form-label")
                yield Input(
                    value=str(self.run_config.performance.target_tps),
                    placeholder="0",
                    id="perf-tps-input",
                )
                yield Label("Stages (users:seconds, ... — overrides above if set)", classes="form-label")
                yield Input(
                    value=_stages_to_str(self.run_config.performance.stages),
                    placeholder="e.g. 5:10, 20:30, 50:60",
                    id="perf-stages-input",
                )

            with Horizontal(id="config-footer"):
                yield Button("\\[esc] CANCEL", variant="default", id="cancel-btn")
                yield Button("\\[ctrl+s] SAVE & RUN", variant="success", id="save-btn")

    def on_key(self, event) -> None:
        """Cmd+Enter to submit from anywhere."""
        pass  # ctrl+s binding handles submission

    def action_save(self) -> None:
        self.dismiss(self._build_config())

    def _build_config(self) -> TestRunConfig:
        def _float(input_id: str, default: float) -> float:
            try:
                return float(self.query_one(f"#{input_id}", Input).value)
            except (ValueError, Exception):
                return default

        def _int(input_id: str, default: int) -> int:
            try:
                return int(self.query_one(f"#{input_id}", Input).value)
            except (ValueError, Exception):
                return default

        auth_select = self.query_one("#auth-type-select", Select)
        auth_type = str(auth_select.value) if auth_select.value != Select.BLANK else "none"

        return TestRunConfig(
            base_url=self.query_one("#base-url-input", Input).value.strip(),
            timeout_seconds=_float("timeout-input", 30.0),
            follow_redirects=self.query_one("#redirects-check", Checkbox).value,
            verify_ssl=self.query_one("#ssl-check", Checkbox).value,
            auth_type=auth_type,
            auth_value=self.query_one("#auth-value-input", Input).value.strip(),
            performance=PerformanceConfig(
                enabled=self.query_one("#perf-enabled-check", Checkbox).value,
                concurrent_users=_int("perf-users-input", 10),
                duration_seconds=_int("perf-duration-input", 30),
                ramp_up_seconds=_int("perf-rampup-input", 0),
                target_tps=_float("perf-tps-input", 0.0),
                stages=_parse_stages(self.query_one("#perf-stages-input", Input).value),
            ),
        )

    @on(Button.Pressed, "#save-btn")
    def on_save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_btn(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _parse_stages(text: str) -> list[RampStage]:
    """Parse stages from 'users:seconds, users:seconds, ...' format."""
    text = text.strip()
    if not text:
        return []
    stages = []
    for part in text.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        try:
            users_s, dur_s = part.split(":", 1)
            stages.append(RampStage(users=int(users_s.strip()), duration_seconds=int(dur_s.strip())))
        except (ValueError, TypeError):
            continue
    return stages


def _stages_to_str(stages: list[RampStage]) -> str:
    """Convert stages back to display string."""
    if not stages:
        return ""
    return ", ".join(f"{s.users}:{s.duration_seconds}" for s in stages)
