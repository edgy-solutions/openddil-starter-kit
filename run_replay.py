"""Replay a unit over one edge's recorded input and write a JSON report.

usage: run_replay.py [--measure] <unit-dir> <data/edge-xx> <out.json>

--measure reports the unit's memory and per-sample time instead of its outputs.

Exit 0 means the unit loaded and read records. It says nothing about whether
the unit's answers are any good; read the report.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "harness"))

from algorithm_runtime import replay  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    measure = args[:1] == ["--measure"]
    args = args[measure:]
    if len(args) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    unit_dir, edge_dir, out = (Path(a) for a in args)
    if not edge_dir.is_dir():
        print(f"error: {edge_dir} is not a directory", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    return replay.main([
        "--unit-dir", str(unit_dir),
        "--edge-id", edge_dir.name,
        "--region-id", "kit-region",
        "--raw", str(edge_dir / "raw-sensor-stream.*.gz"),
        "--out", str(out),
        *(["--measure"] if measure else []),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
