# Handoff

## Status

This session finalized the target architecture and vocabulary but intentionally made no application-code or Compose changes.

The agreed design is now recorded in:

- [`SPEC.md`](SPEC.md) — authoritative architecture, terminology, feature behavior, deployment target, and acceptance criteria.
- [`ROADMAP.md`](ROADMAP.md) — incremental implementation sequence.
- [`CLAUDE.md`](CLAUDE.md) — concise repository guidance that points agents to the authoritative documents.

The implementation baseline remains commit `978a90e` (`Implement Telegram torrent workflow and shared media services`). Consult that commit and the current diff rather than reproducing its details here.

## Important implementation gap

The repository code still reflects the pre-decision structure: dashboard and Telegram run as separate Compose services, shared filesystem operations remain partly in dashboard routes, current service module names are provider/workflow-specific, and Jellyfin refresh/download-status/library bot features are not implemented. The documentation describes the intended destination, not the current runtime.

## Recommended next session

Start with **Phase 1** in [`ROADMAP.md`](ROADMAP.md): migrate dashboard and Telegram polling into one `media-app` process while preserving existing behavior. Keep this migration narrow before renaming or extracting service modules.

Before implementation, inspect:

- [`docker-compose.yml`](docker-compose.yml)
- [`src/dashboard/main.py`](src/dashboard/main.py)
- [`src/bot/main.py`](src/bot/main.py)
- [`src/bot/handlers.py`](src/bot/handlers.py)
- [`src/dashboard/routes.py`](src/dashboard/routes.py)
- [`src/services/`](src/services/)

Pay particular attention to graceful aiogram startup/shutdown, single-worker execution, and blocking synchronous calls on the shared event loop. Follow the constraints and acceptance criteria in `SPEC.md`; do not introduce an internal HTTP API or dependency-injection framework.

## Working tree

Documentation files are modified/added and should be reviewed before committing. Run `git diff --check` and inspect `git diff -- SPEC.md ROADMAP.md CLAUDE.md HANDOFF.md`.

No secrets or personal values were added to these documents.
