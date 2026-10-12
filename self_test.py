# -*- coding: utf-8 -*-
"""self_test for oncall-handoff-spec (scaffold v2, four defenses inherited).

D1: SystemExit caught in run_cli. D2: unicode fields exercised.
D3: fixtures written with newline="". D4: last line "SUMMARY: PASS n/n".
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")  # D3

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "core", os.path.join(_HERE, "oncall_handoff_spec.py"))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)
main = core.main

CASES = []


def case(category, name):
    def deco(fn):
        CASES.append((category, name, fn))
        return fn
    return deco


def run_cli(argv):
    buf_out, buf_err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            ret = main(argv)
            code = 0 if ret is None else int(ret)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:
        code = 1
        buf_err.write(repr(e))
    return code, buf_out.getvalue(), buf_err.getvalue()


_TMP = tempfile.mkdtemp(prefix="ohs_selftest_")


def write_fixture(name, obj):
    p = os.path.join(_TMP, name)
    with open(p, "w", encoding="utf-8", newline="") as f:  # D3
        f.write(json.dumps(obj, ensure_ascii=False, indent=2))
    return p


BASE = {
    "shift": {"start": "2026-10-13T08:00:00Z", "end": "2026-10-13T20:00:00Z"},
    "engineer": "oncall-alias-7",
    "in_progress": [{"id": "INC-1", "status": "investigating",
                     "next_step": "check upstream logs", "owner": "alias-a"}],
    "risks": [{"id": "R-1", "description": "dep may be stale",
               "severity": "medium", "mitigation": "pin revision"}],
    "muted_alerts": [{"alert": "cpu-high", "reason": "known burn-in",
                      "until": "2026-10-14T00:00:00Z"}]}


def doc(**over):
    d = copy.deepcopy(BASE)
    for k, v in over.items():
        d[k] = v
    return d


# ---------- [A] functional ----------
def _t_base_valid():
    rep = core.validate_handoff(doc())
    assert rep["errors"] == [] and rep["warnings"] == [], rep
case("A", "baseline handoff valid")(_t_base_valid)

def _t_score_full():
    assert core.validate_handoff(doc())["score"] == 1.0
case("A", "baseline score is 1.0")(_t_score_full)

def _t_empty_sections_ok():
    rep = core.validate_handoff(doc(in_progress=[], risks=[], muted_alerts=[]))
    assert rep["errors"] == [] and rep["score"] == 1.0
case("A", "empty required sections acceptable")(_t_empty_sections_ok)

def _t_shift_order():
    rep = core.validate_handoff(doc(shift={"start": "2026-10-13T20:00:00Z",
                                           "end": "2026-10-13T08:00:00Z"}))
    assert rep["errors"] and rep["checks"]["shift_valid"] is False
case("A", "start after end rejected")(_t_shift_order)

def _t_epoch_shift():
    rep = core.validate_handoff(doc(shift={"start": 1791907200, "end": 1791950400}))
    assert rep["errors"] == []
case("A", "epoch-number shift bounds accepted")(_t_epoch_shift)

def _t_medium_warn():
    d = doc(risks=[{"id": "R", "description": "x", "severity": "medium"}])
    rep = core.validate_handoff(d)
    assert rep["errors"] == [] and rep["warnings"]
case("A", "medium risk w/o mitigation warns")(_t_medium_warn)

def _t_low_no_mitigation():
    d = doc(risks=[{"id": "R", "description": "x", "severity": "low"}])
    rep = core.validate_handoff(d)
    assert rep["errors"] == [] and rep["warnings"] == []
case("A", "low risk needs no mitigation")(_t_low_no_mitigation)

def _t_score_partial():
    d = doc(engineer="")
    rep = core.validate_handoff(d)
    assert 0 < rep["score"] < 1.0
case("A", "partial failure lowers score")(_t_score_partial)

def _t_mute_midshift_warn():
    d = doc(muted_alerts=[{"alert": "a", "reason": "r",
                           "until": "2026-10-13T09:00:00Z"}])
    rep = core.validate_handoff(d)
    assert rep["errors"] == [] and any("mid-shift" in w["message"]
                                       for w in rep["warnings"])
case("A", "mute expiring mid-shift warns")(_t_mute_midshift_warn)

def _t_deployments_ok():
    d = doc(deployments=[{"service": "api", "revision": "rev9",
                          "at": "2026-10-13T09:00:00Z"}])
    assert core.validate_handoff(d)["errors"] == []
case("A", "well-formed deployment accepted")(_t_deployments_ok)

def _t_open_questions_ok():
    d = doc(open_questions=[{"question": "who owns queue?"}])
    assert core.validate_handoff(d)["errors"] == []
case("A", "well-formed open question accepted")(_t_open_questions_ok)

def _t_unicode_fields():
    d = doc(engineer="值班-α", in_progress=[{"id": "工单-1", "status": "排查中",
                                            "next_step": "查日志", "owner": "甲"}])
    rep = core.validate_handoff(d)
    assert rep["errors"] == []
case("A", "unicode fields accepted (D2)")(_t_unicode_fields)

def _t_cli_validate_ok():
    p = write_fixture("h.json", doc())
    code, out, _ = run_cli(["validate", p])
    assert code == 0 and "score=1.00" in out
case("A", "CLI validate good -> 0")(_t_cli_validate_ok)

def _t_cli_validate_json():
    p = write_fixture("h.json", doc())
    code, out, _ = run_cli(["validate", p, "--json"])
    parsed = json.loads(out)
    assert code == 0 and parsed["score"] == 1.0 and parsed["errors"] == []
case("A", "CLI validate --json round-trip")(_t_cli_validate_json)

def _t_cli_validate_bad():
    p = write_fixture("h.json", {"shift": {}})
    code, out, _ = run_cli(["validate", p])
    assert code == 1
case("A", "CLI validate broken -> 1")(_t_cli_validate_bad)

def _t_cli_min_score():
    p = write_fixture("h.json", doc(engineer=""))
    code1, _, _ = run_cli(["validate", p, "--min-score", "0.8"])
    code2, _, _ = run_cli(["validate", p, "--min-score", "1.0"])
    assert code1 == 0 and code2 == 1
case("A", "--min-score threshold controls exit")(_t_cli_min_score)

def _t_cli_bench():
    code, out, _ = run_cli(["bench", "--docs", "200"])
    assert code == 0 and "docs/s" in out
case("A", "CLI bench runs")(_t_cli_bench)

def _t_checks_shape():
    rep = core.validate_handoff(doc())
    assert set(rep) == {"errors", "warnings", "score", "checks"}
    assert set(rep["checks"]) == {"sections_present", "shift_valid", "engineer",
                                  "in_progress_complete", "risks_severity_valid",
                                  "high_risks_mitigated", "muted_complete",
                                  "timestamps_parse", "optional_sections_valid"}
case("A", "report shape stable")(_t_checks_shape)

def _t_severities_vocab():
    for sev in ("low", "medium", "high"):
        d = doc(risks=[{"id": "R", "description": "x", "severity": sev,
                        "mitigation": "m"}])
        assert core.validate_handoff(d)["errors"] == []
case("A", "all severity levels valid")(_t_severities_vocab)

# ---------- [B] exception paths ----------
def _t_non_dict():
    rep = core.validate_handoff([1])
    assert rep["errors"][0]["rule"] == "R1" and rep["score"] == 0.0
case("B", "non-dict handoff -> R1, score 0")(_t_non_dict)

def _t_shift_missing():
    rep = core.validate_handoff(doc(shift=None))
    assert any(e["rule"] == "R2" for e in rep["errors"])
case("B", "missing shift -> R2")(_t_shift_missing)

def _t_bad_ts():
    rep = core.validate_handoff(doc(shift={"start": "soon", "end": "later"}))
    assert any(e["rule"] == "R2" for e in rep["errors"])
case("B", "unparseable shift timestamps -> R2")(_t_bad_ts)

def _t_empty_engineer():
    rep = core.validate_handoff(doc(engineer="   "))
    assert any(e["rule"] == "R3" for e in rep["errors"])
case("B", "blank engineer -> R3")(_t_empty_engineer)

def _t_missing_section():
    d = doc()
    del d["risks"]
    rep = core.validate_handoff(d)
    assert any(e["rule"] == "R4" and e["path"] == "$.risks" for e in rep["errors"])
case("B", "missing risks section -> R4")(_t_missing_section)

def _t_section_not_list():
    rep = core.validate_handoff(doc(in_progress="todo"))
    assert any(e["rule"] == "R4" for e in rep["errors"])
case("B", "section not a list -> R4")(_t_section_not_list)

def _t_ip_missing_next_step():
    d = doc(in_progress=[{"id": "I", "status": "open", "next_step": "", "owner": "o"}])
    rep = core.validate_handoff(d)
    assert any(e["path"].endswith("next_step") for e in rep["errors"])
case("B", "in_progress without next_step -> R5")(_t_ip_missing_next_step)

def _t_ip_not_dict():
    d = doc(in_progress=["oops"])
    rep = core.validate_handoff(d)
    assert any(e["rule"] == "R5" for e in rep["errors"])
case("B", "in_progress item not object -> R5")(_t_ip_not_dict)

def _t_bad_severity():
    d = doc(risks=[{"id": "R", "description": "x", "severity": "extreme"}])
    rep = core.validate_handoff(d)
    assert any(e["rule"] == "R6" and "severity" in e["path"] for e in rep["errors"])
case("B", "unknown severity -> R6")(_t_bad_severity)

def _t_high_no_mitigation():
    d = doc(risks=[{"id": "R", "description": "x", "severity": "high"}])
    rep = core.validate_handoff(d)
    assert any("mitigation" in e["path"] for e in rep["errors"])
case("B", "high risk w/o mitigation -> R6 error")(_t_high_no_mitigation)

def _t_mute_no_reason():
    d = doc(muted_alerts=[{"alert": "a", "reason": "", "until": "2026-10-14T00:00:00Z"}])
    rep = core.validate_handoff(d)
    assert any(e["path"].endswith("reason") for e in rep["errors"])
case("B", "muted alert without reason -> R7")(_t_mute_no_reason)

def _t_mute_bad_until():
    d = doc(muted_alerts=[{"alert": "a", "reason": "r", "until": "tomorrow"}])
    rep = core.validate_handoff(d)
    assert any(e["path"].endswith("until") for e in rep["errors"])
    assert rep["checks"]["timestamps_parse"] is False
case("B", "unparseable until -> R7 + ts check fails")(_t_mute_bad_until)

def _t_deploy_bad_at():
    d = doc(deployments=[{"service": "api", "revision": "r", "at": "morning"}])
    rep = core.validate_handoff(d)
    assert any(e["path"].endswith(".at") for e in rep["errors"])
case("B", "deployment with bad timestamp -> R8")(_t_deploy_bad_at)

def _t_oq_empty():
    d = doc(open_questions=[{"question": " "}])
    rep = core.validate_handoff(d)
    assert any(e["rule"] == "R9" for e in rep["errors"])
case("B", "blank open question -> R9")(_t_oq_empty)

def _t_no_args():
    code, _, _ = run_cli([])
    assert code == 2
case("B", "CLI no args -> SystemExit 2 (D1)")(_t_no_args)

def _t_unknown_cmd():
    code, _, _ = run_cli(["handoff"])
    assert code == 2
case("B", "CLI unknown subcommand -> 2")(_t_unknown_cmd)

def _t_missing_file():
    code, _, err = run_cli(["validate", os.path.join(_TMP, "nope.json")])
    assert code == 1 and "cannot read" in err
case("B", "CLI missing file -> 1")(_t_missing_file)

def _t_broken_json():
    p = os.path.join(_TMP, "broken.json")
    with open(p, "w", encoding="utf-8", newline="") as f:  # D3
        f.write("{not json")
    code, _, _ = run_cli(["validate", p])
    assert code == 1
case("B", "CLI unparseable JSON -> 1")(_t_broken_json)

def _t_bad_min_score_type():
    p = write_fixture("h.json", doc())
    code, _, _ = run_cli(["validate", p, "--min-score", "abc"])
    assert code == 2
case("B", "non-numeric --min-score -> 2")(_t_bad_min_score_type)

# ---------- [C] extreme edges ----------
def _t_crlf_file():
    p = os.path.join(_TMP, "crlf.json")
    with open(p, "w", encoding="utf-8", newline="") as f:  # D3
        f.write(json.dumps(doc(), indent=2) + "\r\n")
    code, _, _ = run_cli(["validate", p])
    assert code == 0
case("C", "CRLF-terminated handoff file (D3)")(_t_crlf_file)

def _t_offset_ts():
    d = doc(shift={"start": "2026-10-13T16:00:00+08:00",
                   "end": "2026-10-14T04:00:00+08:00"})
    assert core.validate_handoff(d)["errors"] == []
case("C", "shift with +08:00 offsets")(_t_offset_ts)

def _t_space_ts():
    d = doc(shift={"start": "2026-10-13 08:00:00", "end": "2026-10-13 20:00:00"})
    assert core.validate_handoff(d)["errors"] == []
case("C", "space-separated timestamps")(_t_space_ts)

def _t_long_fields():
    d = doc(in_progress=[{"id": "I" * 5000, "status": "s", "next_step": "n" * 5000,
                          "owner": "o"}])
    assert core.validate_handoff(d)["errors"] == []
case("C", "5k-char fields tolerated")(_t_long_fields)

def _t_many_risks():
    risks = [{"id": "R-%d" % i, "description": "d%d" % i, "severity": "low"}
             for i in range(500)]
    rep = core.validate_handoff(doc(risks=risks))
    assert rep["errors"] == [] and rep["score"] == 1.0
case("C", "500 risks validated")(_t_many_risks)

def _t_extra_keys():
    d = doc(future_field={"x": 1})
    assert core.validate_handoff(d)["errors"] == []
case("C", "unknown top-level keys tolerated")(_t_extra_keys)

def _t_extra_item_keys():
    d = doc(risks=[{"id": "R", "description": "x", "severity": "low", "tag": "extra"}])
    assert core.validate_handoff(d)["errors"] == []
case("C", "unknown item keys tolerated")(_t_extra_item_keys)

def _t_deploy_optional_absent():
    assert core.validate_handoff(doc())["errors"] == []
case("C", "absent optional sections fine")(_t_deploy_optional_absent)

def _t_deploy_empty_list():
    d = doc(deployments=[], open_questions=[])
    assert core.validate_handoff(d)["errors"] == []
case("C", "empty optional lists fine")(_t_deploy_empty_list)

def _t_epoch_until():
    d = doc(muted_alerts=[{"alert": "a", "reason": "r", "until": 1791950400}])
    assert core.validate_handoff(d)["errors"] == []
case("C", "epoch-number until accepted")(_t_epoch_until)

def _t_naive_ts():
    d = doc(shift={"start": "2026-10-13T08:00:00", "end": "2026-10-13T20:00:00"})
    assert core.validate_handoff(d)["errors"] == []
case("C", "naive timestamps treated as UTC")(_t_naive_ts)

def _t_perf_sane():
    docs = [{"shift": {"start": "2026-10-13T08:00:00Z", "end": "2026-10-13T20:00:00Z"},
             "engineer": "e%d" % i, "in_progress": [], "risks": [], "muted_alerts": []}
            for i in range(3000)]
    rep = [core.validate_handoff(d) for d in docs]
    assert all(r["errors"] == [] for r in rep)
case("C", "3k docs validated without error")(_t_perf_sane)

def _t_only_engineer_failing_score():
    rep = core.validate_handoff(doc(engineer=""))
    assert rep["score"] == round(14 / 15, 4)
case("A", "weight math: engineer-only failure -> 14/15")(_t_only_engineer_failing_score)

def _t_high_mitigated_ok():
    d = doc(risks=[{"id": "R", "description": "db failover pending",
                    "severity": "high", "mitigation": "runbook rb-7 pinned"}])
    rep = core.validate_handoff(d)
    assert rep["errors"] == [] and rep["score"] == 1.0
case("A", "mitigated high risk accepted")(_t_high_mitigated_ok)

def _t_severity_case_sensitive():
    d = doc(risks=[{"id": "R", "description": "x", "severity": "High"}])
    assert any(e["rule"] == "R6" for e in core.validate_handoff(d)["errors"])
case("A", "severity 'High' (capitalized) rejected")(_t_severity_case_sensitive)

def _t_until_equals_end_ok():
    d = doc(muted_alerts=[{"alert": "a", "reason": "r",
                           "until": "2026-10-13T20:00:00Z"}])
    rep = core.validate_handoff(d)
    assert rep["errors"] == [] and rep["warnings"] == []
case("A", "mute until == shift end is not mid-shift")(_t_until_equals_end_ok)

def _t_zero_width_shift():
    rep = core.validate_handoff(doc(shift={"start": "2026-10-13T08:00:00Z",
                                           "end": "2026-10-13T08:00:00Z"}))
    assert any(e["rule"] == "R2" for e in rep["errors"])
case("A", "zero-length shift rejected")(_t_zero_width_shift)

def _t_emoji_engineer():
    rep = core.validate_handoff(doc(engineer="oncall-🤖-7"))
    assert rep["errors"] == []
case("A", "emoji pseudonym accepted (D2)")(_t_emoji_engineer)

def _t_cli_min_score_zero():
    p = write_fixture("h.json", doc(engineer=""))
    code, _, _ = run_cli(["validate", p, "--min-score", "0"])
    assert code == 0
case("A", "--min-score 0 lenient mode")(_t_cli_min_score_zero)

def _t_deploy_missing_revision():
    d = doc(deployments=[{"service": "api", "at": "2026-10-13T09:00:00Z"}])
    rep = core.validate_handoff(d)
    assert any(e["path"].endswith("revision") for e in rep["errors"])
case("A", "deployment missing revision -> R8")(_t_deploy_missing_revision)

def _t_oq_not_dict():
    d = doc(open_questions=["who?"])
    rep = core.validate_handoff(d)
    assert any(e["rule"] == "R9" for e in rep["errors"])
case("A", "open_questions item not object -> R9")(_t_oq_not_dict)

def _t_all_checks_true_baseline():
    rep = core.validate_handoff(doc())
    assert all(rep["checks"].values())
case("A", "baseline: every check passes")(_t_all_checks_true_baseline)

def _t_meta_count():
    assert len(CASES) >= 60
case("C", "meta: at least 60 cases defined")(_t_meta_count)


class T(unittest.TestCase):
    pass


def _add(i, cat, name, fn):
    def t(self, _f=fn):
        _f()
    t.__doc__ = "%s: %s" % (cat, name)
    setattr(T, "test_%s_%03d_%s" % (cat, i, re.sub(r"[^0-9A-Za-z_]", "_", name)), t)


for _i, (_c, _n, _f) in enumerate(CASES):
    _add(_i + 1, _c, _n, _f)

if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"]))
    total, fails = r.testsRun, len(r.failures) + len(r.errors)
    print("SUMMARY: PASS %d/%d" % (total - fails, total))  # D4
    sys.exit(0 if fails == 0 else 1)
