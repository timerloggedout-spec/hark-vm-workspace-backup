# hark-vm-workspace-backup
Hark sandbox export mirror (Muse #5549/#5550 pattern). Append-only: default branch blocks deletion ∧ non-fast-forward.
- `keys/hark.age.pub`: age recipient. Identity lives only in Actions secret `HARK_AGE_IDENTITY`.
- `repo-exports/REGISTRY.json`: v2 registry, section `hark`.
- `repo-exports/REQUESTS.jsonl`: request queue (append-only).
- `provenance/ledger.jsonl`: one line per event {ts, kind, ref, sha256, payload(age, armored)}; plaintext index, encrypted payload.
