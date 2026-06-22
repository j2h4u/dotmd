import json
from pathlib import Path

import devtools.pyright_ratchet as pyright_ratchet
import pytest


def test_tighten_updates_baseline_monotonically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_path = tmp_path / "pyright-baseline.json"
    monkeypatch.setattr(pyright_ratchet, "BASELINE", baseline_path)
    monkeypatch.setattr(pyright_ratchet, "run_pyright", lambda: {"src/a.py": 3, "src/b.py": 1})

    assert pyright_ratchet.main(["--tighten"]) == 0
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {
        "src/a.py": 3,
        "src/b.py": 1,
    }

    monkeypatch.setattr(pyright_ratchet, "run_pyright", lambda: {"src/a.py": 2})

    assert pyright_ratchet.main(["--update"]) == 0
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {
        "src/a.py": 2,
    }


def test_tighten_refuses_to_raise_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_path = tmp_path / "pyright-baseline.json"
    baseline_path.write_text(json.dumps({"src/a.py": 1}, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(pyright_ratchet, "BASELINE", baseline_path)
    monkeypatch.setattr(pyright_ratchet, "run_pyright", lambda: {"src/a.py": 2})

    assert pyright_ratchet.main(["--update"]) == 1
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {"src/a.py": 1}

    captured = capsys.readouterr()
    assert "REGRESSIONS:" in captured.err
