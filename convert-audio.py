#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path

def find_movie_files(directory):
    """Find movie files in the current directory"""
    video_extensions = ['.mkv', '.mp4', '.avi', '.mov', '.m4v']
    movie_files = []

    for ext in video_extensions:
        movie_files.extend(Path(directory).glob(f'*{ext}'))

    return movie_files

def get_audio_tracks(movie_file):
    """Get audio track information using ffprobe"""
    try:
        # Get basic info using grep method (more reliable for language)
        cmd = ['ffprobe', str(movie_file)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        tracks = []
        audio_lines = [line for line in result.stderr.split('\n') if 'Audio:' in line]

        for line in audio_lines:
            # Parse line like: "Stream #0:1(rus): Audio: dts (DTS), 48000 Hz, 5.1(side), fltp, 768 kb/s (default)"
            if 'Stream #' in line:
                # Extract stream index
                stream_part = line.split('Stream #')[1].split(':')[1].split('(')[0]
                index = int(stream_part)

                # Extract language (in parentheses after stream index)
                lang = 'unknown'
                if '(' in line and ')' in line:
                    lang_part = line.split('(')[1].split(')')[0]
                    if len(lang_part) <= 3 and lang_part.isalpha():  # Likely a language code
                        lang = lang_part

                # Extract codec
                codec = 'unknown'
                if 'Audio: ' in line:
                    audio_part = line.split('Audio: ')[1]
                    codec = audio_part.split(' ')[0].split('(')[0]

                # Extract channels (look for patterns like "5.1", "2.0", or just numbers)
                channels = 2  # default
                if '5.1' in line:
                    channels = 6
                elif 'stereo' in line or '2.0' in line:
                    channels = 2
                elif 'mono' in line or '1.0' in line:
                    channels = 1

                tracks.append({
                    'index': index,
                    'codec': codec,
                    'channels': channels,
                    'language': lang
                })

        return tracks
    except subprocess.CalledProcessError:
        print(f"Error: Could not analyze {movie_file}")
        return []

def display_audio_tracks(tracks):
    """Display audio tracks in a readable format"""
    print("\nAudio tracks:")
    print("Index | Codec | Channels | Language")
    print("------|-------|----------|----------")
    for i, track in enumerate(tracks):
        print(f"{i:5} | {track['codec']:5} | {track['channels']:8} | {track['language']:8}")

def convert_audio_track(movie_file, track_index, tracks):
    """Convert selected audio track to AC3"""
    original_path = Path(movie_file)
    output_path = original_path.with_name(f"{original_path.stem}_ac3{original_path.suffix}")

    # Build ffmpeg command
    cmd = [
        'ffmpeg', '-i', str(movie_file),
        '-threads', '0',  # Use all available CPU cores
        '-map', '0',  # Copy all streams
        '-c', 'copy',  # Copy all streams by default
        f'-c:a:{track_index}', 'ac3',  # Convert specific audio track to AC3
        f'-b:a:{track_index}', '640k',  # Set bitrate for AC3
        '-y',  # Overwrite output file
        str(output_path)
    ]

    print(f"\nConverting track {track_index} ({tracks[track_index]['codec']}) to AC3...")
    print(f"Output: {output_path.name}")
    print("\nRunning ffmpeg...")

    try:
        subprocess.run(cmd, check=True)
        print(f"\nSuccess! Converted file saved as: {output_path.name}")
    except subprocess.CalledProcessError:
        print(f"Error: Conversion failed")
        if output_path.exists():
            output_path.unlink()  # Remove failed output file

def main():
    current_dir = Path.cwd()

    # Find movie files
    movie_files = find_movie_files(current_dir)

    if not movie_files:
        print("No movie files found in current directory.")
        sys.exit(1)

    # If multiple files, let user choose
    if len(movie_files) > 1:
        print("Multiple movie files found:")
        for i, file in enumerate(movie_files):
            print(f"{i}: {file.name}")

        while True:
            try:
                choice = int(input(f"\nSelect file (0-{len(movie_files)-1}): "))
                if 0 <= choice < len(movie_files):
                    movie_file = movie_files[choice]
                    break
                else:
                    print("Invalid choice!")
            except ValueError:
                print("Please enter a number!")
    else:
        movie_file = movie_files[0]

    print(f"\nAnalyzing: {movie_file.name}")

    # Get audio tracks
    tracks = get_audio_tracks(movie_file)
    if not tracks:
        sys.exit(1)

    # Display tracks
    display_audio_tracks(tracks)

    # Ask user which track to convert
    while True:
        try:
            track_choice = int(input(f"\nSelect audio track to convert to AC3 (0-{len(tracks)-1}): "))
            if 0 <= track_choice < len(tracks):
                break
            else:
                print("Invalid track index!")
        except ValueError:
            print("Please enter a number!")

    # Check if already AC3
    if tracks[track_choice]['codec'] == 'ac3':
        print(f"Track {track_choice} is already AC3!")
        sys.exit(0)

    # Convert
    convert_audio_track(movie_file, track_choice, tracks)

if __name__ == "__main__":
    main()
