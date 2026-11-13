"""Tests for tools/scan-recording.sh over a tiny planted recording."""
import base64
import gzip
import os
import subprocess
import sys
import tarfile

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.dirname(TOOLS)
SH = os.path.join(TOOLS, "scan-recording.sh").replace("\\", "/")


def _bash():
    # On Windows a bare "bash" can be the WSL launcher; prefer Git Bash.
    for c in (os.environ.get("BASH_EXE"), "C:/Program Files/Git/bin/bash.exe"):
        if c and os.path.isfile(c):
            return c
    return "bash"


BASH = _bash()
sys.path.insert(0, os.path.join(KIT, "harness"))
from openddil.telemetry.v1 import telemetry_pb2  # noqa: E402

TERM = "zq-planted-term"


def b64(b):
    return base64.b64encode(b).decode()


def event(asset_id="A-100", callsign="", event_id="e1", rev=0):
    m = telemetry_pb2.EntityTelemetryEvent()
    m.event_id = event_id
    m.asset.asset_id = asset_id
    if callsign:
        m.asset.callsign = callsign
    m.schema_revision = rev
    return m


def write_gz(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", newline="\n") as f:
        for ln in lines:
            f.write(ln + "\n")


def rec(off, key, val):
    return "%d 1700000000000 %s %s" % (off, b64(key), b64(val))


def build(tmp_path, proto=(), json_vals=(), extra_lines=()):
    root = tmp_path / "data" / "edge-01"
    pl = [rec(i, b"k%d" % i, m.SerializeToString()) for i, m in enumerate(proto)]
    write_gz(str(root / "raw-sensor-stream.0-9.gz"), pl)
    jl = [rec(i, b"j%d" % i, v.encode()) for i, v in enumerate(json_vals)]
    jl += list(extra_lines)
    write_gz(str(root / "prognostics-changelog.0-9.gz"), jl)
    return tmp_path / "data"


def run(args, tmp_path, **kw):
    env = dict(os.environ, PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([BASH, SH] + [str(a).replace("\\", "/") for a in args], capture_output=True,
                          text=True, env=env, cwd=str(tmp_path), **kw)


def terms_file(tmp_path, lines, name="terms.txt"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def test_clean(tmp_path):
    d = build(tmp_path, [event()], ['{"a": "b"}'])
    t = terms_file(tmp_path, [])
    r = run(["--terms", t, d], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.rstrip().endswith("verdict: PASS")


def test_term_in_field(tmp_path):
    d = build(tmp_path, [event(asset_id="X-" + TERM)], [])
    t = terms_file(tmp_path, [TERM])
    r = run(["--terms", t, d], tmp_path)
    assert r.returncode == 1
    assert "asset.asset_id" in r.stdout
    assert "in a field 1" in r.stdout
    assert TERM not in r.stdout + r.stderr


def test_term_raw_only(tmp_path):
    # field 15 (schema_revision) is tag 0x78 = "x" then varint 0x41 = 'A': "xA" spans no leaf.
    m = event(asset_id="Q", event_id="zz", rev=65)
    wire = m.SerializeToString()
    assert b"xA" in wire
    d = build(tmp_path, [m], [])
    t = terms_file(tmp_path, ["xA"])
    r = run(["--terms", t, d], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "raw only 1" in r.stdout and "in a field 0" in r.stdout
    assert "match length 2-2" in r.stdout
    assert "verdict: PASS (raw-byte-only hits, noise: 1)" in r.stdout


def test_raw_only_hit_with_a_decode_failure_fails(tmp_path):
    # A record that doesn't decode is where a raw hit could be real, so the scan fails.
    m = event(asset_id="Q", event_id="zz", rev=65)
    d = build(tmp_path, [m], [], extra_lines=[rec(9, b"k9", b"\xffxA\xff")])  # not JSON: fails to decode
    t = terms_file(tmp_path, ["xA"])
    r = run(["--terms", t, d], tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "decode_failures 1" in r.stdout and "verdict: FAIL (decode_failures)" in r.stdout


def test_callsign(tmp_path):
    d = build(tmp_path, [event(callsign="Viper 1")], [])
    r = run(["--terms", terms_file(tmp_path, []), d], tmp_path)
    assert r.returncode == 1
    assert "non-empty asset.callsign 1" in r.stdout
    assert "Viper" not in r.stdout


def test_person_subject(tmp_path):
    d = build(tmp_path, [], ['{"reported_by": "Jane Doe"}'])
    r = run([d], tmp_path)
    assert r.returncode == 1
    assert "reported_by/person-name" in r.stdout
    assert "Jane" not in r.stdout + r.stderr


def test_service_subject_ok(tmp_path):
    d = build(tmp_path, [], ['{"reported_by": "svc:cm-bridge"}'])
    r = run([d], tmp_path)
    assert r.returncode == 0, r.stdout
    assert "reported_by/service" in r.stdout


def test_email(tmp_path):
    d = build(tmp_path, [], ['{"note": "write to jdoe@example.org"}'])
    r = run([d], tmp_path)
    assert r.returncode == 1
    assert "email: records 1, in a field 1" in r.stdout
    assert "example.org" not in r.stdout + r.stderr
    assert "note" not in r.stdout.replace("callsign", "")  # JSON key names are data, masked


def test_pattern_file(tmp_path):
    d = build(tmp_path, [], ['{"x": "ID-4821"}'])
    p = terms_file(tmp_path, ["ID-[0-9]{4}"], "pats.txt")
    r = run(["--patterns", p, d], tmp_path)
    assert r.returncode == 1
    assert "pattern " in r.stdout and "#1: records 1, in a field 1" in r.stdout
    assert "4821" not in r.stdout


def test_tar_and_work_dir(tmp_path):
    d = build(tmp_path, [event()], ['{"a": "b"}'])
    tar = tmp_path / "rec.tar"
    with tarfile.open(tar, "w") as tf:
        tf.add(d, arcname="data")
    t = terms_file(tmp_path, [])
    work = tmp_path / "w1"
    r = run(["--terms", t, "--work", work, tar], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not work.exists()
    work2 = tmp_path / "w2"
    r2 = run(["--terms", t, "--work", work2, "--keep", tar], tmp_path)
    assert r2.returncode == 0
    assert (work2 / "dump.txt").is_file()
    assert r.stdout == r2.stdout
    # a non-empty work dir is refused
    r3 = run(["--terms", t, "--work", work2, tar], tmp_path)
    assert r3.returncode == 1


def test_bad_line(tmp_path):
    d = build(tmp_path, [event()], ['{"a": "b"}'], extra_lines=["5 1700000000000 abc"])
    r = run([d], tmp_path)
    assert r.returncode == 1
    assert "bad_lines 1" in r.stdout


def test_decode_failure(tmp_path):
    d = build(tmp_path, [], ["not json"])
    r = run([d], tmp_path)
    assert r.returncode == 1
    assert "decode_failures 1" in r.stdout


def test_usage_error(tmp_path):
    assert run([], tmp_path).returncode == 1
    assert run(["--bogus", tmp_path], tmp_path).returncode == 1


def test_term_numbering_by_physical_line(tmp_path):
    d = build(tmp_path, [event(asset_id="X-" + TERM)], [])
    t = terms_file(tmp_path, ["# comment", "", "nothere-1", "   ", "\r", TERM + "\r"])
    r = run(["--terms", t, d], tmp_path)
    assert r.returncode == 1
    assert "#3: records 0" in r.stdout
    assert "#6: records 1, in a field 1" in r.stdout
    assert TERM not in r.stdout
