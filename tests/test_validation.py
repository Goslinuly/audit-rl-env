import json
import sys

import pytest

from auditgym.runner.demo import record_cast
from auditgym.runner.validate import execute


def test_validation_preserves_nonzero_exit_and_does_not_continue(tmp_path):
    out = tmp_path / "run"
    report = execute([
        ("first", [sys.executable, "-c", "raise SystemExit(7)"]),
        ("never", [sys.executable, "-c", "raise SystemExit(0)"]),
    ], tmp_path, out, 10)
    assert report["status"] == "failed"
    assert len(report["stages"]) == 1 and report["stages"][0]["exit_code"] == 7
    assert json.loads((out / "validation.json").read_text())["status"] == "failed"


def test_validation_deadline_is_reported(tmp_path):
    report = execute([("slow", [sys.executable, "-c", "import time; time.sleep(3)"])],
                     tmp_path, tmp_path / "timed", .1)
    assert report["status"] == "failed"
    assert report["stages"][0]["status"] == "timed_out"


def test_terminal_recording_is_asciinema_v2_with_reading_pauses(tmp_path, monkeypatch):
    import auditgym.runner.demo as demo
    now = [0.0]
    monkeypatch.setattr(demo.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(demo.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    path = tmp_path / "demo.cast"
    record_cast(path, ["actual measured run", "summary"], 135)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["version"] == 2
    assert rows[1][0] == 0 and rows[-1][0] == 135
    assert rows[-1][1:] == ["o", "summary\r\n"]


@pytest.mark.parametrize("deadline", [0, float("nan"), float("inf")])
def test_invalid_validation_deadline_does_not_create_output(tmp_path, deadline):
    with pytest.raises(ValueError):
        execute([], tmp_path, tmp_path / "output", deadline)
    assert not (tmp_path / "output").exists()
