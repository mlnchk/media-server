# Media Server Project Guide

## Authoritative documents

- [`SPEC.md`](SPEC.md) defines the agreed product scope, vocabulary, architecture, safety constraints, and target deployment.
- [`ROADMAP.md`](ROADMAP.md) defines the incremental implementation order.
- Git commit `978a90e` is the current working baseline for the Telegram torrent workflow and initial shared services.

Read those artifacts before changing application architecture. Do not duplicate their content here.

## Project priorities

- Optimize for a small, single-user Raspberry Pi 5 deployment.
- Prefer direct, understandable code over infrastructure and speculative abstractions.
- Preserve manual control over downloads, file moves, and conversion.
- Keep dashboard routes and Telegram handlers as separate interaction layers over shared Python capability modules.
- Maintain safe DTS-to-AC3 replacement semantics and filesystem path validation.

## Development rules

- Secrets belong only in ignored `.env` files. Never commit credentials, tokens, API keys, or personal identifiers.
- Runtime data under `application-data/` is not application source and should not be inspected or committed unless a task explicitly requires configuration diagnosis.
- Application code lives under `src/`; `scripts/` is for operational hooks and CLI entry points.
- Keep the target monolith to one Uvicorn worker so Telegram polling and conversion state are not duplicated.
- Move blocking network, filesystem scan, and `ffprobe` work off the shared asyncio event loop.
- Do not add dependency-injection frameworks, provider registries, databases, queues, or internal HTTP communication without an explicit requirement.
- Update `SPEC.md` and `ROADMAP.md` when an architectural decision or scope changes.

## Validation

For code changes, run the smallest relevant checks plus a Compose configuration/build check when deployment files change. Manually verify that existing dashboard and authorized Telegram torrent workflows remain intact during the monolith migration.
