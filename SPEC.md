# Media Server Specification

## Purpose

Run a small, understandable media server for a single trusted household. The application supports manual torrent discovery, download monitoring, library management, media inspection/conversion, and Jellyfin refreshes through two clients: a web dashboard and a Telegram bot.

The design intentionally avoids an *arr stack, databases, provider frameworks, internal microservice APIs, and automatic content selection.

## Design principles

1. **One monolithic application process.** FastAPI serves the dashboard while aiogram Telegram polling runs as a background task in the same asyncio event loop.
2. **Two thin clients, one set of capabilities.** Dashboard routes and Telegram handlers call the same Python service functions directly.
3. **Capability-named boundaries.** Public modules describe what the application does, not which product currently implements it.
4. **Concrete defaults over speculative abstraction.** RuTracker, Transmission, and Jellyfin are implemented directly behind stable module functions. Do not add protocols, dependency-injection containers, provider registries, or factories until a real second implementation requires them.
5. **Manual first.** Operations that mutate files or start conversion require an explicit user action.
6. **Single-user simplicity.** In-memory interaction and conversion state is acceptable. No database or distributed job queue is required.

## Vocabulary

- **Torrent indexer:** searches a torrent catalogue and retrieves torrent metadata/files. The current implementation is RuTracker.
- **Download client:** adds and manages downloads. The current implementation is Transmission.
- **Media server:** indexes and serves the organized media library. The current implementation is Jellyfin.
- **Library:** the local Downloads, Movies, and Shows filesystem areas.
- **Client:** a user interaction layer. The clients are the dashboard and Telegram bot; neither owns domain operations.

A BitTorrent tracker technically coordinates peers and is not necessarily a searchable catalogue. Therefore the searchable capability is called a **torrent indexer**, not a tracker service.

## Target user capabilities

### Torrent discovery

- Search RuTracker from either client using a title.
- Fetch at most two result pages.
- Exclude results over 30 GiB and obvious high-end formats such as 2160p, 4K, UHD, HDR, and Dolby Vision.
- Prefer well-seeded 1080p/HD releases.
- Present title, size, seeders, and leechers.
- Require explicit confirmation before adding a torrent.
- Let Transmission report exact duplicates; do not maintain a separate request database.

### Download monitoring

Both clients can list Transmission downloads with:

- name and status;
- downloaded and total bytes;
- percentage complete;
- remaining bytes;
- current download rate;
- approximate ETA when Transmission provides one, with `remaining / rate` as a possible fallback.

Unknown or unavailable ETAs must be displayed as unknown rather than as misleading values.

### Library management

Both clients can:

- browse files and directories in Downloads, Movies, and Shows;
- move or rename files and directories between supported library areas;
- reject path traversal and destination collisions;
- inspect media audio tracks and clearly identify DTS.

The first safe workflow should remain moving completed content from Downloads to Movies or Shows. Moving content belonging to an active torrent behind Transmission's back can break the download and must be rejected or deferred until a Transmission-aware move is deliberately implemented.

All client selections use a library area plus a relative path. Arbitrary absolute paths are not accepted at the service boundary.

### Audio conversion

- Inspect streams with `ffprobe`.
- Convert explicitly selected DTS tracks to AC3 while copying video and other streams.
- Write to a temporary sibling file and replace the original only after successful `ffmpeg` completion.
- Keep the original and remove incomplete output after failure or interruption.
- Allow only one conversion at a time.

Because dashboard and bot run in one process, they share conversion state. This depends on the application remaining a single Uvicorn worker.

### Jellyfin refresh

Both clients can explicitly request a Jellyfin library refresh. A successful request means Jellyfin accepted the scan request, not that scanning has completed.

A failed refresh must not undo a successful filesystem move. Automatic refresh after a move may be added after the manual action is reliable.

## Architecture

```text
                       one media application process
                +---------------------------------------+
                | FastAPI dashboard    Telegram polling |
                |          \              /             |
                |           Python service functions    |
                +-------------+-----------+-------------+
                              |           |
                  local media filesystem  external applications
                                           |- RuTracker
                                           |- Transmission
                                           `- Jellyfin
```

There is no internal HTTP API between the bot and dashboard. Dashboard `/api/...` routes are web controllers used by its HTML/HTMX client; Telegram does not call them.

### Target layout

```text
src/
├── app/
│   └── main.py                 # Composition root and process lifecycle
├── dashboard/
│   ├── routes.py               # HTTP/HTML input and presentation only
│   └── templates/
├── bot/
│   └── handlers.py             # Telegram input and presentation only
└── services/
    ├── torrent_indexer.py      # RuTracker-backed search and fetch
    ├── download_client.py      # Transmission-backed add/status operations
    ├── media_server.py         # Jellyfin-backed refresh operation
    ├── library.py              # Safe filesystem browsing/moves
    └── media.py                # ffprobe/ffmpeg inspection and conversion
```

Product-specific private helpers may live inside their capability modules, for example `_TransmissionRpcClient`. Separate `integrations/`, interface, and provider packages should only be introduced when their additional structure solves a real need.

### Public service style

Prefer small functions and provider-neutral data models:

```python
search_torrents(query)
fetch_torrent(reference)
add_download(payload)
list_downloads()
list_library_items(area, path="")
move_library_item(source, destination)
get_audio_tracks(item)
convert_audio(item, track_indices)
refresh_libraries()
```

Dashboard and bot import these functions. They should not construct or receive dependency graphs. Public errors and result models use capability terms such as `TorrentIndexerError`, `DownloadClientError`, and `MediaServerError`; provider details belong in logs.

If a second implementation is actually introduced, preserve these public calls and select or combine implementations internally. Do not build that selection mechanism in advance.

## Process lifecycle

FastAPI is the primary process entry point. Its lifespan starts aiogram polling as a background task and stops it cleanly during shutdown.

Requirements:

- run exactly one Uvicorn worker;
- do not use production reload mode, which can start duplicate bot pollers;
- Telegram startup/polling failures should be logged and should not unnecessarily terminate the dashboard;
- blocking `requests`, filesystem scans, and `ffprobe` operations must use `asyncio.to_thread` or otherwise avoid blocking the shared event loop;
- long-running conversion uses an async subprocess.

## Telegram behavior

### Access control

- Only IDs in `ALLOWED_USER_IDS` may use the bot.
- The deployed allowlist must not be empty.

### Interactions

- Plain text continues to search the torrent indexer.
- `/downloads` lists active and recent download status with refresh controls.
- `/library` browses Downloads, Movies, and Shows and offers valid actions for the selected item.
- Codec inspection shows all audio tracks and marks DTS tracks.
- `/refresh` requests a Jellyfin library refresh.
- Destructive or mutating actions such as move, rename, and conversion require confirmation.

Telegram callback data has a small size limit. Store short-lived selection tokens in process memory instead of embedding full paths or result objects in callback payloads.

Up to ten recent torrent searches per user may remain valid until selected, cancelled, evicted, or the process restarts.

### Errors

Return concise user-facing errors without tracebacks and log full details. Never report a torrent as added, a file as moved, a conversion as completed, or a refresh as requested before the underlying operation succeeds.

## Deployment

Active Compose services in the target deployment:

- `transmission`
- `jellyfin`
- `media-app`

`media-app` replaces the separate `dashboard` and `telegram-bot` containers. It:

- exposes the dashboard port;
- receives application configuration from `.env`;
- mounts `/media/usb:/data`;
- reaches Transmission and Jellyfin by their Compose service names;
- runs FastAPI and Telegram polling in one process.

## Configuration

Required or feature-specific environment variables:

```dotenv
TELEGRAM_BOT_TOKEN=
ALLOWED_USER_IDS=
RUTRACKER_USERNAME=
RUTRACKER_PASSWORD=
USER_NAME=
USER_PASS=
TRANSMISSION_RPC_URL=http://transmission:9091/transmission/rpc
JELLYFIN_URL=http://jellyfin:8096
JELLYFIN_API_KEY=
```

`JELLYFIN_API_KEY` is created from Jellyfin's administrative API Keys screen. Secrets remain only in ignored `.env` files and must never be committed.

Do not add provider selectors such as `DOWNLOAD_CLIENT=transmission` or `MEDIA_SERVER=jellyfin` until an alternative implementation exists.

## Out of scope

- Automatic torrent selection or unattended downloading.
- RSS/watchlist synchronization.
- Radarr, Sonarr, Prowlarr, or similar automation stacks.
- Persistent search, command, or conversion history.
- Multiple application workers or replicas.
- Internal HTTP communication between the two clients.
- A generic plugin or dependency-injection framework.
- Moving active torrent content without coordinating with the download client.

## Acceptance criteria for the next architecture increment

- Compose starts Transmission, Jellyfin, and one media application container.
- Dashboard and Telegram polling run concurrently in one application process.
- Existing authorized Telegram search/add and dashboard workflows continue working.
- Dashboard and bot call shared capability modules directly.
- Both clients can display normalized download progress and ETA.
- Both clients can browse library areas and move completed content safely.
- Both clients can inspect audio codecs and identify DTS.
- Both clients can request a Jellyfin refresh.
- Conversion remains safe and only one conversion can run at a time.
