"""Pyright ratchet — fail when any file has more errors than the baseline.

The dev-gate (start.sh, ENVIRONMENT=dev) runs pyright on every container
start and uses this script to gate the server: if any tracked file has
*new* type errors compared to ``pyright-baseline.json``, the gate fails
and the server does not boot.

This is the "ratchet" pattern: the checked-in baseline is acceptable, but no
file is allowed to *increase* its error count. Errors fixed locally cause the
baseline to tighten only when the operator re-runs ``--update`` from the host.

Usage:
    python devtools/pyright_ratchet.py             # check only, exit 1 on regression
    python devtools/pyright_ratchet.py --tighten   # lower baseline only, exit 1 on regression
    python devtools/pyright_ratchet.py --update    # alias for --tighten

Files with fewer errors than baseline are treated as silent improvements
in check mode. Tighten mode records lower counts and refuses to raise any
per-file baseline, so the checked-in floor only moves in one direction.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "pyright-baseline.json"
SCAN_PATHS = ("src/", "tests/", "devtools/")


def run_pyright() -> dict[str, int]:
    """Run pyright in JSON mode, return {relative_file: error_count}."""
    proc = subprocess.run(
        ["pyright", "--outputjson", *SCAN_PATHS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if not proc.stdout:
        sys.stderr.write(
            f"pyright produced no JSON output (exit {proc.returncode}).\nstderr:\n{proc.stderr}\n"
        )
        sys.exit(2)

    # On first run, pyright's nodeenv prints platform-detection noise like
    # ``{'x86': False, 'risc': False, 'lts': False}`` to stdout BEFORE the
    # real JSON document.  Skip the preamble by anchoring on the proper
    # JSON ``"version"`` key that pyright always emits first.
    raw = proc.stdout
    m = re.search(r'^\{\s*\n\s*"version"', raw, re.MULTILINE)
    if m:
        raw = raw[m.start() :]

    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"failed to parse pyright JSON: {exc}\n"
            f"first 500 chars of stdout:\n{proc.stdout[:500]}\n"
        )
        sys.exit(2)

    counts: dict[str, int] = {}
    for diag in data.get("generalDiagnostics", []):
        if diag.get("severity") != "error":
            continue
        f = diag["file"]
        with contextlib.suppress(ValueError):
            f = str(Path(f).relative_to(ROOT))
        counts[f] = counts.get(f, 0) + 1
    return counts


def load_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text())


def write_baseline(counts: dict[str, int]) -> None:
    BASELINE.write_text(
        json.dumps(dict(sorted(counts.items())), indent=2) + "\n",
        encoding="utf-8",
    )


def regressions_against_baseline(
    current: dict[str, int],
    baseline: dict[str, int],
) -> list[tuple[str, int, int]]:
    regressions: list[tuple[str, int, int]] = []
    for f, n in sorted(current.items()):
        b = baseline.get(f, 0)
        if n > b:
            regressions.append((f, n, b))
    return regressions


def improvements_against_baseline(
    current: dict[str, int],
    baseline: dict[str, int],
) -> list[tuple[str, int, int]]:
    improvements: list[tuple[str, int, int]] = []
    for f, b in baseline.items():
        n = current.get(f, 0)
        if n < b:
            improvements.append((f, b, n))
    return improvements


def write_tightened_baseline(current: dict[str, int]) -> None:
    tightened = {path: count for path, count in current.items() if count > 0}
    write_baseline(tightened)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pyright ratchet.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--update",
        action="store_true",
        help="Alias for --tighten; kept for existing operator muscle memory.",
    )
    modes.add_argument(
        "--tighten",
        action="store_true",
        help="Rewrite the baseline only when doing so lowers or preserves every per-file count.",
    )
    args = parser.parse_args(argv)

    current = run_pyright()
    total = sum(current.values())

    if (args.update or args.tighten) and not BASELINE.exists():
        write_baseline(current)
        print(
            f"baseline updated: {total} errors across {len(current)} files",
            file=sys.stderr,
        )
        return 0

    if not BASELINE.exists():
        sys.stderr.write(
            f"No baseline at {BASELINE} — run with --update from the host first.\n"
            f"Current count would be locked in: {total} errors across {len(current)} files.\n"
        )
        return 2

    baseline = load_baseline()
    regressions = regressions_against_baseline(current, baseline)
    improvements = improvements_against_baseline(current, baseline)

    baseline_total = sum(baseline.values())
    print(
        f"pyright ratchet: {total} errors (baseline {baseline_total})",
        file=sys.stderr,
    )

    if improvements:
        delta = sum(was - now for _, was, now in improvements)
        print(
            f"  improvements: -{delta} across {len(improvements)} files "
            "(run with --update to lock the new floor)",
            file=sys.stderr,
        )

    if regressions:
        if args.update or args.tighten:
            print("  refused to raise baseline", file=sys.stderr)
        print("  REGRESSIONS:", file=sys.stderr)
        for f, now, was in regressions:
            print(f"    {f}: {now} (was {was}, +{now - was})", file=sys.stderr)
        return 1

    if args.update or args.tighten:
        write_tightened_baseline(current)
        print(
            f"baseline tightened: {total} errors across {len(current)} files",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
