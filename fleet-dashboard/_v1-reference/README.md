# v1 reference — port from these

These are the **v1 fleet collector** files, vendored here so a cloud/Claude Code
session has them in-repo (the original lives in a local-only `improve_ai_dev`
clone with no remote — unreachable from the cloud).

- `collector.py` — v1 collector. **Port from this** per `../BUILD-SPEC.md` Leaf 1:
  KEEP the git/PR/flag engine (squash-merge-aware `is_merged`, `gh_pr`,
  dirty/ahead/behind, worktree parse, naming-based pairing, self-contained
  inlined HTML). STRIP `collect_initiatives()` (the workbench-folder reader —
  replaced by the two-level `collect_kanban()` in Leaf 2).
- `template.html` — v1 render reference.

These are a snapshot for reference, not the live tool. The v2 build lives one
level up in `fleet-dashboard/`.
