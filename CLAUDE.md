# Media Server Project Summary

## Project Overview

Simple, reliable Jellyfin media server for Raspberry Pi 5 with automatic DTS audio detection and manual conversion workflow. Optimized for ~3-4 movies/week viewing pattern with "watch and forget" philosophy.

---

## Current Stack (Phase 1 - COMPLETED)

### Docker Containers
- **Jellyfin** - Media server (port 8096)
- **Transmission** - Torrent client (port 9091)
- **Dashboard** - Web UI for file management & conversion (port 8080)

### Scripts
- **`check_and_notify.py`** - Post-download DTS detection → Telegram notification
- **`convert.py`** - Interactive DTS→AC3 conversion with track selection

### Workflow
1. Manual torrent search (RuTracker, 1337x)
2. Add magnet link to Transmission web UI
3. Download completes → `check_and_notify.py` runs automatically
4. Telegram notification shows if DTS detected
5. Open Dashboard → move to library, convert if DTS detected
6. Watch in Jellyfin (via LG WebOS or future Xiaomi TV Stick)

---

## Technical Details

### Problem Solved
LG WebOS Jellyfin client doesn't support DTS audio → triggers transcoding → Raspberry Pi 5 too weak for realtime transcode → stuttering/freezing

### Solution
Offline audio conversion (DTS→AC3 @ 640kbps) after download completes, before watching. Raspberry Pi handles offline conversion fine (~1 min per 1.5GB).

### Key Design Decisions
- **Manual over automatic** - 3-4 movies/week doesn't justify complex automation
- **Notification-driven** - Alert user to DTS, they convert before watching
- **Interactive conversion** - User chooses which audio tracks to convert
- **Simple stack** - 3 containers vs previous 5 (Radarr/Sonarr/Prowlarr removed)

---

## File Structure

```
media-server/
├── docker-compose.yml
├── .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
├── scripts/
│   ├── check_and_notify.py     # Post-download DTS detection
│   ├── convert.py              # CLI conversion (legacy)
│   └── telegram_bot.py         # Phase 2-4
└── app/                        # Dashboard web app
    ├── Dockerfile
    ├── pyproject.toml
    └── src/dashboard/
        ├── main.py             # FastAPI entry
        ├── config.py           # Paths config
        ├── routes.py           # API endpoints
        ├── media.py            # ffprobe/ffmpeg logic
        └── templates/          # Jinja2 + HTMX
```

---

## Configuration

### Transmission Post-Download Hook
**Location:** `application-data/transmission/settings.json`
```json
{
    "script-torrent-done-enabled": true,
    "script-torrent-done-filename": "/scripts/check_and_notify.py"
}
```

### Environment Variables
**Location:** `.env`
```
TELEGRAM_BOT_TOKEN=<bot_token_from_@BotFather>
TELEGRAM_CHAT_ID=<your_chat_id>
```

**Loaded via:** `env_file` in docker-compose.yml

### Dashboard Configuration
**Location:** `app/src/dashboard/config.py`
```python
DOWNLOADS_DIR = Path("/data/downloads")
MOVIES_DIR = Path("/data/movies")
SHOWS_DIR = Path("/data/shows")
AUDIO_BITRATE = "640k"
```

---

## Dashboard

Mobile-friendly web UI for media management. Stack: FastAPI + HTMX + Tailwind CSS.

### Features
- **File Browser** - List downloads, show size/type
- **Move to Library** - Move files to movies/shows with optional rename
- **Audio Conversion** - Scan downloads/movies/shows for DTS, convert to AC3

### Endpoints
```
GET  /                    # File browser
GET  /convert             # Conversion UI
POST /api/move            # Move file to library
POST /api/convert         # Start DTS→AC3 conversion
GET  /api/convert/status  # Conversion progress
```

### Access
- URL: `http://<pi-ip>:8080`
- No auth (home network trusted)

---

## Next Steps (Prioritized)

### Phase 2: Telegram Bot - Add Torrents Remotely
**Goal:** Send magnet links via Telegram instead of opening Transmission web UI

**Implementation:**
- Enable `telegram_bot.py` in docker-compose
- Bot listens for messages starting with `magnet:?`
- Calls `transmission-remote` to add download
- Responds with confirmation

**Effort:** 1-2 hours
**Value:** Medium (convenience, especially on mobile)

---

### Phase 3: Telegram Bot - Search Torrents
**Goal:** Search RuTracker directly from Telegram

**Implementation:**
- Add RuTracker scraping to bot
- `/search <query>` command
- Returns top 5-10 results with inline buttons
- Click button → adds magnet to Transmission

**Effort:** 3-4 hours (scraping logic + parsing)
**Value:** High (no browser needed)

**Challenges:**
- RuTracker requires authentication (cookies)
- Captcha handling
- Parsing HTML (BeautifulSoup)

**Alternative:** Use existing RuTracker API wrappers if available

---

### Phase 4: Telegram Bot - Remote Conversion
**Goal:** Trigger conversion from Telegram

**Implementation:**
- `/convert` command shows files with DTS
- Inline keyboard to select file
- Bot runs `convert.py` in background
- Progress updates via Telegram
- Notification when complete

**Effort:** 2-3 hours
**Value:** Medium (nice-to-have, not critical)

---

### Future Considerations (Lower Priority)

#### Hardware Upgrade
**Option A: Xiaomi TV Stick 4K (~$40)**
- Solves DTS natively (hardware decode)
- No conversion needed ever
- Jellyfin Android TV app works great
- **This might make the entire conversion workflow obsolete**

**Option B: Orange Pi or Intel N100 Mini PC**
- More power for potential 4K transcoding
- Only if current setup becomes insufficient

#### Software Enhancements
- **Auto-move to Jellyfin library** after conversion
- **Jellyfin library scan trigger** after file changes
- **Storage cleanup** - auto-delete watched content
- **Quality profiles** - preferred release groups, resolution
- **Subtitle handling** - auto-download via OpenSubtitles

#### Monitoring
- **Grafana dashboard** - container stats, disk usage
- **Health checks** - alert if services down
- **Conversion queue** - track pending conversions

---

## Known Limitations & Tradeoffs

### What We Sacrificed
- ❌ No automatic episode tracking (Sonarr)
- ❌ No automatic quality upgrades (Radarr)
- ❌ No RSS monitoring for new releases
- ❌ No web-based torrent search (qBittorrent/Jackett rejected)

### Why It's Worth It
- ✅ 90% less complexity
- ✅ Nothing runs in background (except notifications)
- ✅ Easy to understand and debug
- ✅ Minimal maintenance
- ✅ User stays in control

### Current Pain Points
1. **Manual torrent search** - Mobile web browser on torrent sites isn't ideal
2. **Remembering to convert** - notification helps but still manual step
3. **Track selection** - need to know which language/codec wanted

---

## Technical Debt & Improvements

### Code Quality
- [ ] Add proper error handling in conversion script
- [ ] Add logging to file (not just stdout)
- [ ] Add tests for audio detection logic
- [ ] Better progress indication during conversion

### Docker Setup
- [ ] Custom Dockerfile for Transmission with ffmpeg pre-installed
- [ ] Health checks for all containers
- [ ] Proper volume permissions handling

### Scripts
- [ ] Handle edge cases (no audio streams, corrupted files)
- [ ] Retry logic for failed conversions
- [ ] Conversion queue system (multiple files)
- [ ] Estimate accuracy improvement

---

## Performance Benchmarks (Raspberry Pi 5)

| File Size | Resolution | Duration | Conversion Time |
|-----------|-----------|----------|-----------------|
| 2 GB | 1080p | 2h | ~3-5 min |
| 8 GB | 1080p | 2h | ~5-10 min |
| 18 GB | 1080p | 2.5h | ~12-15 min |

**Note:** Only audio transcoded, video copied unchanged

---

## Dependencies

### Python Packages (in container)
- `python3` (built-in)
- `requests` (for Telegram API)
- `python-telegram-bot` (for Phase 2-4)

### System Tools (in container)
- `ffmpeg` - audio/video processing
- `ffprobe` - media file analysis
- `transmission-remote` - torrent client control
- `lsof` - file lock checking

---

## Troubleshooting

### DTS Not Detected
- Check ffprobe is installed in Transmission container
- Verify notification script has execute permissions
- Check Telegram bot token/chat ID in .env

### Conversion Fails
- Check disk space in /downloads
- Verify ffmpeg is installed
- Check file isn't corrupted (try manual ffprobe)

### Notification Not Received
- Verify .env loaded in docker-compose
- Test Telegram API manually: `curl https://api.telegram.org/bot<TOKEN>/getMe`
- Check script ran (Transmission logs)

---

## Alternative Approaches Considered

### Rejected Options
1. **Stremio + Real-Debrid** - Not local, requires subscription
2. **qBittorrent with plugins** - UI poor, plugins broken
3. **Full *arr stack** - Overkill for 3-4 movies/week
4. **Automatic background conversion** - Wastes CPU, storage
5. **Jackett/Prowlarr** - Not worth extra container for manual search

### Why Current Approach Won
- Matches actual usage pattern
- Minimal complexity
- User control maintained
- Easy to debug and modify
- Progressive enhancement (phases)

---

## Usage Pattern Context

### Viewing Habits
- **Frequency:** 3-4 movies/week
- **Content:** Russian and English movies/shows
- **Viewing:** One-time (watch and forget)
- **Quality preference:** 1080p-2K, not 4K
- **Subtitles:** Russian + English preferred

### Technical Preferences
- Manual > complex automation for low-frequency tasks
- Notifications > silent background processes
- Simple > feature-rich when features unused
- Progressive enhancement over big-bang releases

---

## Questions for Future Development

1. **Should we implement Phase 2-4 or just buy Xiaomi stick?**
   - Stick solves DTS permanently, might obsolete all conversion code
   - But Telegram bot is convenient for other reasons

2. **Is manual search actually a problem?**
   - 30 seconds × 4 times/week = 2 minutes/week
   - Building search might take 4 hours
   - Break-even: 120 weeks (2+ years)

3. **Should we add any automation?**
   - RSS for specific shows followed regularly?
   - Auto-move to library after conversion?
   - Or keep it fully manual?

---

## Success Metrics

### Phase 1 (Current)
- [x] DTS detection working
- [x] Notifications received
- [x] Conversion script functional
- [x] Can watch movies without stuttering
- [x] Setup time < 2 hours
- [x] Maintenance time = 0 hours/week

### Phase 2-4 (Future)
- [ ] Can add torrent from phone (no laptop needed)
- [ ] Search without browser
- [ ] Remote conversion trigger
- [ ] Total interaction time < 1 min per movie

---

**Last Updated:** 2026-01-27
**Status:** Phase 1 complete + Dashboard added
**Next Action:** See ROADMAP.md for dashboard improvements
