"""Safe filesystem operations within configured media library areas."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .download_client import DownloadClientError, path_belongs_to_active_download


class LibraryError(RuntimeError):
    """A library request is invalid or could not be completed."""


class LibraryCollisionError(LibraryError):
    pass


class ActiveDownloadError(LibraryError):
    pass


@dataclass(frozen=True)
class LibraryLocation:
    area: str
    path: str = ""


@dataclass(frozen=True)
class LibraryItem:
    location: LibraryLocation
    name: str
    is_dir: bool
    size: int | None


_ROOTS = {
    "downloads": Path(os.getenv("DOWNLOADS_DIR", "/data/downloads")),
    "movies": Path(os.getenv("MOVIES_DIR", "/data/movies")),
    "shows": Path(os.getenv("SHOWS_DIR", "/data/shows")),
}


def library_areas() -> tuple[str, ...]:
    return tuple(_ROOTS)


def resolve_location(location: LibraryLocation, *, must_exist: bool = True) -> Path:
    if location.area not in _ROOTS:
        raise LibraryError("Unknown library area")
    relative = PurePosixPath(location.path or "")
    if relative.is_absolute() or any(part in {"..", ""} for part in relative.parts):
        raise LibraryError("Invalid library path")
    root = _ROOTS[location.area].resolve()
    candidate = (root / Path(*relative.parts)).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise LibraryError("Path is outside the library area")
    if must_exist and not candidate.exists():
        raise LibraryError("Library item was not found")
    return candidate


def location_for(area: str, path: str = "") -> LibraryLocation:
    location = LibraryLocation(area, path.strip("/"))
    resolve_location(location, must_exist=False)
    return location


def list_library_items(area: str, path: str = "") -> list[LibraryItem]:
    location = location_for(area, path)
    directory = resolve_location(location)
    if not directory.is_dir():
        raise LibraryError("Library location is not a directory")
    items: list[LibraryItem] = []
    for child in directory.iterdir():
        relative = child.relative_to(_ROOTS[area].resolve()).as_posix()
        try:
            size = child.stat().st_size if child.is_file() else None
        except OSError:
            size = None
        items.append(LibraryItem(LibraryLocation(area, relative), child.name, child.is_dir(), size))
    return sorted(items, key=lambda item: (not item.is_dir, item.name.casefold()))


def move_library_item(source: LibraryLocation, destination: LibraryLocation) -> LibraryLocation:
    source_path = resolve_location(source)
    if source_path == _ROOTS[source.area].resolve():
        raise LibraryError("A library area itself cannot be moved")
    destination_path = resolve_location(destination, must_exist=False)
    if destination_path == _ROOTS[destination.area].resolve():
        destination_path /= source_path.name
        destination = LibraryLocation(destination.area, source_path.name)
    if destination_path.exists():
        raise LibraryCollisionError("Destination already exists")
    if source_path == destination_path or source_path in destination_path.parents:
        raise LibraryError("An item cannot be moved into itself")
    if source.area == "downloads":
        try:
            active = path_belongs_to_active_download(source_path)
        except DownloadClientError as exc:
            raise LibraryError("Could not verify whether the download is active") from exc
        if active:
            raise ActiveDownloadError("This item belongs to an active download and cannot be moved")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(source_path), str(destination_path))
    except OSError as exc:
        raise LibraryError(f"Could not move library item: {exc}") from exc
    return destination


def rename_library_item(item: LibraryLocation, new_name: str) -> LibraryLocation:
    name = new_name.strip()
    if not name or PurePosixPath(name).name != name or name in {".", ".."}:
        raise LibraryError("Name must not contain a path")
    parent = PurePosixPath(item.path).parent
    destination_path = str(parent / name) if str(parent) != "." else name
    return move_library_item(item, LibraryLocation(item.area, destination_path))
