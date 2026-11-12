from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence

from .equivalence import Comparison, weak_bisimilar, weak_trace_equivalent
from .lts import LTS, format_aut, normalize_time
from .statespace import read_observables, read_statespace

EQUIVALENCES = ("weak-bisim", "weak-trace")


def compare_mcrl2(
    left: LTS, right: LTS, equivalence: str,
    executable: str = "ltscompare", timeout: float = 300,
) -> Comparison:
    program = shutil.which(executable)
    if program is None and executable == "ltscompare" and os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "mCRL2/bin/ltscompare.exe"
        if candidate.is_file():
            program = str(candidate)
    if program is None:
        raise ValueError(f"mCRL2 executable not found: {executable}; install ltscompare or omit --mcrl2")
    with tempfile.TemporaryDirectory(prefix="semanticchecker-") as directory:
        paths = [Path(directory) / "left.aut", Path(directory) / "right.aut"]
        for path, lts in zip(paths, (left, right)):
            path.write_text(format_aut(lts), encoding="utf-8")
        try:
            result = subprocess.run(
                [program, f"--equivalence={equivalence}", *(str(p) for p in paths)],
                capture_output=True, text=True, check=False, timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError(f"ltscompare timed out after {timeout:g} seconds") from error
        if result.returncode != 0:
            raise ValueError(f"ltscompare failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
        verdict = result.stdout.strip().lower()
        if verdict not in {"true", "false"}:
            raise ValueError(f"Unexpected ltscompare output: {result.stdout.strip()!r}")
        return Comparison(verdict == "true")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two Afra .statespace files modulo discrete weak timed equivalence.")
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("observable_messages", type=Path, nargs="?", help="comma/newline-separated owner.message selectors; default: all messages")
    parser.add_argument("-e", "--equivalence", choices=EQUIVALENCES, default="weak-bisim")
    parser.add_argument("--mcrl2", action="store_true", help="use mCRL2 ltscompare after the same time normalization")
    parser.add_argument("--ltscompare", default="ltscompare", help="ltscompare name or executable path")
    parser.add_argument("--timeout", type=_positive_float, default=300, help="mCRL2 timeout in seconds (default: 300)")
    parser.add_argument("--include-arguments", action="store_true", help="observe queued message arguments as well as message names")
    parser.add_argument("--initial-left", help="initial state XML ID in the first file")
    parser.add_argument("--initial-right", help="initial state XML ID in the second file")
    parser.add_argument("--max-states", type=_positive_int, default=1_000_000, help="maximum normalized states per input")
    parser.add_argument("--max-pairs", type=_positive_int, default=100_000, help="maximum subset pairs in Python weak-trace checking")
    parser.add_argument("--json", action="store_true", help="print structured result, including a distinguishing trace when available")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        observable = read_observables(arguments.observable_messages) if arguments.observable_messages else None
        spaces = [
            read_statespace(path, observable, include_arguments=arguments.include_arguments, initial_state=initial)
            for path, initial in ((arguments.left, arguments.initial_left), (arguments.right, arguments.initial_right))
        ]
        left, right = [normalize_time(lts, arguments.max_states) for lts in spaces]
        if arguments.mcrl2:
            result = compare_mcrl2(left, right, arguments.equivalence, arguments.ltscompare, arguments.timeout)
        elif arguments.equivalence == "weak-bisim":
            result = weak_bisimilar(left, right)
        else:
            result = weak_trace_equivalent(left, right, arguments.max_pairs)
        if arguments.json:
            print(json.dumps({
                "equivalent": result.equivalent,
                "equivalence": arguments.equivalence,
                "backend": "mcrl2" if arguments.mcrl2 else "python",
                "inputs": [{"path": str(path), "states": raw.num_states, "normalized_states": normalized.num_states,
                            "normalized_transitions": len(normalized.transitions)}
                           for path, raw, normalized in zip((arguments.left, arguments.right), spaces, (left, right))],
                "explored_pairs": result.explored_pairs,
                "counterexample": result.counterexample,
            }, indent=2))
        else:
            print("YES" if result.equivalent else "NO")
        return 0 if result.equivalent else 1
    except (OSError, ValueError, MemoryError) as error:
        print(f"Error: {error or 'insufficient memory'}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
