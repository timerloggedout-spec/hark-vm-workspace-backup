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
cd /tmp && exec python3 "$D/$S" "$@"
