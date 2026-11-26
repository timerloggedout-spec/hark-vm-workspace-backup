#!/bin/bash
# hark-vm self-heal launcher: heal_run.sh <script.py> [args]  (auto-FIX pipeline, owner 2026-11-26)
# ① wait for JuiceFS /workspace mount (6×20s) ② file missing ∧ mount present ⇒ restore from hark-vm-workspace-backup tools/hark-vm-node/ ③ exec
S="$1"; shift; D=/workspace/hark-vm-node
for i in 1 2 3 4 5 6; do [ -d /workspace/work ] && [ -d /workspace/memory ] && break; sleep 20; done
if [ ! -d /workspace/work ]; then echo "HEAL mount-absent /workspace after 120s"; exit 75; fi
if [ ! -f "$D/$S" ]; then
  mkdir -p "$D"
  apicall github contents_get owner=timerloggedout-spec repo=hark-vm-workspace-backup path=tools/hark-vm-node/$S \
   | python3 -c 'import sys,json,base64;sys.stdout.write(base64.b64decode(json.load(sys.stdin)["content"]).decode())' > "$D/$S.tmp" && mv "$D/$S.tmp" "$D/$S" \
   && echo "HEAL restored $S from store" >&2 || { echo "HEAL restore-failed $S"; exit 75; }
fi
# watchdog: fly-hark-runner liveness (continuous leg) ⇒ re-arm when ∄ in_progress ∨ queued
if [ "$S" = "fly_watch.py" ]; then
  N=$(for st in in_progress queued; do curl -s "https://api.github.com/repos/timerloggedout-spec/termux-monorepo/actions/workflows/fly-hark-runner.yml/runs?status=$st&per_page=1" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("total_count",0))' 2>/dev/null || echo 1; done | python3 -c "import sys;print(sum(int(x) for x in sys.stdin.read().split()))")
  if [ "${N:-1}" = "0" ]; then apicall github workflow_dispatch owner=timerloggedout-spec repo=termux-monorepo workflow_id=fly-hark-runner.yml ref=master >/dev/null 2>&1 && echo "WATCHDOG re-armed fly-hark-runner" >&2; fi
fi
# heartbeat: node pass ⇒ store hark/heartbeat.json (muse watcher alarms when stale >2h)
if [ "$S" = "node_pass.py" ]; then
  cd /tmp && python3 "$D/$S" "$@"; RC=$?
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ); B64=$(printf '{"peer":"hark-vm","ts":"%s","node_pass_rc":%s}\n' "$TS" "$RC" | base64 -w0)
  SHA=$(apicall github contents_get owner=timerloggedout-spec repo=muse-vm-workspace-backup path=hark/heartbeat.json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sha",""))' 2>/dev/null)
  apicall github contents_put owner=timerloggedout-spec repo=muse-vm-workspace-backup path=hark/heartbeat.json message="chore(hark): heartbeat [skip render]" content="$B64" ${SHA:+sha=$SHA} >/dev/null 2>&1
  exit $RC
fi
cd /tmp && exec python3 "$D/$S" "$@"
