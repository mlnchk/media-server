#!/usr/bin/env python3
"""Manual CLI entry point for the shared DTS conversion service."""

import argparse
import asyncio
import sys
from pathlib import Path

# Permit running from a source checkout as well as the application image.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.media import conversion_status, convert_audio, scan_for_dts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactively convert DTS audio tracks to AC3")
    parser.add_argument("directory", nargs="?", type=Path, default=Path("/data/movies"))
    args = parser.parse_args()
    files = [item for item in scan_for_dts(args.directory) if item.has_dts]
    if not files:
        print("No files with DTS audio found.")
        return 0
    for number, media in enumerate(files, 1):
        tracks = [track.index for track in media.audio_tracks if track.is_dts]
        print(f"{number}. {media.path} (DTS streams: {', '.join(map(str, tracks))})")
    try:
        selection = int(input("File number (0 to cancel): "))
    except (ValueError, EOFError, KeyboardInterrupt):
        return 1
    if selection == 0:
        return 0
    if selection < 1 or selection > len(files):
        print("Invalid selection.")
        return 1
    media = files[selection - 1]
    tracks = [track.index for track in media.audio_tracks if track.is_dts]
    success = asyncio.run(convert_audio(media.path, tracks))
    print("Conversion complete." if success else f"Conversion failed: {conversion_status.error}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
