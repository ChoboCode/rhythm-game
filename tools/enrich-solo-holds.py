"""Review and optionally extend HARD holds at sustained instrumental leads.

Requires Demucs htdemucs 'other' stems in --stems. Guitar, synth and piano can
all appear in this stem, so candidates must be reviewed before --write.
"""

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import stft


ROOT = Path(__file__).resolve().parents[1]
SR = 11025
HOP = 256
NFFT = 2048


def decode(path):
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
         "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SR), "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(pcm, dtype="<f4").astype(np.float32)


def features(path):
    freq, times, spec = stft(decode(path), SR, nperseg=NFFT,
                             noverlap=NFFT - HOP, boundary="zeros")
    mid = (freq >= 190) & (freq <= 2400)
    magnitude = np.abs(spec[mid])
    harmonic = np.minimum(magnitude, median_filter(magnitude, size=(1, 11)))
    energy = np.sqrt(np.mean(harmonic * harmonic, axis=0))
    flux = np.sum(np.maximum(harmonic[:, 1:] - harmonic[:, :-1], 0), axis=0)
    flux = np.r_[0, flux] / np.maximum(np.sum(harmonic, axis=0), 1e-8)
    return times, energy, flux


def candidates(chart, times, energy, flux):
    notes = chart["notes"]
    median_energy = np.percentile(energy, 55)
    flux_floor = np.percentile(flux, 67)
    lane_next = [float("inf")] * len(notes)
    seen = {}
    for i in range(len(notes) - 1, -1, -1):
        n = notes[i]
        lane_next[i] = seen.get(n["lane"], float("inf"))
        seen[n["lane"]] = n["t"]
    choices = []
    for i, note in enumerate(notes):
        if note["hold"] >= 1.35:
            continue
        if note.get("source") == "hard-transient-v1":
            continue
        t = note["t"]
        if any(other is not note and other["hold"] > .9 and
               other["t"] - .12 <= t < other["t"] + other["hold"] - .2
               for other in notes[max(0, i - 20):i + 8]):
            continue
        room = min(lane_next[i] - t - .13, chart["duration"] - t - .25, 3.0)
        if room < 1.35:
            continue
        a = np.searchsorted(times, t - .09)
        b = np.searchsorted(times, t + .11)
        start = np.searchsorted(times, t + .16)
        end = np.searchsorted(times, t + min(room, 2.5))
        if b <= a or end - start < 35:
            continue
        head = np.percentile(energy[a:b], 75)
        if head < median_energy * 1.3:
            continue
        # Favor a freshly picked/plucked lead note instead of a pad that was
        # already present before the chart head.
        if np.max(flux[a:b]) < flux_floor:
            continue
        # Find the portion that stays audible; a new strong onset ends the hold.
        threshold = max(median_energy * .72, head * .40)
        end_frame = start
        for frame in range(start, end):
            age = times[frame] - t
            if age > .48 and (energy[frame] < threshold or
                              (flux[frame] > flux_floor * 1.8 and
                               energy[frame] > median_energy)):
                break
            end_frame = frame
        length = min(room, times[end_frame] - t)
        if length < 1.35:
            continue
        score = head / max(median_energy, 1e-8) * length
        choices.append((score, i, round(length, 4)))
    return choices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stems", type=Path, required=True)
    parser.add_argument("--titles", nargs="*")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    songs = json.loads((ROOT / "songs" / "songs.json").read_text(encoding="utf-8"))
    for song in songs:
        if args.titles and song["title"] not in args.titles:
            continue
        stem_dir = args.stems / Path(song["file"]).stem
        stem = next((stem_dir / ("other" + suffix) for suffix in (".wav", ".mp3")
                     if (stem_dir / ("other" + suffix)).exists()), None)
        if not stem:
            continue
        chart_path = ROOT / "songs" / song["charts"]["hard"]
        chart = json.loads(chart_path.read_text(encoding="utf-8"))
        if args.write and any(note.get("source") == "instrumental-sustain-v1"
                              for note in chart["notes"]):
            print(f"{song['title']}: already enriched; skipped", flush=True)
            continue
        times, energy, flux = features(stem)
        choices = candidates(chart, times, energy, flux)
        remainder = next((stem_dir / ("no_other" + suffix)
                          for suffix in (".wav", ".mp3")
                          if (stem_dir / ("no_other" + suffix)).exists()), None)
        other_audio, rest_audio = decode(stem), decode(remainder)
        def prominence(t):
            a, b = int(max(0, t - .15) * SR), int((t + .85) * SR)
            lead = np.sqrt(np.mean(other_audio[a:b] ** 2))
            rest = np.sqrt(np.mean(rest_audio[a:b] ** 2))
            return float(lead / max(rest, 1e-8))
        # Long leads should be accents, not a second blanket of holds.
        chosen = []
        for score, index, length in sorted(choices, reverse=True):
            note = chart["notes"][index]
            ratio = prominence(note["t"])
            if ratio < .55:
                continue
            if any(abs(note["t"] - chart["notes"][other]["t"]) < 5
                   for _, other, _, _ in chosen):
                continue
            chosen.append((score, index, length, ratio))
            if len(chosen) >= max(3, round(chart["duration"] / 28)):
                break
        chosen.sort(key=lambda row: chart["notes"][row[1]]["t"])
        report = [(round(chart["notes"][index]["t"], 2), length,
                   round(score, 1), round(ratio, 2))
                  for score, index, length, ratio in chosen]
        print(f"{song['title']}: {report}", flush=True)
        if args.write:
            for _, index, length, _ in chosen:
                chart["notes"][index]["hold"] = length
                chart["notes"][index]["source"] = "instrumental-sustain-v1"
            chart_path.write_text(json.dumps(chart, ensure_ascii=False,
                                             separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
