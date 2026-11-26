#!/usr/bin/env python3
"""hark-vm flywheel reader gate v2 (parity with muse-vm learnings 2026-11-26).
Registry-driven: every established JSONL channel in REGISTRY.json. WAKE classes:
 ① any line to hark-vm ∨ all ∨ mentioning hark-vm  ② every peer line on pair channel FLY-010
 ③ unknown sender (∉ registry peers)  ④ registry peer-set/channel hash change  ⑤ new store/channel path.
exit 0 silent · exit 2 + wake lines · exit 1 read failure. --ack clears pending."""
import json,base64,subprocess,sys,os,re,hashlib
D="/workspace/hark-vm-node"; STATE=f"{D}/.fly_watch_state.json"
O="timerloggedout-spec"; STORE="muse-vm-workspace-backup"; MONO="termux-monorepo"
REG="docs/ops/flywheel-comms/REGISTRY.json"
def api(*a):
    r=subprocess.run(["apicall","github",*a],capture_output=True,text=True)
    return json.loads(r.stdout or "{}")
def get(repo,p):
    d=api("contents_get",f"owner={O}",f"repo={repo}",f"path={p}")
    if "sha" not in d: return None
    c=d.get("content") or api("git_blob_get",f"owner={O}",f"repo={repo}",f"file_sha={d['sha']}").get("content","")
    return base64.b64decode(c).decode(errors="replace")
st=json.load(open(STATE)) if os.path.exists(STATE) else {}
if sys.argv[1:2]==["--ack"]:
    st["pending"]=[]; json.dump(st,open(STATE,"w")); sys.exit(0)
raw=get(MONO,REG)
if raw is None: print("registry read fail"); sys.exit(1)
reg=json.loads(raw); chans=reg.get("channels",[])
peers=set()
for k in ("peers","seats"):
    v=reg.get(k)
    if isinstance(v,list): peers|={(p.get("id") or p.get("name") or "") for p in v if isinstance(p,dict)}
    if isinstance(v,dict): peers|=set(v)
for c in chans: peers|=set(c.get("participants") or [])
peers|={"muse-vm","manus-cue","cue","hark-vm","chatgpt","chatgpt-github","mistralai"}
new=[]
h=hashlib.sha256(json.dumps([(c.get("id"),c.get("status"),c.get("participants")) for c in chans]+[sorted(peers)],sort_keys=True).encode()).hexdigest()[:12]
if st.get("reg_hash") and st["reg_hash"]!=h: new.append(f"REGISTRY Δ hash {st['reg_hash']}⇒{h}")
st["reg_hash"]=h
src=[]
for c in chans:
    if c.get("status") not in ("established","proposed"): continue
    txt=(c.get("store") or "")+" "+(c.get("path") or "")
    m=re.search(r"([\w./-]+\.jsonl)",txt)
    if not m or "~/" in txt.split(m.group(1))[0][-3:]: continue
    p=m.group(1)
    if p.startswith("/"): continue
    repo=MONO if p.startswith(("docs/","ops/")) else STORE
    if c["id"]=="FLY-003": continue  # high-volume relay feed; confirmations only
    src.append((c["id"],repo,p))
known=set(st.get("paths",[]))
for cid,repo,p in src:
    key=f"{repo}:{p}"
    if known and key not in known: new.append(f"NEW CHANNEL {cid} {key}")
    t=get(repo,p)
    if t is None: continue
    L=t.splitlines(); seen=st.get(key,len(L) if key not in st and cid!="FLY-010" else 0)
    for i in range(seen,len(L)):
        try: o=json.loads(L[i])
        except Exception: continue
        fr=o.get("from") or o.get("actor") or ""; to=o.get("to") or ""
        if fr=="hark-vm": continue
        body=json.dumps(o,ensure_ascii=False)
        why=("to-hark" if to in ("hark-vm","all","*") else "pair" if cid=="FLY-010" else
             "unknown-sender" if fr and fr not in peers else "mention" if "hark" in body.lower() else None)
        if why: new.append(f"{cid} {p}#{i+1} [{why}] {L[i][:1500]}")
    st[key]=len(L)
st["paths"]=[f"{r}:{p}" for _,r,p in src]
pending=st.get("pending",[])+new; st["pending"]=pending
json.dump(st,open(STATE,"w"))
if not pending: sys.exit(0)
print("\n".join(pending)); sys.exit(2)
