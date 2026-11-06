#!/usr/bin/env python3
"""PRD-16 central-resolution end-to-end acceptance harness.

Runs ONE fixed checklist (see checks.py) against a REPLICA of the real machine and real projects.
Every check runs to completion even when earlier checks fail.  Real state is read-only and guarded by a sentinel.

  python3 run.py                         full run, report in <sandbox>/report.json
  python3 run.py --only CR-C,CR-F        just those checks (plus the setup they need)
  python3 run.py --rerun-failed REPORT   rerun the failed checks of an earlier report
  python3 run.py --rerun-failed REPORT --with-adjacent   ... plus every check that shares a component with a failure
  python3 run.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import checks as ck  # noqa: E402
import harness as hn  # noqa: E402
import replica as rp  # noqa: E402


def adjacency(failed_ids: set[str]) -> dict[str, list[str]]:
    tags = {i: c.tags for i, c in ck.REGISTRY.items()}
    return {i: sorted(j for j in tags if j != i and tags[i] & tags[j]) for i in failed_ids if i in tags}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated check IDs (e.g. CR-C,CR-F)")
    ap.add_argument("--rerun-failed", metavar="REPORT", help="rerun the failed checks recorded in REPORT")
    ap.add_argument("--with-adjacent", action="store_true", help="with --rerun-failed: add checks sharing components")
    ap.add_argument("--sandbox", help="sandbox root (default: /Volumes/Dev/cr-acceptance/<timestamp>)")
    ap.add_argument("--report", help="report path (default: <sandbox>/report.json)")
    ap.add_argument("--keep-credentials", action="store_true", help="leave copied auth files in the sandbox")
    ap.add_argument("--reuse", action="store_true", help="debug only: reuse an existing sandbox instead of rebuilding")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for i in ck.ORDER:
            c = ck.REGISTRY[i]
            print(f"{i}  {c.title}   [components: {', '.join(sorted(c.tags))}]")
        print("CR-S  Real-state sentinel (always runs)")
        return 0

    selected = list(ck.ORDER)
    if args.only:
        want = [x.strip() for x in args.only.split(",") if x.strip()]
        unknown = [x for x in want if x not in ck.REGISTRY]
        if unknown:
            print(f"unknown check IDs: {unknown}", file=sys.stderr)
            return 2
        selected = [i for i in ck.ORDER if i in want]
    if args.rerun_failed:
        prev = json.loads(Path(args.rerun_failed).read_text())
        failed = {i for i, c in prev["checks"].items() if c["status"] != "PASS" and i in ck.REGISTRY}
        want = set(failed)
        if args.with_adjacent:
            for adj in adjacency(failed).values():
                want |= set(adj)
        selected = [i for i in ck.ORDER if i in want]
        print(f"rerun: failed={sorted(failed)} selected={selected}")

    sandbox = Path(args.sandbox or f"/Volumes/Dev/cr-acceptance/{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}")
    t0 = time.monotonic()
    support = []
    # ---- sentinel before ----------------------------------------------------------------------------
    support = []  # the six role projects are always sentineled; shared checkouts are active workspaces and are not
    before = hn.sentinel_snapshot(support)

    # ---- replica -------------------------------------------------------------------------------------
    print(f"building replica in {sandbox} ...", flush=True)
    tb = time.monotonic()
    if args.reuse and (sandbox / "home").is_dir():
        rep = rp.Replica(root=sandbox)
        for r_, n_, role in rp.PROJECTS:
            rep.projects[role] = sandbox / "Sites" / r_ / n_
        rep.notes.append("sandbox reused (debug)")
        import shutil
        shutil.copy2(rp.REAL_HOME / ".codex" / "auth.json", rep.codex_home / "auth.json")
    else:
        rep = rp.build(sandbox)
    # claude authenticates through the login keychain, found via the home directory: expose it read-only
    (rep.home / "Library").mkdir(exist_ok=True)
    kc = rep.home / "Library" / "Keychains"
    if not kc.exists():
        os.symlink(rp.REAL_HOME / "Library" / "Keychains", kc)
    print(f"replica built in {time.monotonic() - tb:.0f}s", flush=True)
    ctx = ck.Ctx(rep, sandbox / "work")
    ctx.work.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    selected_run = (["CR-R"] if "CR-R" not in selected else []) + selected
    for cid in selected_run:
        c = ck.REGISTRY[cid]
        res = ck.Result(cid)
        t = time.monotonic()
        try:
            c.fn(ctx, res)
        except Exception:
            res.error = traceback.format_exc()[-1500:]
            res.ok("exception", False, "check runs to completion", res.error, "harness or product crash")
        secs = time.monotonic() - t
        status = "PASS" if res.passed else "FAIL"
        reported = cid in selected
        results[cid] = {"status": status, "title": c.title, "secs": round(secs, 1), "asserts": res.asserts,
                        "evidence": res.evidence, "error": res.error, "reported": reported}
        n_fail = sum(1 for a in res.asserts if not a["ok"])
        print(f"{status}  {cid}  {c.title}  ({secs:.0f}s, {len(res.asserts) - n_fail}/{len(res.asserts)} assertions)"
              + ("" if reported else "  [prerequisite]"), flush=True)

    # ---- sentinel after ------------------------------------------------------------------------------
    after = hn.sentinel_snapshot(support)
    changed = {k: {"before": before[k], "after": after.get(k)} for k in before if before[k] != after.get(k)}
    sres = ck.Result("CR-S")
    sres.ok("unchanged", not changed, "no sentinel item of the real machine or real projects changed during the run",
            json.dumps(changed)[:800] if changed else f"{len(before)} items identical",
            "harness wrote to real state, OR a concurrent real session changed it (compare timestamps)", ["harness.py", "replica.py"])
    results["CR-S"] = {"status": "PASS" if sres.passed else "FAIL", "title": "Real-state sentinel", "secs": 0,
                       "asserts": sres.asserts, "evidence": {"items": sorted(before)}, "error": "", "reported": True}
    print(f"{results['CR-S']['status']}  CR-S  Real-state sentinel  ({len(before)} items)")

    # ---- credentials never stay behind -----------------------------------------------------------------
    if not args.keep_credentials:
        for p in (rep.codex_home / "auth.json", rep.home / "Library" / "Keychains"):
            try:
                p.unlink()
            except OSError:
                pass

    # ---- consolidated defect list ----------------------------------------------------------------------
    failed_ids = {i for i, c in results.items() if c["status"] == "FAIL" and c.get("reported", True)}
    adj = adjacency(failed_ids)
    defects = []
    for cid in sorted(failed_ids):
        for a in results[cid]["asserts"]:
            if not a["ok"]:
                defects.append({"check": cid, "assertion": a["id"], "expected": a["expected"], "observed": a["observed"],
                                "suspected_cause": a["suspected_cause"], "components_files": a["files"],
                                "adjacent_checks": adj.get(cid, [])})
    try:
        sha = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:
        sha = ""
    rerun = sorted(failed_ids | {x for v in adj.values() for x in v})
    report = {
        "harness_commit": sha, "release_under_test": ctx.baseline_id, "sandbox": str(sandbox),
        "total_secs": round(time.monotonic() - t0), "selected": selected,
        "summary": {i: results[i]["status"] for i in results if results[i].get("reported", True)},
        "checks": results, "defects": defects,
        "rerun_after_fix": f"python3 {HERE / 'run.py'} --only {','.join(i for i in rerun if i != 'CR-S')}" if rerun else "",
        "notes": rep.notes,
    }
    out = Path(args.report or sandbox / "report.json")
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nreport: {out}")
    if defects:
        print(f"\nCONSOLIDATED DEFECT LIST ({len(defects)})")
        for d in defects:
            print(f"- {d['assertion']}\n    expected: {d['expected']}\n    observed: {d['observed'][:400]}\n"
                  f"    cause: {d['suspected_cause']}\n    files: {', '.join(d['components_files'])}\n"
                  f"    adjacent checks: {', '.join(d['adjacent_checks']) or '-'}")
        print(f"\nafter fixes: {report['rerun_after_fix']}")
    return 1 if any(c["status"] != "PASS" for c in results.values() if c.get("reported", True)) else 0


if __name__ == "__main__":
    sys.exit(main())
