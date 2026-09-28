"""Estimate the sustained bass pitch underneath each registered song.

The profile tunes only the short kick/tom tail; snares and cymbals stay
unpitched. It never changes the score, chart, or the displayed song key.
Run from the repository root with --write to update songs/songs.json.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import librosa
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / "songs"
SR = 11025
FFT = 8192
HOP = 2048
WINDOW = 2.0
NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def bass_profile(audio_path, duration):
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio_path), "-f", "f32le",
         "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SR), "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    samples = np.frombuffer(pcm, dtype="<f4")
    spectrum = np.abs(librosa.stft(samples, n_fft=FFT, hop_length=HOP))
    harmonic, _ = librosa.decompose.hpss(spectrum)
    frequencies = librosa.fft_frequencies(sr=SR, n_fft=FFT)
    bass = harmonic[(frequencies >= 43) & (frequencies <= 220)]
    bass_hz = frequencies[(frequencies >= 43) & (frequencies <= 220)]
    # The strongest low harmonic is generally the bass fundamental or an
    # octave of it. Octaves collapse to the same pitch class.
    peaks = np.argmax(bass, axis=0)
    magnitude = bass[peaks, np.arange(len(peaks))]
    pitch_class = np.rint(librosa.hz_to_midi(bass_hz[peaks])).astype(np.int16) % 12
    times = librosa.frames_to_time(np.arange(len(peaks)), sr=SR, hop_length=HOP)
    audible = magnitude > np.percentile(magnitude, 30)
    global_weight = np.bincount(pitch_class[audible], weights=magnitude[audible], minlength=12)
    global_root = int(np.argmax(global_weight))
    profile = []
    for section in range(int(np.ceil(duration / WINDOW))):
        here = audible & (times >= section * WINDOW) & (times < (section + 1) * WINDOW)
        weights = np.bincount(pitch_class[here], weights=magnitude[here], minlength=12)
        if weights.sum() < 1e-6 or weights.max() < weights.sum() * .24:
            profile.append(profile[-1] if profile else global_root)
        else:
            profile.append(int(np.argmax(weights)))
    return profile, global_root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    manifest_path = SONGS / "songs.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for song in manifest:
        profile, root = bass_profile(SONGS / song["file"], song["duration"])
        print(f"{song['title']}: {NAMES[root]}, "
              f"{len(profile)} sections, "
              f"{','.join(NAMES[int(x)] for x in profile[:12])}", flush=True)
        if args.write:
            song["soundBass"] = profile
    if args.write:
        formatted = json.dumps(manifest, ensure_ascii=False, indent=2)
        formatted = re.sub(
            r'("soundBass": )\[\s*([0-9,\s]+)\]',
            lambda m: m.group(1) + "[" + ",".join(m.group(2).split(","))
            .replace("\n", "").replace(" ", "") + "]",
            formatted,
        )
        manifest_path.write_text(formatted + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
