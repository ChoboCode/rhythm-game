"""Measure the isolated drum texture of every song for the live key sounds.

Each two-second entry contains independent kick, snare, and cymbal strengths
from the audio itself. This does not change the song mix or note timing.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt


ROOT = Path(__file__).resolve().parents[1]
SR = 11025
WINDOW = 2.0
FRAME = 256
STEP = 128
BANDS = ((42, 165), (650, 3800), (3300, 5200))


def decode(path):
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
         "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SR), "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(pcm, dtype="<f4").astype(np.float64)


def band_strength(samples, low, high, duration):
    sos = butter(3, (low, high), btype="bandpass", fs=SR, output="sos")
    filtered = sosfilt(sos, samples)
    count = max(1, 1 + (len(filtered) - FRAME) // STEP)
    frames = np.lib.stride_tricks.sliding_window_view(filtered, FRAME)[::STEP][:count]
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    # Positive changes in band energy emphasize actual hits over a constant
    # bass line, sustained cymbal, or a loud but smooth melodic instrument.
    attack = np.maximum(0, rms - np.r_[rms[0], rms[:-1]] * .82)
    sections = int(np.ceil(duration / WINDOW))
    result = np.zeros(sections)
    for section in range(sections):
        a = int(section * WINDOW * SR / STEP)
        b = min(len(attack), int((section + 1) * WINDOW * SR / STEP))
        if b > a:
            values = attack[a:b]
            result[section] = np.sqrt(np.mean(values * values))
    return result


def strength_levels(values):
    positive = values[values > 1e-8]
    if not len(positive):
        return [1] * len(values)
    # Relative to the same song, with silence/intro held back.  The reference
    # stays below the loudest chorus so its strongest bins retain headroom.
    reference = np.percentile(positive, 82)
    ratios = values / max(reference, 1e-8)
    return np.select(
        [ratios < .40, ratios < .80, ratios < 1.03], [0, 1, 2], default=3,
    ).astype(int).tolist()


def flow_profile(stem_path, duration):
    samples = decode(stem_path)
    bands = [strength_levels(band_strength(samples, low, high, duration))
             for low, high in BANDS]
    return [list(levels) for levels in zip(*bands)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--stems", type=Path, required=True,
                        help="htdemucs output directory containing each song's drums stem")
    args = parser.parse_args()
    manifest_path = ROOT / "songs" / "songs.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for song in manifest:
        stem_dir = args.stems / Path(song["file"]).stem
        stem = next((stem_dir / ("drums" + suffix) for suffix in (".wav", ".mp3")
                     if (stem_dir / ("drums" + suffix)).exists()), None)
        if stem is None:
            raise FileNotFoundError(f"missing drums stem for {song['title']}: {stem_dir}")
        flow = flow_profile(stem, song["duration"])
        histogram = [[sum(row[band] == tier for row in flow) for tier in range(4)]
                     for band in range(3)]
        print(f"{song['title']}: {len(flow)} windows, K/S/H {histogram}", flush=True)
        if args.write:
            song["soundFlow"] = flow
    if args.write:
        formatted = json.dumps(manifest, ensure_ascii=False, indent=2)
        formatted = re.sub(
            r'("soundBass": )\[\s*([0-9,\s]+)\]',
            lambda match: match.group(1) + "[" + ",".join(
                match.group(2).replace("\n", "").replace(" ", "").split(",")) + "]",
            formatted,
        )
        formatted = re.sub(
            r'("soundFlow": )\[\s*((?:\[\s*\d+,\s*\d+,\s*\d+\s*\],?\s*)+)\]',
            lambda match: match.group(1) + "[" + ",".join(
                "[" + ",".join(re.findall(r"\d+", row)) + "]"
                for row in re.findall(r"\[[^\[\]]+\]", match.group(2))) + "]",
            formatted,
        )
        manifest_path.write_text(formatted + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
