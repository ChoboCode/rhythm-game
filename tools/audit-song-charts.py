"""Compare saved chart attacks with independently detected audio onsets.

This is a signal check, not a substitute for listening and play testing.
Requires ffmpeg, numpy, and librosa. Run from rhythm-game:
    python tools/audit-song-charts.py --json chart-audit.json
"""

import argparse
import json
import subprocess
from pathlib import Path

import librosa
import numpy as np
from scipy.ndimage import median_filter


ROOT = Path(__file__).resolve().parent.parent
SONGS = ROOT / "songs"
RATE = 11025
HOP = 128


def audio_samples(path):
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE),
         "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"],
        check=True, capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype="<f4")


def audio_onsets(samples):
    strength = librosa.onset.onset_strength(y=samples, sr=RATE, hop_length=HOP, n_fft=512)
    frames = librosa.onset.onset_detect(
        onset_envelope=strength, sr=RATE, hop_length=HOP, units="frames"
    )
    times = librosa.frames_to_time(frames, sr=RATE, hop_length=HOP)
    return times, strength[frames], np.maximum(0, strength - median_filter(strength, size=87))


def attacks(chart):
    times = np.array([note["t"] for note in chart["notes"]], dtype=float)
    return times[np.r_[True, np.diff(times) > .025]]


def nearest(source, targets):
    indices = np.searchsorted(targets, source)
    left = targets[np.maximum(0, indices - 1)]
    right = targets[np.minimum(len(targets) - 1, indices)]
    return np.where(abs(source - left) <= abs(source - right), left, right)


def alignment(chart_times, onset_times, salience, duration):
    if not len(chart_times) or not len(onset_times):
        return {"matched_42ms": 0, "matched_80ms": 0, "median_error_ms": None, "bias_ms": None,
                "shifted_baseline_80ms": 0}
    offsets = nearest(chart_times, onset_times) - chart_times
    near = abs(offsets) <= .12
    shifts = [3.17, 7.43, 13.71, 19.29, 29.83]
    baseline = [np.mean(abs(nearest((chart_times + shift) % duration, onset_times)
                            - (chart_times + shift) % duration) <= .08) for shift in shifts]
    def strength_at(times):
        frames = np.clip(np.rint(times * RATE / HOP).astype(int), 4, len(salience) - 5)
        values = np.maximum.reduce([salience[frames + delta] for delta in range(-4, 5)])
        return float(np.mean(np.log1p(values)))

    observed = strength_at(chart_times)
    random_strength = np.mean([strength_at((chart_times + shift) % duration) for shift in shifts])
    grid = np.arange(-10, 11) * HOP / RATE
    best_shift = grid[np.argmax([strength_at(np.clip(chart_times + shift, 0, duration))
                                 for shift in grid])]
    return {
        "matched_42ms": round(float(np.mean(abs(offsets) <= .042)), 3),
        "matched_80ms": round(float(np.mean(abs(offsets) <= .08)), 3),
        "median_error_ms": round(float(np.median(abs(offsets))) * 1000),
        "bias_ms": round(float(np.median(offsets[near])) * 1000) if np.any(near) else None,
        "shifted_baseline_80ms": round(float(np.mean(baseline)), 3),
        "salience_lift": round(observed / random_strength, 3) if random_strength else None,
        "best_signal_shift_ms": round(float(best_shift) * 1000),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, help="write full report to this file")
    parser.add_argument("--song", help="only audit this exact title")
    args = parser.parse_args()
    manifest = json.loads((SONGS / "songs.json").read_text(encoding="utf-8"))
    report = []
    for song in manifest:
        if args.song and song["title"] != args.song:
            continue
        samples = audio_samples(SONGS / song["file"])
        onset_times, onset_strength, salience = audio_onsets(samples)
        duration = len(samples) / RATE
        charts = {}
        for level in ("easy", "normal", "hard"):
            chart = json.loads((SONGS / song["charts"][level]).read_text(encoding="utf-8"))
            times = attacks(chart)
            matches = alignment(times, onset_times, salience, duration)
            chord_sizes = {}
            for note in chart["notes"]:
                key = round(note["t"] / .025)
                chord_sizes[key] = chord_sizes.get(key, 0) + 1
            charts[level] = {
                "notes": len(chart["notes"]), "attacks": len(times),
                "notes_per_second": round(len(chart["notes"]) / duration, 2),
                "max_chord": max(chord_sizes.values()),
                "longest_attack_gap_s": round(float(np.max(np.diff(times))), 2),
                "hold_share": round(sum(note["hold"] > 0 for note in chart["notes"])
                                    / len(chart["notes"]), 3),
                **matches,
            }
        strong = onset_times[onset_strength >= np.quantile(onset_strength, .75)] if len(onset_times) else []
        normal_times = attacks(json.loads((SONGS / song["charts"]["normal"]).read_text(encoding="utf-8")))
        strong_coverage = float(np.mean(abs(nearest(strong, normal_times) - strong) <= .1)) if len(strong) else 0
        entry = {"title": song["title"], "duration": round(duration, 2),
                 "audio_onsets": len(onset_times), "strong_onset_coverage_100ms": round(strong_coverage, 3),
                 "charts": charts}
        report.append(entry)
        normal = charts["normal"]
        print(f"{song['title']}\t{len(onset_times)}\t{normal['matched_80ms']:.3f}"
              f"\t{normal['shifted_baseline_80ms']:.3f}\t{normal['median_error_ms']}"
              f"\t{normal['bias_ms']}\t{strong_coverage:.3f}"
              f"\t{normal['salience_lift']}\t{normal['best_signal_shift_ms']}", flush=True)
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
