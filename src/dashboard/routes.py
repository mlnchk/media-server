import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from services.download_client import DownloadClientError, add_download, list_downloads
from services.library import (
    LibraryError, LibraryLocation, library_areas, list_library_items,
    move_library_item, rename_library_item, resolve_location,
)
from services.media import conversion_status, get_audio_tracks, scan_for_dts, start_audio_conversion
from services.media_server import MediaServerError, refresh_libraries
from services.torrent_indexer import (
    TorrentIndexerError, TorrentIndexerLoginError, fetch_torrent, search_torrents,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def format_size(size: int | None) -> str:
    if size is None:
        return "-"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return "-"


def format_eta(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {secs:02d}s"


async def _items(area: str, path: str) -> list[dict]:
    try:
        items = await asyncio.to_thread(list_library_items, area, path)
    except LibraryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return [
        {"name": item.name, "area": item.location.area, "path": item.location.path,
         "is_dir": item.is_dir, "size_human": format_size(item.size)}
        for item in items
    ]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, area: str = "downloads", path: str = ""):
    if area not in library_areas():
        raise HTTPException(400, "Invalid library area")
    parent = path.rpartition("/")[0] if path else None
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"items": await _items(area, path), "area": area, "path": path,
                 "parent": parent, "areas": library_areas()},
    )


@router.get("/partials/files", response_class=HTMLResponse)
async def files_partial(request: Request, area: str = "downloads", path: str = ""):
    return templates.TemplateResponse(
        request=request, name="partials/files.html",
        context={"items": await _items(area, path), "area": area, "path": path},
    )


@router.post("/api/move")
async def move_item(
    source_area: str = Form(...), source_path: str = Form(...),
    destination_area: str = Form(...), destination_path: str = Form(""),
    new_name: str | None = Form(None), refresh_after: bool = Form(False),
):
    source = LibraryLocation(source_area, source_path)
    name = new_name.strip() if new_name and new_name.strip() else Path(source_path).name
    target_relative = "/".join(part for part in (destination_path.strip("/"), name) if part)
    try:
        result = await asyncio.to_thread(
            move_library_item, source, LibraryLocation(destination_area, target_relative)
        )
    except LibraryError as exc:
        raise HTTPException(400, str(exc)) from exc
    response = {"success": True, "area": result.area, "path": result.path,
                "message": "Item moved successfully"}
    if refresh_after:
        try:
            await refresh_libraries()
        except MediaServerError as exc:
            logger.exception("Item moved but media server refresh failed")
            response["message"] = f"Item moved, but media library refresh failed: {exc}"
            response["refresh_failed"] = True
        else:
            response["message"] = "Item moved and media library refresh requested"
    return response


@router.post("/api/rename")
async def rename_item(area: str = Form(...), path: str = Form(...), new_name: str = Form(...)):
    try:
        result = await asyncio.to_thread(rename_library_item, LibraryLocation(area, path), new_name)
    except LibraryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"success": True, "area": result.area, "path": result.path}


@router.get("/api/audio")
async def audio_info(area: str = Query(...), path: str = Query(...)):
    try:
        media_path = await asyncio.to_thread(resolve_location, LibraryLocation(area, path))
    except LibraryError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not media_path.is_file():
        raise HTTPException(404, "File not found")
    tracks = await asyncio.to_thread(get_audio_tracks, media_path)
    return {"tracks": [track.__dict__ for track in tracks]}


@router.get("/convert", response_class=HTMLResponse)
async def convert_page(request: Request):
    files = []
    for area in library_areas():
        root = await asyncio.to_thread(resolve_location, LibraryLocation(area))
        for media_file in await asyncio.to_thread(scan_for_dts, root):
            files.append({
                "path": media_file.path,
                "area": area,
                "relative_path": media_file.path.relative_to(root).as_posix(),
                "audio_tracks": media_file.audio_tracks,
                "has_dts": media_file.has_dts,
            })
    return templates.TemplateResponse(
        request=request, name="convert.html", context={"files": files, "status": conversion_status}
    )


@router.post("/api/convert")
async def start_conversion(
    area: str = Form(...), path: str = Form(...), tracks: list[int] = Form(...),
):
    try:
        media_path = await asyncio.to_thread(resolve_location, LibraryLocation(area, path))
    except LibraryError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not media_path.is_file():
        raise HTTPException(404, "File not found")
    if conversion_status.running:
        raise HTTPException(409, "Conversion already running")
    available_tracks = await asyncio.to_thread(get_audio_tracks, media_path)
    available = {track.index for track in available_tracks if track.is_dts}
    if not tracks or not set(tracks) <= available:
        raise HTTPException(400, "Only DTS tracks can be converted")
    task = start_audio_conversion(media_path, tracks)
    if task is None:
        raise HTTPException(409, "Conversion already running")
    task.add_done_callback(
        lambda done: logger.error("Conversion task failed", exc_info=done.exception())
        if not done.cancelled() and done.exception() else None
    )
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
    except TorrentIndexerLoginError as exc:
        logger.exception("Torrent indexer login failed")
        raise HTTPException(503, str(exc)) from exc
    except TorrentIndexerError as exc:
        logger.exception("Torrent indexer search failed")
        raise HTTPException(502, str(exc)) from exc
    return {"query": q.strip(), "count": len(results), "results": [
        {"topic_id": item.reference, "title": item.title, "size": item.size,
         "size_gb": round(item.size_gib, 2), "seeds": item.seeders,
         "leeches": item.leechers, "topic_url": item.url}
        for item in results
    ]}


@router.get("/api/torrents/download/{reference}")
async def torrent_download(reference: int):
    try:
        content = await fetch_torrent(reference)
    except TorrentIndexerError as exc:
        logger.exception("Torrent fetch failed")
        raise HTTPException(502, "Torrent fetch failed") from exc
    return Response(content, media_type="application/x-bittorrent",
                    headers={"Content-Disposition": f'attachment; filename="{reference}.torrent"'})


@router.post("/api/torrents/add/{reference}")
async def torrent_add(reference: int):
    try:
        result = await add_download(await fetch_torrent(reference))
    except (TorrentIndexerError, DownloadClientError) as exc:
        logger.exception("Torrent add failed")
        raise HTTPException(502, str(exc)) from exc
    return {"success": True, "name": result.name, "id": result.id, "duplicate": result.duplicate}


@router.get("/downloads", response_class=HTMLResponse)
async def downloads_page(request: Request):
    try:
        downloads = await list_downloads()
        error = None
    except DownloadClientError as exc:
        logger.exception("Could not list downloads")
        downloads, error = [], str(exc)
    return templates.TemplateResponse(
        request=request, name="downloads.html",
        context={"downloads": downloads, "error": error, "format_size": format_size, "format_eta": format_eta},
    )


@router.post("/api/refresh")
async def refresh_media_server():
    try:
        await refresh_libraries()
    except MediaServerError as exc:
        logger.exception("Media server refresh failed")
        raise HTTPException(502, str(exc)) from exc
    return {"success": True, "message": "Media library refresh requested"}
