"""Add a small, audible melody layer to the saved charts without moving existing notes.

Uses the Demucs vocal/other WAVs left by make-stems.py. Dry run by default:
    python tools/add-melody-notes.py [song title ...]
    python tools/add-melody-notes.py [song title ...] --write

The first write keeps untouched charts in _chart_backup_melody_add. Re-running a
written song is intentionally a no-op; restore the backup before regenerating.
"""
import bisect
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
KEEP = Path(tempfile.gettempdir()) / 'rhythm-game-stems' / 'keep' / 'htdemucs'
BACKUP = ROOT / '_chart_backup_melody_add'
LEVELS = ('easy', 'normal', 'hard')
SOURCE = 'melody-add-v1'
SR = 22050

spec = importlib.util.spec_from_file_location('attack_chart', ROOT / 'tools' / 'attack-chart.py')
attack_chart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attack_chart)


def pitch_at(y, t):
    """Dominant harmonic pitch just after an attack; None for unpitched sound."""
    a = max(0, int((t + .025) * SR))
    b = min(len(y), a + int(.12 * SR))
    part = y[a:b]
    if len(part) < 1000 or np.sqrt(np.mean(part * part)) < .0005:
        return None
    spectrum = np.abs(np.fft.rfft(part * np.hanning(len(part)), n=8192))
    hz_per_bin = SR / 8192
    scores = []
    for midi in range(48, 85):
        fundamental = librosa.midi_to_hz(midi)
        value = 0.0
        for harmonic, weight in ((1, 1.0), (2, .55), (3, .3)):
            k = round(fundamental * harmonic / hz_per_bin)
            value += weight * max(spectrum[max(0, k - 1):k + 2])
        scores.append(value)
    best = int(np.argmax(scores))
    if scores[best] < np.median(scores) * 1.55:
        return None
    return best + 48


def candidates(song, vocal, other):
    vt, vs = attack_chart.detect(vocal)
    ot, os_ = attack_chart.detect(other)
    duration = song['duration']
    words = []
    lines = []
    if song.get('lyrics'):
        lines = json.loads((SONGS / song['lyrics']).read_text(encoding='utf-8'))['lines']
        words = [w['t'] for line in lines for w in (line.get('words') or [])]
    result = []
    # Word timestamps were already aligned to the vocal stem. Use the nearest
    # measured vocal attack so the new notes do not inherit annotation drift.
    for w in words:
        j = int(np.searchsorted(vt, w))
        near = [k for k in (j - 1, j) if 0 <= k < len(vt) and abs(vt[k] - w) <= .08]
        if near:
            k = min(near, key=lambda i: abs(vt[i] - w))
            result.append((float(vt[k]), 'vocal', 5.0 + float(vs[k]), vocal))
    for t, strength in zip(vt, vs):
        if strength >= .38 and not any(abs(t - w) < .11 for w in words):
            result.append((float(t), 'vocal', 2.0 + float(strength), vocal))
    for t, strength in zip(ot, os_):
        in_vocal_line = any(line['t'] - .15 <= t <= line['end'] + .15 for line in lines)
        if strength >= (.85 if in_vocal_line else .52):
            result.append((float(t), 'instrument', 1.0 + float(strength), other))
    # One audible attack is one opportunity, even if both stems detect it.
    result.sort(key=lambda row: -row[2])
    unique = []
    times = []
    for t, kind, score, signal in result:
        if t < .5 or t > duration - .4:
            continue
        j = bisect.bisect_left(times, t)
        if any(abs(times[k] - t) < .06 for k in (j - 1, j) if 0 <= k < len(times)):
            continue
        pitch = pitch_at(signal, t)
        if pitch is None:
            continue
        unique.append({'t': round(t, 4), 'kind': kind, 'score': score, 'pitch': pitch})
        times.insert(j, t)
    return unique


def desired_lane(event, events):
    near = [e['pitch'] for e in events if abs(e['t'] - event['t']) <= 3.0 and e['kind'] == event['kind']]
    if len(near) < 3:
        near = [e['pitch'] for e in events if abs(e['t'] - event['t']) <= 5.0]
    if not near:
        return 3
    low, high = np.percentile(near, [15, 85])
    return int(np.clip(round(1 + 4 * (event['pitch'] - low) / max(3, high - low)), 0, 6))


def find_place(notes, times, event, events, beat, level):
    t = event['t']
    j = bisect.bisect_left(times, t)
    closest = min((abs(times[k] - t), times[k]) for k in (j - 1, j) if 0 <= k < len(times)) if times else (99, None)
    # A melody attack already represented by a pitched note needs no addition.
    same_time = closest[0] <= .055
    if same_time:
        t = closest[1]
        group = [n for n in notes if n['t'] == t]
        if any(n['drum'] == 'tom' for n in group):
            return None
        max_chord = {'easy': 2, 'normal': 3, 'hard': 4}[level]
        if len(group) >= max_chord:
            return None
    else:
        # Preserve the established rhythm density; fill only clear gaps.
        gap = max(.095, beat * {'easy': .42, 'normal': .23, 'hard': .15}[level])
        if closest[0] < gap:
            return None
        if any(abs(times[k] - t) < gap for k in (j - 1, j) if 0 <= k < len(times)):
            return None
    want = desired_lane(event, events)
    # Keep the contour when possible, then use the nearest playable lane.
    for lane in sorted(range(7), key=lambda x: (abs(x - want), abs(x - 3))):
        if same_time and any(n['lane'] == lane for n in group):
            continue
        left = next((n for n in reversed(notes) if n['lane'] == lane and n['t'] <= t), None)
        right = next((n for n in notes if n['lane'] == lane and n['t'] > t), None)
        if left and t - (left['t'] + left.get('hold', 0)) < .22:
            continue
        if right and right['t'] - t < .22:
            continue
        return {'t': round(t, 4), 'lane': lane, 'hold': 0.0, 'drum': 'tom', 'source': SOURCE}
    return None


def enrich(chart, events, song, level):
    notes = list(chart['notes'])
    original = len(notes)
    beat = 60 / song['bpm']
    # A modest budget leaves the existing pattern and difficulty recognizable.
    budget = round(original * {'easy': .10, 'normal': .075, 'hard': .05}[level])
    vocal_budget = round(budget * (.55 if song.get('lyrics') else 0))
    by_kind = {'vocal': [], 'instrument': []}
    for event in events:
        by_kind[event['kind']].append(event)
    for kind in by_kind:
        by_kind[kind].sort(key=lambda event: -event['score'])
    added = {'vocal': 0, 'instrument': 0}
    chosen_times = []
    for kind, limit in (('vocal', vocal_budget), ('instrument', budget - vocal_budget)):
        # Strong opening attacks should not consume the whole song's budget.
        window_cap = max(1, int(np.ceil(limit * 8 / song['duration'] * 1.7)))
        window_counts = {}
        for event in by_kind[kind]:
            if added[kind] >= limit:
                break
            window = int(event['t'] / 8)
            if window_counts.get(window, 0) >= window_cap:
                continue
            if any(abs(t - event['t']) < beat * .65 for t in chosen_times):
                continue
            times = sorted(set(n['t'] for n in notes))
            new = find_place(notes, times, event, events, beat, level)
            if new is None:
                continue
            notes.append(new)
            notes.sort(key=lambda n: (n['t'], n['lane']))
            chosen_times.append(new['t'])
            added[kind] += 1
            window_counts[window] = window_counts.get(window, 0) + 1
    updated = dict(chart, notes=notes, noteCount=len(notes))
    return updated, added


def main():
    write = '--write' in sys.argv[1:]
    titles = {arg for arg in sys.argv[1:] if not arg.startswith('--')}
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    selected = [song for song in manifest if not titles or song['title'] in titles]
    if titles - {song['title'] for song in selected}:
        raise SystemExit('Unknown song: ' + ', '.join(sorted(titles - {song['title'] for song in selected})))
    for song in selected:
        charts = {level: SONGS / song['charts'][level] for level in LEVELS}
        originals = {level: json.loads(path.read_text(encoding='utf-8')) for level, path in charts.items()}
        if any(any(n.get('source') == SOURCE for n in chart['notes']) for chart in originals.values()):
            print(song['title'], 'already enriched; restore _chart_backup_melody_add to regenerate', flush=True)
            continue
        stem = KEEP / Path(song['file']).stem
        if not all((stem / (part + '.wav')).is_file() for part in ('vocals', 'other')):
            raise SystemExit(f'Missing Demucs WAV for {song["title"]}: {stem}')
        vocal = librosa.load(stem / 'vocals.wav', sr=SR, mono=True)[0]
        other = librosa.load(stem / 'other.wav', sr=SR, mono=True)[0]
        events = candidates(song, vocal, other)
        updates = {level: enrich(originals[level], events, song, level) for level in LEVELS}
        report = ' '.join(f'{level}: +{sum(counts.values())} (voice {counts["vocal"]}, instrument {counts["instrument"]})'
                          for level, (_, counts) in updates.items())
        print(f'{song["title"]}: {len(events)} pitched attacks; {report}', flush=True)
        if write:
            BACKUP.mkdir(exist_ok=True)
            manifest_backup = BACKUP / 'songs.json'
            if not manifest_backup.exists():
                shutil.copy2(SONGS / 'songs.json', manifest_backup)
            for level, path in charts.items():
                backup = BACKUP / path.name
                if backup.exists():
                    if backup.read_bytes() != path.read_bytes():
                        raise SystemExit(f'Backup differs from current chart; preserve it and choose a new backup: {backup}')
                else:
                    shutil.copy2(path, backup)
            for level, path in charts.items():
                path.write_text(json.dumps(updates[level][0], ensure_ascii=False, separators=(',', ':')), encoding='utf-8', newline='')
    if write:
        # Keep level chips and sorting consistent with the actual saved charts.
        import subprocess
        subprocess.run([sys.executable, str(ROOT / 'tools' / 'update-levels.py'), '--write'], check=True)


if __name__ == '__main__':
    main()
