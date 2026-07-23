# Media Server Specification

## Purpose

Run a small, self-hosted media server with a manual Telegram workflow for finding and downloading movies. The system must remain understandable and low-maintenance: Docker Compose manages the services; there is no *arr stack, indexer service, watchlist sync, RSS polling, or automatic movie selection.

## User workflow

1. The user sends a movie title to the Telegram bot.
2. The bot searches RuTracker.
3. The bot shows up to three eligible results with title, size, seeders, and leechers.
4. The user presses a **Download** button or **Cancel**.
5. For a download choice, the bot downloads the `.torrent` from RuTracker and adds it directly to Transmission.
6. The bot confirms whether Transmission added it or identified it as an exact duplicate.
7. Transmission downloads to the existing downloads directory. The existing manual dashboard workflow is used to inspect, convert DTS audio when needed, and move media to the Jellyfin library.

There is deliberately no persistent “already requested/downloaded” list. A user can search or request the same film again; Transmission will report an exact torrent duplicate when applicable.

## Scope

### In scope

- Telegram bot for manual title/link search and explicit download confirmation.
- RuTracker as the only tracker.
- Transmission as the only download client.
- Existing dashboard retained as a browser UI for media management and torrent searching.
- Shared Python service code used directly by dashboard and bot.
- Manual DTS detection and DTS-to-AC3 conversion.
- Repository cleanup and a root-level Python application layout.

### Out of scope

- Letterboxd RSS, list synchronization, profile authorization, or polling.
- Automatic search, selection, download, conversion, library moves, or deletion.
- Radarr, Sonarr, Prowlarr, Homepage, Home Assistant, Glances, queues, and databases.
- Additional torrent trackers.
- An internal HTTP API between the bot and dashboard.
- A Claude/dashboard integration. The service boundary should make one possible later, but no interface is built now.

## Repository layout

```text
media-server/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── src/
│   ├── services/
│   │   ├── torrents.py
│   │   ├── transmission.py
│   │   └── media.py
│   ├── dashboard/
│   │   ├── main.py
│   │   ├── routes.py
│   │   └── templates/
│   └── bot/
│       ├── main.py
│       └── handlers.py
├── scripts/
│   ├── check-and-notify.py
│   └── convert-audio.py
├── application-data/             # ignored runtime configuration/state
├── .env                          # ignored secrets
└── .env.example
```

`scripts/` is reserved for operational entry points such as Transmission hooks or manual CLI commands. Application code must live under `src/` and must not depend on a script implementation.

## Architecture

### Shared services

`services/torrents.py` owns the torrent workflow:

- log in to RuTracker using credentials from environment variables;
- search and download `.torrent` files;
- normalize results;
- apply eligibility filtering and ranking;
- add a selected torrent through `TransmissionClient`.

`services/transmission.py` is a narrow Transmission RPC adapter. It handles RPC session negotiation and adds torrent metainfo. It has no Telegram, FastAPI, or RuTracker knowledge.

`services/media.py` owns reusable media operations:

- enumerate video files;
- inspect audio tracks with `ffprobe`;
- detect DTS tracks;
- convert selected DTS tracks to AC3 while copying video and subtitles.

### Interfaces

`dashboard/` is a FastAPI/HTML interface. `bot/` is an aiogram Telegram interface. They import the service functions directly and only handle input validation, presentation, and user interaction.

No service calls another container over HTTP. Both application containers are built from the same source image and differ only by their Compose command.

## Telegram bot requirements

### Access control

- Only Telegram IDs listed in `ALLOWED_USER_IDS` may use the bot.
- An empty allowlist is not permitted in the deployed configuration.

### Input

- Plain movie title: search that text.
- URLs and empty text return a concise error.

### Search result policy

- Fetch up to two RuTracker result pages.
- Exclude files over 30 GiB.
- Exclude titles containing obvious high-end formats: `2160p`, `4K`, `UHD`, `HDR`, `Dolby Vision` / `DV`.
- Prefer 1080p/HD releases when otherwise comparable.
- Rank primarily by seeders; use size preference only as a tie-breaker or small adjustment.
- Return at most three results.
- Show result title, size in GiB, seeders, and leechers, plus Download buttons and Cancel.
- Do not claim that audio/subtitles are guaranteed: tracker titles are not reliable structured metadata.

### Selection lifecycle

- Pending choices are stored only in bot process memory.
- Each result message has a unique token, so its buttons always refer to that message's results.
- Up to ten recent searches per user remain valid until selected, cancelled, evicted by newer searches, or the bot restarts.
- Downloading fetches the selected `.torrent` from RuTracker, sends it to Transmission, then reports its name and whether it was already present.
- Cancel clears the pending choice.

### Errors

- Report no eligible results without exposing a traceback.
- Report RuTracker login/CAPTCHA failures with an actionable message.
- Report Transmission failures without falsely confirming a queued download.
- Log complete errors in container logs.

## Media/DTS requirements

- DTS conversion remains manual; neither the bot nor Transmission starts conversion.
- The dashboard may scan downloads, movies, and shows for DTS audio.
- Conversion writes a temporary sibling output file.
- Only after successful ffmpeg completion may it replace the original file.
- Replacement retains the original file path/name, so library structure does not change.
- Failed or interrupted conversion keeps the original and removes incomplete output.

The existing post-download notification script may remain available, but it is not required for the Telegram torrent bot and must be explicitly enabled in Transmission before it is considered active.

## Docker Compose requirements

Active services:

- `transmission`
- `jellyfin`
- `dashboard`
- `telegram-bot`

The dashboard and bot build from the root `Dockerfile`. Both receive the necessary environment through `.env`; only the dashboard exposes a browser port. The bot exposes no port.

Remove inactive/obsolete Compose configuration and files for Glances, Prowlarr, Radarr, Sonarr, Homepage, and Home Assistant.

## Configuration

Required `.env` values:

```dotenv
TELEGRAM_BOT_TOKEN=
ALLOWED_USER_IDS=
RUTRACKER_USERNAME=
RUTRACKER_PASSWORD=
USER_NAME=
USER_PASS=
TRANSMISSION_RPC_URL=http://transmission:9091/transmission/rpc
```

Existing Telegram notification values may remain if the post-download script is retained:

```dotenv
TELEGRAM_CHAT_ID=
```

Secrets are stored only in ignored `.env`, never in source or Compose. RuTracker uses username/password login; manually captured session cookies are not part of this design.

## Implementation plan

1. Clean Compose and remove obsolete files/configuration.
2. Move the root Python project from `app/` to the root and migrate reusable code into `src/services/`.
3. Update the dashboard imports and retain its existing file, move, conversion, and torrent-search views.
4. Add `aiogram` and implement the Telegram bot as a second interface.
5. Add the `telegram-bot` Compose service and update `.env.example`.
6. Build containers and manually test search, cancel, add, duplicate handling, and dashboard conversion.

## Acceptance criteria

- `docker compose up -d --build` starts Transmission, Jellyfin, dashboard, and Telegram bot successfully.
- An authorized user can send a movie title, select one of up to three eligible results, and see it in Transmission.
- An unauthorized Telegram user cannot search or add torrents.
- A result larger than 30 GiB or marked 4K/HDR is not offered.
- Cancel does not add anything to Transmission.
- The dashboard continues to browse, move, inspect, and manually convert media.
- No active Compose configuration or repository files remain for removed services.
