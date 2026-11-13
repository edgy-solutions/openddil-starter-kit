"""Helpers for tools/scan-recording.sh. Python stdlib + protobuf only.

Subcommands: dump, leaves, report. Nothing here prints a record key, a leaf value or a
matched string. Output is kinds and counts.
"""
import argparse
import base64
import binascii
import gzip
import json
import os
import re
import sys
from collections import Counter

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "harness"))

PROTO_TOPICS = {"raw-sensor-stream", "derived-sustainment"}
SUBJECT_KEYS = {"reported_by", "reportedby", "sub", "recordedby", "recorded_by",
                "filer", "filed_by", "subject"}
PERSON_RE = re.compile(r"^[A-Z][a-z]+[ ._][A-Z][a-z]+$")
SERVICE_RE = re.compile(r"^(svc|system|service)[:/]", re.I)
_MASK = bytes(c if 32 <= c <= 126 else 32 for c in range(256))
_PROTO = None


def proto():
    global _PROTO
    if _PROTO is None:
        from google.protobuf.json_format import MessageToDict
        from openddil.telemetry.v1 import telemetry_pb2
        names = set()
        seen = set()

        def collect(d):
            if d.full_name in seen:
                return
            seen.add(d.full_name)
            for f in d.fields:
                names.add(f.name)
                if f.message_type is not None:
                    collect(f.message_type)

        collect(telemetry_pb2.EntityTelemetryEvent.DESCRIPTOR)
        _PROTO = (telemetry_pb2.EntityTelemetryEvent, MessageToDict, names)
    return _PROTO


def printable(b):
    return b.translate(_MASK).decode("ascii")


def mask_str(s):
    return "".join(c if 32 <= ord(c) <= 126 else " " for c in s)


def gz_files(inputs):
    for root in inputs:
        found = []
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.endswith(".gz"):
                    found.append(os.path.join(dp, f))
        yield from sorted(found)


def b64(col):
    if col == "":
        return b""
    return base64.b64decode(col, validate=True)


def records(inputs, stats=None):
    """Yield (topic, key_bytes, value_bytes) per well-formed line, in order."""
    for path in gz_files(inputs):
        topic = os.path.basename(path).split(".")[0]
        if stats is not None:
            stats["files"] += 1
        with gzip.open(path, "rb") as fh:
            for raw in fh:
                line = raw.rstrip(b"\r\n").decode("latin-1")
                cols = line.split(" ")
                if len(cols) != 4:
                    if stats is not None:
                        stats["bad_lines"] += 1
                    continue
                try:
                    key = b64(cols[2])
                    val = b64(cols[3])
                    ok = True
                except (binascii.Error, ValueError):
                    key = cols[2].encode("latin-1")
                    val = cols[3].encode("latin-1")
                    ok = False
                yield topic, key, val, ok


def decode(topic, val):
    """Return (obj, kind) with kind 'proto', 'json', 'empty' or 'fail'."""
    if val == b"":
        return None, "empty"
    try:
        if topic in PROTO_TOPICS:
            cls, to_dict, _ = proto()
            msg = cls()
            msg.ParseFromString(val)
            return msg, "proto"
        return json.loads(val.decode("utf-8")), "json"
    except Exception:
        return None, "fail"


def shape(v):
    if "@" in v:
        return "email"
    if PERSON_RE.match(v):
        return "person-name"
    if SERVICE_RE.match(v):
        return "service"
    return "other"


def walk(obj, path, mask, leaf, subj):
    """Visit a decoded structure. leaf(path, text); subj(key_lower, value)."""
    j = (lambda p, c: p + "." + c if p else c)
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            leaf(j(path, "(key)"), ks)
            if ks.lower() in SUBJECT_KEYS:
                subj(ks.lower(), v)
            walk(v, j(path, mask(ks)), mask, leaf, subj)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, j(path, "[]"), mask, leaf, subj)
    else:
        leaf(path, str(obj))


def iter_decoded(inputs, stats=None):
    """Yield (n, topic, key, val, obj_dict_or_None, msg) for every record."""
    n = 0
    for topic, key, val, ok in records(inputs, stats):
        n += 1
        obj, kind = decode(topic, val)
        msg = None
        if kind == "proto":
            msg = obj
            obj = proto()[1](msg, preserving_proto_field_name=True)
        yield n, topic, key, val, obj, msg, kind, ok


def cmd_dump(a):
    stats = Counter()
    per_topic = Counter()
    subj_vals = Counter()
    subj_keys = 0
    callsigns = 0
    with open(os.path.join(a.work, "dump.txt"), "w", newline="\n") as out:
        for n, topic, key, val, obj, msg, kind, ok in iter_decoded(a.inputs, stats):
            stats["records"] += 1
            per_topic[topic] += 1
            if kind == "empty":
                stats["empty_values"] += 1
            if kind == "fail" or not ok:
                stats["decode_failures"] += 1
            out.write(topic + " " + printable(key + b" " + val) + "\n")
            if msg is not None and msg.asset.callsign:
                callsigns += 1
            if obj is not None:
                def leaf(p, t):
                    pass

                def subj(k, v):
                    nonlocal subj_keys
                    subj_keys += 1
                    if isinstance(v, str) and v != "":
                        subj_vals[k + "/" + shape(v)] += 1

                walk(obj, "", lambda s: s, leaf, subj)
    res = {"files": stats["files"], "records": stats["records"],
           "bad_lines": stats["bad_lines"], "empty_values": stats["empty_values"],
           "decode_failures": stats["decode_failures"], "callsigns": callsigns,
           "per_topic": dict(per_topic), "subject_keys": subj_keys,
           "subject_vals": dict(subj_vals)}
    with open(os.path.join(a.work, "stats.json"), "w") as f:
        json.dump(res, f)


def cmd_leaves(a):
    names = proto()[2]

    def mask(c):
        return c if c in names else "*"

    want = set()
    with open(os.path.join(a.work, "hits-union.txt")) as f:
        for line in f:
            line = line.strip()
            if line:
                want.add(int(line))
    vals = open(os.path.join(a.work, "leaves-values.txt"), "w", newline="\n")
    meta = open(os.path.join(a.work, "leaves-meta.tsv"), "w", newline="\n")
    try:
        for n, topic, key, val, obj, msg, kind, ok in iter_decoded(a.inputs):
            if n not in want:
                continue

            def leaf(p, t):
                vals.write(mask_str(t) + "\n")
                meta.write("%d\t%s\t%s\n" % (n, topic, p))

            leaf("(record key)", key.decode("latin-1"))
            if obj is not None:
                walk(obj, "", mask, leaf, lambda k, v: None)
    finally:
        vals.close()
        meta.close()


def cmd_report(a):
    st = json.load(open(os.path.join(a.work, "stats.json")))
    out = []
    pt = ", ".join("%s %d" % (k, v) for k, v in sorted(st["per_topic"].items()))
    out.append("records %d in %d files (%s)" % (st["records"], st["files"], pt))
    out.append("bad_lines %d  empty_values %d  decode_failures %d"
               % (st["bad_lines"], st["empty_values"], st["decode_failures"]))
    out.append("callsign: records with a non-empty asset.callsign %d" % st["callsigns"])
    out.append("subjects: keys present %d, values by key/shape %s"
               % (st["subject_keys"], json.dumps(st["subject_vals"], sort_keys=True)))
    infield = raw = 0
    with open(os.path.join(a.work, "results.tsv")) as f:
        for line in f:
            kind, file, num, nrec, inf, rw, rng = line.rstrip("\n").split("\t")
            inf, rw = int(inf), int(rw)
            infield += inf
            raw += rw
            label = "email:" if kind == "email" else "%s %s #%s:" % (kind, file, num)
            if int(nrec) == 0:
                out.append("%s records 0" % label)
                continue
            s = "%s records %s, in a field %d, raw only %d" % (label, nrec, inf, rw)
            if rw:
                s += " (match length %s)" % rng
            out.append(s)
    paths = Counter()
    seen = set()
    with open(os.path.join(a.work, "fieldhits.tsv")) as f:
        for line in f:
            i, rec, p = line.rstrip("\n").split("\t")
            if (i, rec, p) not in seen:
                seen.add((i, rec, p))
                paths[p] += 1
    if paths:
        out.append("in a field by path: " + "; ".join(
            "%s %d" % (p, c) for p, c in sorted(paths.items())))
    reasons = []
    if infield:
        reasons.append("in-field hits")
    if st["callsigns"]:
        reasons.append("callsign")
    if any(not k.endswith("/service") for k in st["subject_vals"]):
        reasons.append("subject values")
    if st["bad_lines"]:
        reasons.append("bad_lines")
    if st["decode_failures"]:
        reasons.append("decode_failures")
    if reasons:
        out.append("verdict: FAIL (%s)" % ", ".join(reasons))
        code = 1
    else:
        # Every record decoded and no decoded field holds a hit, so a raw-only hit is bytes that
        # aren't text (e.g. a varint read as letters): listed as noise, not gating.
        out.append("verdict: PASS" + (" (raw-byte-only hits, noise: %d)" % raw if raw else ""))
        code = 0
    print("\n".join(out))
    return code


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("dump", "leaves"):
        s = sub.add_parser(name)
        s.add_argument("--work", required=True)
        s.add_argument("inputs", nargs="+")
    s = sub.add_parser("report")
    s.add_argument("--work", required=True)
    a = p.parse_args(argv)
    if a.cmd == "dump":
        cmd_dump(a)
        return 0
    if a.cmd == "leaves":
        cmd_leaves(a)
        return 0
    return cmd_report(a)


if __name__ == "__main__":
    sys.exit(main())
