"""Add restrained tap notes to every registered HARD chart from audio transients.

Requires ffmpeg, numpy, and scipy. Run from the project root:
    python rhythm-game/tools/enrich-hard-charts.py --write

The operation is repeatable: notes marked by this script are replaced on rerun.
"""

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
from scipy import ndimage, signal


ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / "songs"
MARK = "hard-transient-v1"
SAMPLE_RATE = 11025
HOP = 128


def audio_onsets(path):
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
         "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
        check=True, capture_output=True,
    )
    audio = np.frombuffer(decoded.stdout, dtype="<f4")
    frequencies, times, stft = signal.stft(
        audio, fs=SAMPLE_RATE, nperseg=1024, noverlap=1024-HOP,
        boundary="zeros", padded=False,
    )
    spectrum = np.log1p(np.abs(stft) * 90)
    # Low drum, mid snare/body, and high hat/cymbal attacks are analysed
    # independently, so a bright voice does not hide a kick or snare.
    bands = [(42, 160, "kick"), (165, 1800, "snare"), (1850, 5400, "hat")]
    rms = np.sqrt(ndimage.uniform_filter1d(audio.astype(np.float64)**2, size=1103))
    rms_at_frames = np.interp(times, np.arange(len(audio)) / SAMPLE_RATE, rms)
    sound_floor = max(0.005, float(np.percentile(rms_at_frames, 25)) * .65)
    candidates = []
    for lo, hi, drum in bands:
        rows = spectrum[(frequencies >= lo) & (frequencies < hi)]
        flux = np.maximum(0, np.diff(rows, axis=1, prepend=rows[:, :1])).mean(axis=0)
        flux = ndimage.gaussian_filter1d(flux, .65)
        baseline = ndimage.median_filter(flux, size=45)
        excess = np.maximum(0, flux - baseline)
        scale = max(1e-5, float(np.percentile(excess, 90)))
        peaks, properties = signal.find_peaks(
            excess, distance=round(.09 * SAMPLE_RATE / HOP),
            prominence=scale * .20,
        )
        for i, prominence in zip(peaks, properties["prominences"]):
            if rms_at_frames[i] < sound_floor or excess[i] < scale * .40:
                continue
            # STFT flux rises just after an attack; this offset was checked
            # against pre-existing chart heads for the same source audio.
            candidates.append((float(times[i]), drum, float(excess[i] / scale),
                               float(prominence / scale)))
    return candidates


def note_at(notes, t, lane):
    return any(n["lane"] == lane and n["t"] - .22 <= t <= n["t"] + n["hold"] + .22
               for n in notes if n["t"] < t + .23 and n["t"] + n["hold"] > t - .23)


def enrich(chart, candidates):
    original = [n for n in chart["notes"] if n.get("source") != MARK]
    bpm = chart["bpm"]
    beat = 60 / bpm
    grid = beat / 4
    offset = chart.get("beatOffset", 0)
    duration = chart["duration"]
    heads = np.array([n["t"] for n in original], dtype=float)
    heads.sort()
    # Estimate the source chart's attack alignment from already charted heads.
    candidate_times = np.array([c[0] for c in candidates], dtype=float)
    distances = []
    for t in candidate_times:
        ix = np.searchsorted(heads, t)
        nearby = [heads[j] - t for j in (ix-1, ix) if 0 <= j < len(heads)]
        if nearby:
            best = min(nearby, key=abs)
            if abs(best) < .055:
                distances.append(best)
    alignment = float(np.clip(np.median(distances), -.035, .035)) if distances else 0

    by_section = {}
    for t, drum, strength, prominence in candidates:
        t += alignment
        if t < .15 or t > duration - .3:
            continue
        nearest_grid = offset + round((t - offset) / grid) * grid
        # Snap only when the detected transient genuinely sits near the beat.
        if abs(nearest_grid - t) < .045:
            t = nearest_grid
        t = round(t, 4)
        ix = np.searchsorted(heads, t)
        nearby = [heads[j] for j in (ix-1, ix) if 0 <= j < len(heads)]
        nearest = min(nearby, key=lambda head: abs(head-t)) if nearby else None
        # A strong attack already charted as a single note is a good place
        # for a two-hand chord. Avoid almost-simultaneous flams.
        chord = nearest is not None and abs(nearest-t) < .06
        if chord:
            t = float(nearest)
            if sum(abs(n["t"]-t) < .001 for n in original) >= 2:
                continue
        elif nearest is not None and abs(nearest-t) < .135:
            continue
        phase = abs((t - offset) / beat - round((t - offset) / beat))
        score = strength * .65 + prominence * .35 + (.18 if phase < .09 else 0)
        by_section.setdefault(int(t // 12), []).append((score, t, drum, chord))

    added = []
    all_heads = list(original)
    for section in range(math.ceil(duration / 12)):
        start, end = section * 12, min(duration, (section + 1) * 12)
        count = sum(start <= n["t"] < end for n in original)
        # About 15% more heads per phrase; sections that are already dense
        # have less spare room under the rolling two/four-second caps below.
        quota = min(12, max(2, round(count * .15)))
        options = sorted(by_section.get(section, []), reverse=True)
        # Reserve some of each phrase for separate taps. The second pass can
        # use chords when an open beat has no safe lane or clear transient.
        passes = ([item for item in options if not item[3]], options)
        for pass_index, pass_options in enumerate(passes):
            for _, t, drum, _ in pass_options:
                section_added = sum(start <= n["t"] < end for n in added)
                if section_added >= quota or (pass_index == 0 and section_added >= round(quota * .4)):
                    break
                if sum(abs(n["t"] - t) < 1 for n in all_heads) >= 12:
                    continue
                if sum(abs(n["t"] - t) < 2 for n in all_heads) >= 22:
                    continue
                if sum(abs(n["t"] - t) < 1.5 for n in added) >= 4:
                    continue
                if any(abs(n["t"] - t) < .36 for n in added):
                    continue
                # Prefer an independent hand for kick/snare and a narrower lane
                # for hats. The least busy available lane breaks ties.
                lanes = {"kick": [3, 0, 6, 2, 4],
                         "snare": [2, 4, 0, 6, 3],
                         "hat": [1, 5, 0, 6, 2, 4]}[drum]
                feasible = [lane for lane in lanes if not note_at(all_heads, t, lane)]
                if not feasible:
                    continue
                def lane_cost(lane):
                    pressure = sum(max(0, .5 - abs(n["t"] - t))
                                   for n in all_heads if n["lane"] == lane and abs(n["t"] - t) < .5)
                    return pressure * 8 + lanes.index(lane) * .11 + \
                        sum(n["lane"] == lane and abs(n["t"] - t) < 12 for n in added) * .02
                lane = min(feasible, key=lane_cost)
                note = {"t": t, "lane": lane, "hold": 0, "drum": drum, "source": MARK}
                added.append(note)
                all_heads.append(note)

    chart["notes"] = sorted(original + added, key=lambda n: (n["t"], n["lane"]))
    chart["noteCount"] = len(chart["notes"])
    return len(original), len(added), alignment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--song", help="Only process this exact song title")
    args = parser.parse_args()
    songs = json.loads((SONGS / "songs.json").read_text(encoding="utf-8"))
    for song in songs:
        if args.song and song["title"] != args.song:
            continue
        chart_path = SONGS / song["charts"]["hard"]
        chart = json.loads(chart_path.read_text(encoding="utf-8"))
        before, added, alignment = enrich(chart, audio_onsets(SONGS / song["file"]))
        if args.write:
            chart_path.write_text(json.dumps(chart, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{song['title']}: {before} + {added} taps; alignment {alignment*1000:+.0f} ms", flush=True)


if __name__ == "__main__":
    main()
