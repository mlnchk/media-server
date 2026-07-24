# Media Application Roadmap

The target behavior and architecture are defined in [`SPEC.md`](SPEC.md). Implement this roadmap incrementally; each phase should leave the existing workflows usable.

## Current baseline

- [x] Dashboard file browser and Downloads-to-Movies/Shows moves
- [x] Dashboard DTS inspection and manual DTS-to-AC3 conversion
- [x] RuTracker search and Transmission add from dashboard
- [x] Authorized Telegram search, selection, cancel, and Transmission add
- [x] Initial shared media, torrent, and Transmission Python modules

## Phase 1: Simplify the runtime

- [x] Replace the dashboard and Telegram containers with one `media-app` service
- [x] Start aiogram polling from the FastAPI lifespan
- [x] Guarantee a single Uvicorn worker and clean bot shutdown
- [x] Keep Telegram failures from unnecessarily stopping the dashboard
- [x] Move blocking calls off the shared asyncio event loop

## Phase 2: Cement capability boundaries

- [x] Rename/split current modules into `torrent_indexer.py` and `download_client.py`
- [x] Keep RuTracker and Transmission as direct default implementations; add no DI framework
- [x] Extract path validation, listing, rename, and move logic into `services/library.py`
- [x] Add `services/media_server.py` with direct Jellyfin refresh support
- [x] Use provider-neutral result models and errors at client boundaries

## Phase 3: Download visibility

- [x] Normalize Transmission status, downloaded bytes, total bytes, remaining bytes, rate, and ETA
- [x] Add download status to the dashboard
- [x] Add Telegram `/downloads` with refresh controls
- [x] Handle stopped, completed, and unknown-ETA states clearly

## Phase 4: Shared library interaction

- [x] Browse Downloads, Movies, and Shows through the shared library service
- [x] Add Telegram `/library` navigation with short-lived callback tokens
- [x] Support safe file and directory moves with confirmation
- [x] Prevent path traversal and destination overwrites
- [x] Prevent unsafe moves of active torrent content
- [x] Make the existing dashboard routes use the same operations

## Phase 5: Media and Jellyfin controls

- [x] Show audio codecs and DTS status for a selected item in Telegram
- [x] Add manual Jellyfin refresh to dashboard and Telegram
- [x] Report partial success when a move succeeds but refresh fails
- [x] Consider optional automatic Jellyfin refresh after successful moves (kept manual)
- [x] Expose manual conversion through Telegram using the shared single-process conversion state

## Later, only when justified

- [ ] Pause/resume/remove download controls
- [ ] Transmission-aware relocation of active torrent data
- [ ] Conversion queue and batch operations
- [ ] Directory search/filter and richer rename assistance
- [ ] Subtitle management
- [ ] Disk space indicator
- [ ] A second indexer or download client implementation

Do not introduce a database, internal bot-to-dashboard HTTP API, provider registry, abstract interface hierarchy, or dependency-injection container unless a concrete future requirement demonstrates the need.
