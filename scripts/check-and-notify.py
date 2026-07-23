#!/usr/bin/env python3
"""
Post-download checker for Transmission
Checks for DTS audio and sends Telegram notification
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import requests

# ============================================================================
# CONFIGURATION - EDIT THESE
# ============================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ============================================================================


def send_telegram(message, parse_mode="HTML"):
    """Send Telegram message"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram send failed: {e}")
        return False


def get_audio_info(file_path):
    """Get audio stream information"""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index,codec_name:stream_tags=language,title",
            "-of",
            "json",
            str(file_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        return data.get("streams", [])
    except Exception as e:
        print(f"Error getting audio info: {e}")
        return None


def estimate_conversion_time(file_size_gb):
    """Estimate conversion time (rough)"""
    # ~1 minute per 1.5GB on Raspberry Pi 5
    minutes = int((file_size_gb / 1.5) * 1.2)
    return max(minutes, 1)


def check_file(file_path):
    """Check file and send notification if DTS found"""
    file_path = Path(file_path)

    if not file_path.exists():
        print(f"File not found: {file_path}")
        return

    print(f"Checking: {file_path.name}")

    # Get audio streams
    audio_streams = get_audio_info(file_path)

    if not audio_streams:
        print("No audio streams found or ffprobe failed")
        # Send notification anyway - download complete
        message = f"✅ <b>Download Complete</b>\n\n📁 {file_path.name}"
        send_telegram(message)
        return

    # Analyze audio tracks
    has_dts = False
    track_info = []

    for stream in audio_streams:
        codec = stream.get("codec_name", "unknown")
        index = stream.get("index", "?")

        tags = stream.get("tags", {})
        lang = tags.get("language", "und").upper()
        title = tags.get("title", "")

        is_dts = "dts" in codec.lower()
        has_dts = has_dts or is_dts

        status = "❌" if is_dts else "✅"

        track_desc = f"{status} Track {index}: {lang} {codec.upper()}"
        if title:
            track_desc += f" ({title})"

        track_info.append(track_desc)

    # Send notification
    file_size_gb = file_path.stat().st_size / (1024**3)

    if has_dts:
        est_time = estimate_conversion_time(file_size_gb)

        message = f"""🎬 <b>Download Complete - DTS Detected</b>

📁 {file_path.name}
📊 Size: {file_size_gb:.1f} GB
⏱ Est. conversion: ~{est_time} min

🎵 <b>Audio Tracks:</b>
{chr(10).join(track_info)}

⚠️ <b>Action Required:</b>
Run conversion script before watching

💡 <code>cd /home/claude/media-server && python3 scripts/convert.py</code>
"""
        print(f"DTS detected - notification sent")
    else:
        message = f"""✅ <b>Download Complete - Ready to Watch!</b>

📁 {file_path.name}
📊 Size: {file_size_gb:.1f} GB

🎵 <b>Audio:</b>
{chr(10).join(track_info)}

✨ All audio tracks compatible - no conversion needed
"""
        print(f"No DTS - ready to watch")

    send_telegram(message)


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: check_and_notify.py <file_or_directory>")
        sys.exit(1)

    path = Path(sys.argv[1])

    if not path.exists():
        print(f"Path does not exist: {path}")
        sys.exit(1)

    # If directory, find largest video file
    if path.is_dir():
        video_exts = {".mkv", ".mp4", ".avi", ".m4v"}
        video_files = [f for f in path.rglob("*") if f.suffix.lower() in video_exts]

        if not video_files:
            print("No video files found in directory")
            sys.exit(1)

        # Check largest file (usually the main movie/episode)
        path = max(video_files, key=lambda f: f.stat().st_size)
        print(f"Found video file: {path.name}")

    check_file(path)


if __name__ == "__main__":
    main()
