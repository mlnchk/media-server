"""Reusable media inspection and safe DTS-to-AC3 conversion operations."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DTS_CODECS = {"dts", "dca", "dts-hd", "dts_hd"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv"}
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "640k")


@dataclass(frozen=True)
class AudioTrack:
    index: int
    codec: str
    channels: int
    language: str | None
    is_dts: bool


@dataclass(frozen=True)
class MediaFile:
    path: Path
    audio_tracks: list[AudioTrack]
    has_dts: bool


class ConversionStatus:
    def __init__(self) -> None:
        self.running = False
        self.current_file: str | None = None
        self.progress = ""
        self.error: str | None = None


conversion_status = ConversionStatus()


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def find_video_files(directory: Path) -> list[Path]:
    if directory.is_file():
        return [directory] if is_video_file(directory) else []
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*") if path.is_file() and is_video_file(path))


def get_audio_tracks(file_path: Path) -> list[AudioTrack]:
    command = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-select_streams", "a", str(file_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode:
            return []
        streams = json.loads(result.stdout).get("streams", [])
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    return [
        AudioTrack(
            index=int(stream.get("index", 0)),
            codec=str(stream.get("codec_name", "")).lower(),
            channels=int(stream.get("channels", 0)),
            language=stream.get("tags", {}).get("language"),
            is_dts=str(stream.get("codec_name", "")).lower() in DTS_CODECS,
        )
        for stream in streams
    ]


def scan_for_dts(directory: Path) -> list[MediaFile]:
    found: list[MediaFile] = []
    for video in find_video_files(directory):
        tracks = get_audio_tracks(video)
        if tracks:
            found.append(MediaFile(video, tracks, any(track.is_dts for track in tracks)))
    return found


def start_audio_conversion(file_path: Path, track_indices: list[int]) -> asyncio.Task[bool] | None:
    """Atomically reserve the single conversion slot and start conversion."""
    if conversion_status.running:
        return None
    conversion_status.running = True
    conversion_status.current_file = file_path.name
    conversion_status.progress = "Starting..."
    conversion_status.error = None
    return asyncio.create_task(_perform_conversion(file_path, track_indices))


async def convert_audio(file_path: Path, track_indices: list[int]) -> bool:
    """Convert now when the shared conversion slot is available."""
    task = start_audio_conversion(file_path, track_indices)
    return False if task is None else await task


async def _perform_conversion(file_path: Path, track_indices: list[int]) -> bool:
    source = file_path.resolve()
    output = source.with_name(f".{source.stem}.converting{source.suffix}")
    process: asyncio.subprocess.Process | None = None
    try:
        tracks = await asyncio.to_thread(get_audio_tracks, source)
        selected = set(track_indices)
        valid = {track.index for track in tracks if track.is_dts}
        if not selected or not selected <= valid:
            raise ValueError("Select one or more DTS audio tracks")

        command = ["ffmpeg", "-y", "-i", str(source), "-map", "0", "-c", "copy"]
        for audio_index, track in enumerate(tracks):
            if track.index in selected:
                command.extend([f"-c:a:{audio_index}", "ac3", f"-b:a:{audio_index}", AUDIO_BITRATE])
        command.append(str(output))
        conversion_status.progress = "Converting..."
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError(stderr.decode(errors="replace")[-1000:] or "ffmpeg failed")
        os.replace(output, source)
        conversion_status.progress = "Done"
        return True
    except asyncio.CancelledError:
        conversion_status.error = "Conversion interrupted"
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        output.unlink(missing_ok=True)
        raise
    except Exception as exc:
        conversion_status.error = str(exc)
        output.unlink(missing_ok=True)
        return False
    finally:
        conversion_status.running = False
