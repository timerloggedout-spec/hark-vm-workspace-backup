#!/usr/bin/env python3
"""hark-vm deterministic node pass: drain REQUESTS ⇒ eval ⇒ append ledgers ⇒ prune.
Zero-LLM: one shell call per wake. Exit 0 = nothing to report; exit 2 = state change (stdout = stamp lines); exit 1 = blocked."""
import base64, json, os, shutil, subprocess, sys, time, uuid
from datetime import datetime, timezone

O, R, STORE = "timerloggedout-spec", "termux-monorepo", "hark-vm-workspace-backup"
WD = "/workspace/work/hark-vm-node"
SUITES = ["tests/test_branch_reconciliation_registry.py", "tests/test_que_branch_reconciliation_intake.py",
          "tests/test_orchestrator_benchmark.py", "scripts/que/test_task_ranking.py", "tests/test_flywheel.py",
          "tests/test_lead_lag_cadence.py", "scripts/dispatch/test_auto_claim.py"]
SHADOW_JOBS = {
    "matrice-validate": "python3 scripts/linguist/matrice_search.py validate",
    "temporal-import-smoke": "python3 -m unittest tests.test_temporal_hello_import",
    "lead-lag-cadence": "python3 scripts/ops/lead_lag_cadence.py --owner timerloggedout-spec --repo termux-monorepo --branch master --per-page 50 --out /tmp/lead-lag-cadence.json",
}
# gating (2026-11-23): run a shadow job only when its inputs changed (paths) ∨ its max-age lapsed (hours)
SHADOW_GATE = {
    "matrice-validate": {"paths": ["scripts/linguist/", "docs/proposals/active/notation-sets/"], "max_age_h": 24},
    "temporal-import-smoke": {"paths": ["scripts/temporal/", "tests/test_temporal_hello_import.py"], "max_age_h": 24},
    "lead-lag-cadence": {"paths": [], "max_age_h": 6},
}
ALLOW = {"eval", "export", "hygiene", "probe", "clf-doe"}
PYLIB = "/workspace/hark-vm-node/pylib"
NOW = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
out = []

def api(*a):
    # argv via stdin ⇒ in-process runpy; ¬execve ⇒ ¬E2BIG (MAX_ARG_STRLEN 128 KiB) on large contents_put (#5672)
    stub = "import sys,json,runpy,shutil;sys.argv=['apicall','github']+json.load(sys.stdin);runpy.run_path(shutil.which('apicall'),run_name='__main__')"
    p = subprocess.run([sys.executable, "-c", stub], input=json.dumps(list(a)), capture_output=True, text=True)
    if p.returncode: raise RuntimeError(p.stderr[:300] or p.stdout[:300])
    return json.loads(p.stdout or "{}")

def get(path):
    try:
        j = api("contents_get", f"owner={O}", f"repo={STORE}", f"path={path}")
        return base64.b64decode(j["content"]).decode(), j["sha"]
    except RuntimeError as e:
        if "404" in str(e): return "", None
        raise

def append(path, lines, msg):
    if not lines: return None
    body, sha = get(path)
    body = body + "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines)
    a = ["contents_put", f"owner={O}", f"repo={STORE}", f"path={path}", f"message={msg} [skip render]",
         f"content={base64.b64encode(body.encode()).decode()}"]
    if sha: a.append(f"sha={sha}")
    return api(*a)["commit"]["sha"][:7]

def sh(cmd, cwd=None, t=600):
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=t)

def pytest(ref_dir, tests):
    paths = [t for t in tests if os.path.exists(os.path.join(ref_dir, t))]
    if not paths: return {"passed": 0, "failed": 0, "failing": []}
    t0 = time.time(); p = sh("python3 -m pytest -q -p no:cacheprovider -rf " + " ".join(paths), ref_dir)
    txt = p.stdout + p.stderr
    import re
    n = lambda k: sum(int(x) for x in re.findall(rf"(\d+) {k}", txt.splitlines()[-1] if txt else ""))
    return {"passed": n("passed"), "failed": n("failed") + n("error"),
            "failing": re.findall(r"^FAILED (\S+)", txt, re.M), "duration_s": round(time.time() - t0, 1)}

def clf_doe(r, budget=900):
    """clone clf-lab repo ⇒ run_doe --node hark-vm ≤4 cells ≤900s ⇒ append hark-vm rows to lab results/ledger.jsonl."""
    repo = (r.get("args") or {}).get("repo", "")
    if not repo.startswith(f"{O}/clf-lab-"): return "failed", f"repo {repo} ∉ clf-lab"
    d = f"/workspace/work/clf-{repo.split('/')[1]}"; shutil.rmtree(d, ignore_errors=True)
    ca = os.environ.get("SSL_CERT_FILE", "")
    if sh(f'git clone -q --depth 1 -c http.sslCAInfo="{ca}" https://github.com/{repo}.git {d}', t=300).returncode: return "failed", "clone ✗"
    if not os.path.isdir(PYLIB) and sh(f"pip install -q --target {PYLIB} -r {d}/requirements.txt", t=900).returncode:
        return "failed", "pip ✗"
    led = os.path.join(d, "results/ledger.jsonl"); before = open(led).read() if os.path.exists(led) else ""
    env = f"PYTHONPATH={PYLIB} CLF_NODE=hark-vm"
    try: p = sh(f"{env} python3 run_doe.py --node hark-vm --budget-s {int(budget)}", d, int(budget) + 120)
    except subprocess.TimeoutExpired: return "failed", "timeout"
    after = open(led).read() if os.path.exists(led) else ""
    new = after[len(before):] if after.startswith(before) else ""
    tail = ((p.stdout + p.stderr).strip().splitlines() or [""])[-1][:160]
    if p.returncode: shutil.rmtree(d, ignore_errors=True); return "failed", f"rc={p.returncode} {tail}"
    if new.strip():
        ro, rn = repo.split("/")
        j = api("contents_get", f"owner={ro}", f"repo={rn}", "path=results/ledger.jsonl")
        body = base64.b64decode(j["content"]).decode() + new
        api("contents_put", f"owner={ro}", f"repo={rn}", "path=results/ledger.jsonl", "message=record hark-vm DoE cells [skip render]",
            f"content={base64.b64encode(body.encode()).decode()}", f"sha={j['sha']}")
    shutil.rmtree(d, ignore_errors=True)
    return "done", f"{len(new.splitlines())} rows · {tail}"

T0 = time.time()
PASS_BUDGET = 1000  # s; background shell cap 1200
LABS = ["tier1-classifiers-steward", "live-2-prlane-tuning", "nc-1-notation-compliance", "bf-1-backfill-methods"]

def main():
    os.environ["PATH"] = "/workspace/hark-vm-node/bin:" + os.environ.get("PATH", "")
    os.environ.setdefault("GH_TOKEN", "injected")
    ca = os.environ.get("SSL_CERT_FILE", "")
    if not os.path.isdir(WD + "/.git"):
        shutil.rmtree(WD, ignore_errors=True)
        p = sh(f'git clone -q --depth 1 --filter=blob:none -c http.sslCAInfo="{ca}" https://github.com/{O}/{R}.git {WD}', t=900)
        if p.returncode: print(f"blocked hark-vm sync · clone failed · owner action: none"); return 1
    sh(f'git -c http.sslCAInfo="{ca}" fetch -q --depth 1 origin master && git checkout -q -f FETCH_HEAD', WD, 900)
    MASTER = sh("git rev-parse HEAD", WD).stdout.strip()
    refs = {"master": None}
    for pr in api("pulls_list", f"owner={O}", f"repo={R}", "state=open", "per_page=100"):
        if pr["title"].startswith("feat(que)") or any(l["name"] == "que" for l in pr.get("labels", [])):
            refs[f"pr/{pr['number']}"] = pr["number"]
    # drain
    req, _ = get("repo-exports/REQUESTS.jsonl"); done, _ = get("repo-exports/DONE.jsonl")
    done_ids = {json.loads(l)["id"] for l in done.splitlines() if l.strip()}
    pend = [json.loads(l) for l in req.splitlines() if l.strip()]
    pend = [r for r in pend if r.get("target") in ("hark-vm", "any") and r.get("id") not in done_ids]
    pend.sort(key=lambda r: (str(r.get("priority", "T4")), r.get("ts_utc", "")))
    results, extra_tests = [], {}
    for r in pend[:5]:
        k = r.get("kind")
        if k not in ALLOW:
            results.append({"id": r["id"], "ts_utc": NOW(), "node": "hark-vm", "status": "rejected", "receipt": f"kind {k} ∉ allowlist"}); continue
        if k == "probe":
            results.append({"id": r["id"], "ts_utc": NOW(), "node": "hark-vm", "status": "done",
                            "receipt": {"nproc": os.cpu_count(), "mem": sh("free -m | awk '/Mem/{print $2}'").stdout.strip()}}); continue
        if k == "clf-doe":
            left = PASS_BUDGET - (time.time() - T0)
            if left < 90: continue
            st, rc = clf_doe(r, budget=min(left - 60, 600))
            results.append({"id": r["id"], "ts_utc": NOW(), "node": "hark-vm", "status": st, "receipt": rc}); continue
        if k == "eval":
            ref = r.get("ref") or "master"
            tests = [t for t in (r.get("args") or {}).get("tests", SUITES) if t.startswith("tests/") or (t.startswith("scripts/") and "/test_" in t)]
            extra_tests[ref] = (r["id"], tests or SUITES)
            if ref.startswith("pr/"): refs[ref] = int(ref[3:])
            continue
        results.append({"id": r["id"], "ts_utc": NOW(), "node": "hark-vm", "status": "done", "receipt": f"{k} runs in this pass"})
    # eval
    prev = {}
    ev, _ = get("ledger/eval.jsonl")
    for l in ev.splitlines():
        if l.strip(): j = json.loads(l); prev[j["ref"]] = j
    rows = []
    for ref, num in refs.items():
        d = WD
        if num:
            d = f"{WD}-{num}"; shutil.rmtree(d, ignore_errors=True)
            p = sh(f'git -c http.sslCAInfo="{ca}" fetch -q --depth 1 origin pull/{num}/head:pr{num} && git worktree add -q -f {d} pr{num}', WD, 900)
            if p.returncode: continue
        sha = sh("git rev-parse --short HEAD", d).stdout.strip()
        rid, tests = extra_tests.get(ref, (None, SUITES))
        res = pytest(d, tests); row = {"ts_utc": NOW(), "ref": ref, "sha": sha, **res}; rows.append(row)
        if rid: results.append({"id": rid, "ts_utc": NOW(), "node": "hark-vm", "status": "done" if not res["failed"] else "failed", "receipt": f"{sha} {res['passed']}✓ {res['failed']}✗"})
        p0 = prev.get(ref)
        newfail = sorted(set(res["failing"]) - set(p0["failing"])) if p0 else []
        fixed = sorted(set(p0["failing"]) - set(res["failing"])) if p0 else []
        if newfail and p0 and p0.get("sha") == sha: newfail = []
        if newfail: out.append(f"degraded hark-vm eval {ref} · verified receipt {sha} · regression {','.join(newfail)} · owner action: none")
        if fixed: out.append(f"live hark-vm eval {ref} · verified receipt {sha} · fixed {','.join(fixed)} · owner action: none")
        if num: sh(f"git worktree remove -f {d}", WD)
    # shadow jobs: Actions-starved pure-Python lanes, run on master, results ⇒ ledger/jobs.jsonl
    jobs, prevj = [], {}
    jl, _ = get("ledger/jobs.jsonl")
    for l in jl.splitlines():
        if l.strip(): j = json.loads(l); prevj[j["job"]] = j
    sh(f"git checkout -q -f {MASTER}", WD)
    msha = sh("git rev-parse --short HEAD", WD).stdout.strip()
    for name, cmd in SHADOW_JOBS.items():
        pj, g = prevj.get(name), SHADOW_GATE.get(name, {})
        if pj and pj.get("rc") == 0:
            age_h = (time.time() - pj.get("epoch", 0)) / 3600
            changed = bool(g.get("paths")) and sh(f"git diff --quiet {pj['sha']} {msha} -- " + " ".join(g["paths"]), WD).returncode != 0
            if age_h < g.get("max_age_h", 0) and not changed: continue
        t0 = time.time()
        try: p = sh(f"PYTHONPATH={PYLIB} " + cmd, WD, 300); rc = p.returncode; tail = (p.stdout + p.stderr).strip().splitlines()[-1:]
        except subprocess.TimeoutExpired: rc, tail = 124, ["timeout"]
        if rc == 0 and tail and "skipped" in tail[0]: rc = 3  # skip ⇒ ⊬ unproven, ¬ pass
        row = {"ts_utc": NOW(), "epoch": int(time.time()), "job": name, "sha": msha, "rc": rc, "tail": (tail[0][:160] if tail else ""), "duration_s": round(time.time() - t0, 1)}
        jobs.append(row)
        if pj and (pj["rc"] == 0) != (rc == 0):
            out.append(f"{'live' if rc == 0 else 'degraded'} hark-vm shadow {name} · verified receipt {msha} rc={rc} · owner action: none")
    # self-feed: fill remaining pass budget with clf-lab DoE cells, round-robin by hour
    hr = int(time.time() // 3600); clf_rows = []
    for i in range(len(LABS)):
        left = PASS_BUDGET - (time.time() - T0)
        if left < 90: break
        lab = LABS[(hr + i) % len(LABS)]
        st, rc = clf_doe({"args": {"repo": f"{O}/clf-lab-{lab}"}}, budget=min(left - 60, 600))
        clf_rows.append({"ts_utc": NOW(), "job": f"clf-doe:{lab}", "sha": "-", "rc": 0 if st == "done" else 1, "tail": rc[:160], "duration_s": 0})
        if st != "done": out.append(f"degraded hark-vm clf-doe {lab} · {rc} · owner action: none")
        if "left=0" in rc: continue
    jobs += clf_rows
    append("ledger/jobs.jsonl", jobs, "jobs: hark-vm shadow lanes")
    for r in results:
        if r["status"] in ("failed", "rejected"): out.append(f"degraded hark-vm request {r['id']} · {r['status']} · {r['receipt']} · owner action: none")
    c1 = append("ledger/eval.jsonl", rows, "eval: hark-vm node pass")
    c2 = append("repo-exports/DONE.jsonl", results, "done: hark-vm drain")
    c3 = append("ledger/heartbeat.jsonl", [{"ts_utc": NOW(), "node": "hark-vm", "cpu": os.cpu_count(), "status": "live", "drained": len(results), "refs": len(rows)}], "heartbeat: hark-vm")
    shutil.rmtree(WD, ignore_errors=True)
    if out: log(out, f"commits {c1} {c2} {c3}")
    return 0

def log(lines, refs=""):
    """Owner 2026-11-19: GitHub is for the logs ⇒ stamps ⇒ ledger/node-log.jsonl; chat ∅ unless GitHub write ✗."""
    append("ledger/node-log.jsonl", [{"ts_utc": NOW(), "node": "hark-vm", "line": l, "refs": refs} for l in lines], "log: hark-vm node pass")

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        line = f"blocked hark-vm node pass · {type(e).__name__}: {str(e)[:200]} · owner action: none"
        try: log([line]); sys.exit(0)
        except Exception as e2: print(line + f" · log write ✗ {type(e2).__name__}"); sys.exit(1)
