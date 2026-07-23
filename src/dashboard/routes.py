import asyncio
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from services.media import conversion_status, convert_audio, get_audio_tracks, scan_for_dts
from services.torrents import RutrackerLoginError, add_torrent, download_torrent, search_torrents
from services.transmission import TransmissionError

from .config import DOWNLOADS_DIR, MOVIES_DIR, SHOWS_DIR

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
MEDIA_ROOTS = (DOWNLOADS_DIR, MOVIES_DIR, SHOWS_DIR)


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def get_file_info(path: Path) -> dict:
    return {"name": path.name, "path": str(path), "is_dir": path.is_dir(),
            "size_human": format_size(path.stat().st_size) if path.is_file() else "-"}


def _inside(path: Path, roots: tuple[Path, ...]) -> Path:
    resolved = path.resolve()
    if not any(resolved == root.resolve() or resolved.is_relative_to(root.resolve()) for root in roots):
        raise HTTPException(400, "Path is outside the media directories")
    return resolved


def _download_items() -> list[dict]:
    if not DOWNLOADS_DIR.exists():
        return []
    return [get_file_info(item) for item in sorted(
        DOWNLOADS_DIR.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
    )]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"items": _download_items()})


@router.get("/convert", response_class=HTMLResponse)
async def convert_page(request: Request):
    files = []
    for directory in MEDIA_ROOTS:
        files.extend(scan_for_dts(directory))
    return templates.TemplateResponse(
        request=request, name="convert.html", context={"files": files, "status": conversion_status}
    )


@router.post("/api/move")
async def move_item(path: str = Form(...), destination: str = Form(...), new_name: str = Form(None)):
    source = _inside(Path(path), (DOWNLOADS_DIR,))
    if not source.exists():
        raise HTTPException(404, "Source not found")
    if destination not in {"movies", "shows"}:
        raise HTTPException(400, "Invalid destination")
    destination_dir = MOVIES_DIR if destination == "movies" else SHOWS_DIR
    destination_dir.mkdir(parents=True, exist_ok=True)
    name = new_name.strip() if new_name and new_name.strip() else source.name
    if Path(name).name != name or name in {".", ".."}:
        raise HTTPException(400, "Name must not contain a path")
    target = destination_dir / name
    if target.exists():
        raise HTTPException(400, "Destination already exists")
    shutil.move(str(source), str(target))
    return {"success": True, "destination": str(target)}


@router.get("/api/audio/{path:path}")
async def audio_info(path: str):
    media_path = _inside(Path("/" + path), MEDIA_ROOTS)
    if not media_path.is_file():
        raise HTTPException(404, "File not found")
    return {"tracks": [track.__dict__ for track in get_audio_tracks(media_path)]}


@router.post("/api/convert")
async def start_conversion(path: str = Form(...), tracks: list[int] = Form(...)):
    media_path = _inside(Path(path), MEDIA_ROOTS)
    if not media_path.is_file():
        raise HTTPException(404, "File not found")
    if conversion_status.running:
        raise HTTPException(409, "Conversion already running")
    available = {track.index for track in get_audio_tracks(media_path) if track.is_dts}
    if not tracks or not set(tracks) <= available:
        raise HTTPException(400, "Only DTS tracks can be converted")
    asyncio.create_task(convert_audio(media_path, tracks))
    return {"success": True, "message": "Conversion started"}


@router.get("/api/convert/status")
async def conversion_info():
    return {"running": conversion_status.running, "file": conversion_status.current_file,
            "progress": conversion_status.progress, "error": conversion_status.error}


@router.get("/torrents", response_class=HTMLResponse)
async def torrents_page(request: Request):
    return templates.TemplateResponse(request=request, name="torrents.html", context={})


@router.get("/api/torrents/search")
async def torrent_search(q: str):
    if not q.strip():
        raise HTTPException(400, "Query is required")
    try:
        results = await search_torrents(q, limit=10)
    except RutrackerLoginError as exc:
        logger.exception("RuTracker login failed")
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.exception("RuTracker search failed")
        raise HTTPException(502, "RuTracker search failed; check dashboard logs") from exc
    return {"query": q.strip(), "count": len(results), "results": [
        {"topic_id": item.topic_id, "title": item.title, "size": item.size,
         "size_gb": round(item.size_gib, 2), "seeds": item.seeds,
         "leeches": item.leeches, "topic_url": item.topic_url}
        for item in results
    ]}


@router.get("/api/torrents/download/{topic_id}")
async def torrent_download(topic_id: int):
    try:
        content = await download_torrent(topic_id)
    except Exception as exc:
        logger.exception("Torrent download failed")
        raise HTTPException(502, "Torrent download failed") from exc
    return Response(content, media_type="application/x-bittorrent",
                    headers={"Content-Disposition": f'attachment; filename="{topic_id}.torrent"'})


@router.post("/api/torrents/add/{topic_id}")
async def torrent_add(topic_id: int):
    try:
        result = await add_torrent(topic_id)
    except TransmissionError as exc:
        logger.exception("Transmission add failed")
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        logger.exception("Torrent add failed")
        raise HTTPException(502, "Failed to download or add torrent") from exc
    return {"success": True, "name": result.name, "id": result.id, "duplicate": result.duplicate}


@router.get("/partials/files", response_class=HTMLResponse)
async def files_partial(request: Request):
    return templates.TemplateResponse(
        request=request, name="partials/files.html", context={"items": _download_items()}
    )
