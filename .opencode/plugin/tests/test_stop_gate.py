"""The stop-gate plugin, exercised through its real module in a Node harness.

Run: uv run pytest .opencode/plugin/tests/test_stop_gate.py -q
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
HARNESS = ROOT / ".opencode" / "plugin" / "tests" / "helpers" / "stop_gate_harness.mjs"
TSX = ROOT / ".opencode" / "node_modules" / ".bin" / "tsx"
SPACED = Path("/tmp/project with spaces")


def run_harness(*args: str) -> tuple[dict[str, Any], str]:
    """Run one harness scenario and return its JSON report with the plugin's stderr."""
    assert TSX.is_file(), (
        "run npm install --prefix .opencode to install the harness runtime"
    )
    finished = subprocess.run(
        [str(TSX), str(HARNESS), *args],
        cwd=ROOT,
        env={**os.environ, "STOP_GATE_PYTHON": sys.executable},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout.strip().splitlines()[-1]), finished.stderr


@pytest.fixture
def spaced_project() -> Iterator[Path]:
    """The scenario's location, whose name carries spaces that must not be split."""
    shutil.rmtree(SPACED, ignore_errors=True)
    SPACED.mkdir(parents=True)
    yield SPACED
    shutil.rmtree(SPACED, ignore_errors=True)


@pytest.fixture
def two_projects() -> Iterator[tuple[Path, Path]]:
    """The plugin's location and another project's, as the scenario names them."""
    local, other = Path("/tmp/project-a"), Path("/tmp/project-b")
    for project in (local, other):
        shutil.rmtree(project, ignore_errors=True)
        project.mkdir(parents=True)
    yield local, other
    for project in (local, other):
        shutil.rmtree(project, ignore_errors=True)


def test_v2_loader_accepts_plugin_and_setup(tmp_path: Path) -> None:
    report, _ = run_harness("load", str(tmp_path))

    assert report["loadError"] is None
    assert report["defaultKind"] == "object"
    assert report["id"] == "stop-gate"
    assert report["setupIsFunction"] is True
    assert report["subscribeCalls"] == 1
    assert report["gateRuns"] == 0
    assert report["prompts"] == []


def test_local_idle_runs_gate_with_safe_arguments(spaced_project: Path) -> None:
    report, _ = run_harness("local-idle", str(spaced_project))

    assert report["sessionsAsked"] == ["ses_local"]
    assert report["gateRuns"] == 1

    entry = report["gate"][0]
    assert entry["argv"] == [
        f"{spaced_project}/.opencode/skills/sdd/scripts/sdd.py",
        "--root",
        str(spaced_project),
        "stop-gate",
    ]
    assert Path(entry["cwd"]).resolve() == spaced_project.resolve()
    assert entry["stdin"] == "closed"


def test_unrelated_event_is_ignored(spaced_project: Path) -> None:
    # The local idle is the control: it proves the plugin is consuming events, so a quiet
    # `config.updated` is an event that was seen and ignored rather than one nobody read.
    report, _ = run_harness("unrelated-event", str(spaced_project))

    assert report["gateRuns"] == 1
    assert report["sessionsAsked"] == ["ses_local"]
    assert report["prompts"] == []


def test_other_location_idle_is_ignored(two_projects: tuple[Path, Path]) -> None:
    local, other = two_projects

    report, _ = run_harness("other-location", str(local), str(other))

    assert report["sessionsAsked"] == ["ses_other"]
    assert report["gateRuns"] == 0
    assert report["prompts"] == []


def test_concurrent_idle_checks_are_coalesced(spaced_project: Path) -> None:
    report, _ = run_harness("concurrent-idle", str(spaced_project))

    assert report["gateRuns"] == 1


def test_failure_detail_is_delivered_once(spaced_project: Path) -> None:
    report, _ = run_harness("failure-twice", str(spaced_project))

    assert [prompt["sessionID"] for prompt in report["prompts"]] == ["ses_one"]
    assert report["prompts"][0]["text"] == "stop-gate: checks failed"


def test_success_resets_retry_guard(spaced_project: Path) -> None:
    report, _ = run_harness("failure-reset", str(spaced_project))

    assert [prompt["text"] for prompt in report["prompts"]] == [
        "stop-gate: checks failed",
        "stop-gate: checks failed",
    ]


def test_sessions_have_independent_retry_guards(spaced_project: Path) -> None:
    report, _ = run_harness("two-sessions", str(spaced_project))

    assert [prompt["sessionID"] for prompt in report["prompts"]] == [
        "ses_one",
        "ses_two",
    ]
    assert [prompt["text"] for prompt in report["prompts"]] == [
        "stop-gate: checks failed",
        "stop-gate: checks failed",
    ]


def test_unload_cancels_gate_and_stops_events(spaced_project: Path) -> None:
    report, _ = run_harness("unload", str(spaced_project))

    assert report["cancelled"] is True
    assert report["gateRuns"] == 1
    assert report["deliveredAfterCleanup"] == 0
    # The cancelled gate keeps running long enough to return an ordinary result after cleanup.
    assert report["exits"] == [{"code": 2}]
    assert report["prompts"] == []


def test_unexpected_exit_preserves_retry_guard(spaced_project: Path) -> None:
    report, _ = run_harness("unexpected-exit", str(spaced_project))

    reported = [line for line in report["diagnostics"] if "execution failed" in line]
    assert reported, report["diagnostics"]
    assert "1" in reported[0]
    assert [prompt["text"] for prompt in report["prompts"]] == [
        "stop-gate: checks failed"
    ]


def test_launch_error_is_reported_and_next_idle_recovers(spaced_project: Path) -> None:
    report, _ = run_harness("launch-error", str(spaced_project))

    reported = [line for line in report["diagnostics"] if "ENOENT" in line]
    assert reported, report["diagnostics"]
    assert [prompt["text"] for prompt in report["prompts"]] == [
        "stop-gate: checks failed"
    ]
