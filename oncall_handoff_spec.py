# -*- coding: utf-8 -*-
"""oncall-handoff-spec: shift-handoff document schema (in-progress items,
risks, muted alerts) + completeness validator.

Pure standard library. CLI via argparse.
Exit codes: 0 valid & score >= min-score, 1 errors or score below threshold,
2 usage error (argparse).
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone

SEVERITIES = ("low", "medium", "high")
REQUIRED_SECTIONS = ("in_progress", "risks", "muted_alerts")
TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$")
IDENT_RE = re.compile(r"^[^\W\d][\w-]*$", re.UNICODE)


def parse_ts(s):
    """Parse ISO-8601 (or epoch number) to aware epoch seconds; None on failure."""
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return float(s)
    if not isinstance(s, str):
        return None
    t = s.strip()
    if TS_RE.match(t):
        t2 = t.replace(" ", "T")
        if t2.endswith("Z"):
            t2 = t2[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(t2)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    try:
        return float(t)
    except ValueError:
        return None


def _nonempty_str(v):
    return isinstance(v, str) and bool(v.strip())


def validate_handoff(doc):
    """Validate a handoff document. Returns report dict:
    {errors, warnings, score, checks}."""
    errs, warns = [], []

    def err(rule, path, msg):
        errs.append({"rule": rule, "path": path, "message": msg})

    def warn(rule, path, msg):
        warns.append({"rule": rule, "path": path, "message": msg})

    if not isinstance(doc, dict):
        err("R1", "$", "handoff must be a JSON object")
        return {"errors": errs, "warnings": warns, "score": 0.0, "checks": {}}

    checks = {}
    # R2/R3 shift + engineer
    start_ts = end_ts = None
    shift = doc.get("shift")
    if not isinstance(shift, dict):
        err("R2", "$.shift", "shift must be an object")
        checks["shift_valid"] = False
    else:
        start_ts = parse_ts(shift.get("start"))
        end_ts = parse_ts(shift.get("end"))
        ok = start_ts is not None and end_ts is not None and start_ts < end_ts
        if not ok:
            err("R2", "$.shift", "shift.start/end must be ISO timestamps with start < end")
        checks["shift_valid"] = ok
    engineer = doc.get("engineer")
    eng_ok = _nonempty_str(engineer)
    if not eng_ok:
        err("R3", "$.engineer", "engineer must be a non-empty string (pseudonym ok)")
    checks["engineer"] = eng_ok

    # R4 required sections
    sections_ok = True
    lists = {}
    for sec in REQUIRED_SECTIONS:
        v = doc.get(sec)
        if not isinstance(v, list):
            err("R4", "$." + sec, "section %s must be present and a list" % sec)
            sections_ok = False
            v = []
        lists[sec] = v
    checks["sections_present"] = sections_ok

    # R5 in_progress completeness
    ip_ok = True
    for i, item in enumerate(lists["in_progress"]):
        path = "$.in_progress[%d]" % i
        if not isinstance(item, dict):
            err("R5", path, "item must be an object")
            ip_ok = False
            continue
        for field in ("id", "status", "next_step", "owner"):
            if not _nonempty_str(item.get(field)):
                err("R5", path + "." + field, "%s must be a non-empty string" % field)
                ip_ok = False
    checks["in_progress_complete"] = ip_ok

    # R6 risks
    sev_ok, mit_ok = True, True
    for i, item in enumerate(lists["risks"]):
        path = "$.risks[%d]" % i
        if not isinstance(item, dict):
            err("R6", path, "risk must be an object")
            sev_ok = False
            continue
        if not _nonempty_str(item.get("id")) or not _nonempty_str(item.get("description")):
            err("R6", path, "risk needs non-empty id and description")
            sev_ok = False
        sev = item.get("severity")
        if sev not in SEVERITIES:
            err("R6", path + ".severity", "severity must be one of %s" % (", ".join(SEVERITIES),))
            sev_ok = False
        mit = item.get("mitigation")
        if sev == "high" and not _nonempty_str(mit):
            err("R6", path + ".mitigation", "high-severity risk requires a mitigation")
            mit_ok = False
        elif sev == "medium" and not _nonempty_str(mit):
            warn("R6", path + ".mitigation", "medium risk without mitigation (advisory)")
    checks["risks_severity_valid"] = sev_ok
    checks["high_risks_mitigated"] = mit_ok

    # R7 muted alerts
    muted_ok, ts_ok = True, True
    for i, item in enumerate(lists["muted_alerts"]):
        path = "$.muted_alerts[%d]" % i
        if not isinstance(item, dict):
            err("R7", path, "muted alert must be an object")
            muted_ok = False
            continue
        for field in ("alert", "reason"):
            if not _nonempty_str(item.get(field)):
                err("R7", path + "." + field, "%s must be a non-empty string" % field)
                muted_ok = False
        until = parse_ts(item.get("until"))
        if until is None:
            err("R7", path + ".until", "until must be an ISO timestamp")
            muted_ok = False
            ts_ok = False
        elif end_ts is not None and until < end_ts:
            warn("R7", path + ".until", "mute expires mid-shift; re-evaluate at handoff")
    checks["muted_complete"] = muted_ok
    checks["timestamps_parse"] = ts_ok

    # R8 deployments (optional)
    dep_ok = True
    for i, item in enumerate(doc.get("deployments", []) or []):
        path = "$.deployments[%d]" % i
        if not isinstance(item, dict):
            err("R8", path, "deployment must be an object")
            dep_ok = False
            continue
        for field in ("service", "revision"):
            if not _nonempty_str(item.get(field)):
                err("R8", path + "." + field, "%s must be a non-empty string" % field)
                dep_ok = False
        if parse_ts(item.get("at")) is None:
            err("R8", path + ".at", "at must be an ISO timestamp")
            dep_ok = False

    # R9 open_questions (optional)
    oq_ok = True
    for i, item in enumerate(doc.get("open_questions", []) or []):
        path = "$.open_questions[%d]" % i
        if not isinstance(item, dict) or not _nonempty_str(item.get("question")):
            err("R9", path, "open question needs a non-empty 'question'")
            oq_ok = False
    checks["optional_sections_valid"] = dep_ok and oq_ok

    weights = {"sections_present": 3, "shift_valid": 2, "engineer": 1,
               "in_progress_complete": 2, "risks_severity_valid": 1,
               "high_risks_mitigated": 2, "muted_complete": 2, "timestamps_parse": 1,
               "optional_sections_valid": 1}
    total = sum(weights.values())
    score = round(sum(w for k, w in weights.items() if checks.get(k)) / total, 4)
    return {"errors": errs, "warnings": warns, "score": score, "checks": checks}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_validate(args):
    try:
        doc = _load(args.handoff)
    except (OSError, ValueError) as e:
        print("cannot read/parse %s: %s" % (args.handoff, e), file=sys.stderr)
        return 1
    rep = validate_handoff(doc)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for e in rep["errors"]:
            print("error %s %s: %s" % (e["rule"], e["path"], e["message"]))
        for w in rep["warnings"]:
            print("warn  %s %s: %s" % (w["rule"], w["path"], w["message"]))
        print("score=%.2f %s" % (rep["score"],
                                 "OK" if not rep["errors"] else "%d error(s)" % len(rep["errors"])))
    if rep["score"] < args.min_score:
        return 1
    return 0


def _synthetic_doc(i):
    return {
        "shift": {"start": "2026-10-13T08:00:00Z", "end": "2026-10-13T20:00:00Z"},
        "engineer": "alias-%04d" % i,
        "in_progress": [{"id": "INC-%d" % i, "status": "investigating",
                         "next_step": "check upstream logs", "owner": "alias-a"}],
        "risks": [{"id": "R-%d" % i, "description": "dep may be stale",
                   "severity": "medium", "mitigation": "pin revision"}],
        "muted_alerts": [{"alert": "cpu-high-%d" % i, "reason": "known burn-in",
                          "until": "2026-10-14T00:00:00Z"}],
        "deployments": [{"service": "svc-%d" % i, "revision": "rev-%d" % i,
                         "at": "2026-10-13T09:00:00Z"}],
        "open_questions": [{"question": "who owns queue-%d?" % i}]}


def cmd_bench(args):
    docs = [_synthetic_doc(i) for i in range(args.docs)]
    t0 = time.perf_counter()
    n_err = 0
    for d in docs:
        n_err += len(validate_handoff(d)["errors"])
    dt = time.perf_counter() - t0
    print("bench: %d handoff docs validated in %.3fs (%.0f docs/s, %d errors)"
          % (args.docs, dt, args.docs / dt if dt > 0 else 0, n_err))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="oncall-handoff-spec",
        description="On-call shift handoff schema (in-progress / risks / muted "
                    "alerts) + completeness validator.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate a handoff JSON file")
    v.add_argument("handoff")
    v.add_argument("--min-score", type=float, default=1.0,
                   help="minimum completeness score (0..1)")
    v.add_argument("--json", action="store_true")
    v.set_defaults(fn=cmd_validate)
    b = sub.add_parser("bench", help="synthetic benchmark")
    b.add_argument("--docs", type=int, default=5000)
    b.set_defaults(fn=cmd_bench)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
