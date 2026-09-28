"""Trace instrumental phrases and refine saved charts without touching original attack-v1 notes.

Dry run: python -X utf8 tools/refine-interludes.py [song title ...]
Write:   python -X utf8 tools/refine-interludes.py [song title ...] --write

The first write backs up the v1 melody charts. Re-running replaces only the
generated interlude-v2 notes. It also removes v1 additions inside the measured
interludes so the new phrase can be played as one coherent line.
"""
import bisect
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from math import gcd

import librosa
import numpy as np
import scipy.ndimage
import scipy.signal
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
KEEP = Path(tempfile.gettempdir()) / 'rhythm-game-stems' / 'keep' / 'htdemucs'
BACKUP = ROOT / '_chart_backup_interlude_v2'
LEVELS = ('easy', 'normal', 'hard')
SOURCE = 'interlude-v2'
SR = 22050
HOP = 256

spec = importlib.util.spec_from_file_location('attack_chart', ROOT / 'tools' / 'attack-chart.py')
attack_chart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attack_chart)


def load_stem(path):
    audio, rate = sf.read(path, dtype='float32')
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if rate != SR:
        factor = gcd(rate, SR)
        audio = scipy.signal.resample_poly(audio, SR // factor, rate // factor)
    return np.asarray(audio, dtype=np.float32)


def interludes(song, vocal, other):
    """Lyric gaps that also have audible instrument and little separated voice."""
    block = SR // 10
    n = min(len(vocal), len(other)) // block
    if n == 0:
        return []
    vr = np.sqrt(np.mean(vocal[:n * block].reshape(n, block) ** 2, axis=1))
    other_r = np.sqrt(np.mean(other[:n * block].reshape(n, block) ** 2, axis=1))
    lyric_gap = np.ones(n, dtype=bool)
    if song.get('lyrics'):
        lines = json.loads((SONGS / song['lyrics']).read_text(encoding='utf-8'))['lines']
        for line in lines:
            a = max(0, int((line['t'] - .2) * 10))
            b = min(n, int((line['end'] + .2) * 10) + 1)
            lyric_gap[a:b] = False
    active = other_r > max(.002, np.percentile(other_r, 80) * .1)
    quiet = vr < np.maximum(np.percentile(vr, 85) * .22, other_r * .35)
    mask = lyric_gap & active & quiet
    # Bridge brief decays between successive played notes, then reject tiny gaps.
    for i in range(1, n - 3):
        if mask[i - 1] and not mask[i]:
            following = np.flatnonzero(mask[i:i + 4])
            if len(following):
                mask[i:i + int(following[0])] = True
    edges = np.diff(np.r_[False, mask, False].astype(int))
    spans = [(round(a / 10, 3), round(b / 10, 3))
             for a, b in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]) if b - a >= 14]
    return spans


def pitch_track(other, a, b):
    """Dominant moving pitched line in the other stem, MIDI 55..84."""
    pad = .2
    start = max(0, a - pad)
    y = other[int(start * SR):min(len(other), int((b + pad) * SR))]
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=HOP,
                          fmin=librosa.note_to_hz('C2'), n_bins=84)).astype(np.float32)
    midi = np.arange(55, 85)
    k = midi - 36
    sal = C[k] + .45 * C[k + 12] + .24 * C[k + 19]
    sal = scipy.ndimage.median_filter(sal, size=(1, 5))
    # Chord beds stay nearly static. Give moving tones a modest advantage while
    # retaining sustained brass/strings in the raw salience term.
    bed = scipy.ndimage.median_filter(sal, size=(1, 35))
    emphasis = .65 * sal + .35 * np.maximum(0, sal - .65 * bed)
    emphasis *= np.linspace(.9, 1.08, len(midi))[:, None]
    winner = scipy.ndimage.median_filter(np.argmax(emphasis, axis=0), size=5)
    strength = np.take_along_axis(sal, winner[None, :], axis=0)[0]
    conf = strength / (np.median(sal, axis=0) + 1e-5)
    frame_t = start + np.arange(len(winner)) * HOP / SR
    return frame_t, midi[winner], sal, strength, conf


def instrument_events(other, spans):
    onset_t, onset_s = attack_chart.detect(other)
    events = []
    for a, b in spans:
        frame_t, pitch, sal, strength, conf = pitch_track(other, a, b)
        candidates = []
        # Actual attacks catch piano and plucked notes, including repeated pitch.
        lo, hi = np.searchsorted(onset_t, [a, b])
        for t, onset_strength in zip(onset_t[lo:hi], onset_s[lo:hi]):
            if onset_strength < .24:
                continue
            f = np.searchsorted(frame_t, t + .065)
            sl = slice(max(0, f - 2), min(len(pitch), f + 5))
            if sl.stop - sl.start < 4:
                continue
            pitches = pitch[sl]
            p = int(np.median(pitches))
            stable = np.mean(pitches == p)
            if stable < .55 or np.median(conf[sl]) < 1.7:
                continue
            candidates.append((float(t), p, 'attack', float(onset_strength)))
        # A breath/legato lead can change pitch without a strong broadband attack.
        changes = np.flatnonzero(np.diff(pitch, prepend=pitch[0]) != 0)
        for f in changes:
            if f < 5 or f + 10 >= len(pitch):
                continue
            t = float(frame_t[f])
            if not a + .08 <= t <= b - .08 or pitch[f] == pitch[f - 4]:
                continue
            p = int(pitch[f])
            if np.mean(pitch[f:f + 9] == p) < .78 or np.median(conf[f:f + 9]) < 2.0:
                continue
            k = p - 55
            before = np.median(sal[k, f - 5:f - 1])
            after = np.median(sal[k, f + 2:f + 8])
            if after < before * 1.35 or after < np.percentile(strength, 55) * .4:
                continue
            candidates.append((t, p, 'transition', float(after / (before + .01))))
        candidates.sort(key=lambda item: (item[0], item[2] != 'attack'))
        merged = []
        for t, p, kind, score in candidates:
            if merged and t - merged[-1][0] < .065:
                if kind == 'attack' and merged[-1][2] != 'attack':
                    merged[-1] = (t, p, kind, score)
                continue
            merged.append((t, p, kind, score))
        for t, p, kind, score in merged:
            f = min(len(frame_t) - 1, int(np.searchsorted(frame_t, t + .06)))
            k = p - 55
            initial = float(np.median(sal[k, f:min(len(frame_t), f + 6)]))
            end_limit = min(b, t + 2.4)
            end = t + .1
            low_count = 0
            for z in range(f + 7, min(len(frame_t), int(np.searchsorted(frame_t, end_limit)))):
                dominant = sal[k, z] >= .7 * sal[:, z].max()
                if sal[k, z] < initial * .38 or not dominant:
                    low_count += 1
                else:
                    low_count = 0
                if low_count >= 11:
                    break
                end = float(frame_t[z])
            hold = round(min(2.1, end - t - .12), 3) if end - t >= .72 else 0.0
            events.append({'t': round(t, 4), 'pitch': p, 'kind': kind,
                           'strength': round(score, 3), 'hold': max(0.0, hold),
                           'span': (a, b)})
    return events


def in_span(t, spans):
    return any(a <= t < b for a, b in spans)


def excluded_effect(t, song):
    for drop in song.get('drops', []):
        hits = drop.get('hits') or [drop['t']]
        if min(hits) - .65 <= t <= max(hits) + .25:
            return True
    return any(rest['from'] <= t <= rest['to'] for rest in song.get('rests', []))


def starting_lane(event, events):
    near = [e['pitch'] for e in events if e['span'] == event['span']]
    lo, hi = np.percentile(near, [15, 85]) if len(near) >= 3 else (event['pitch'] - 4, event['pitch'] + 4)
    return int(np.clip(round(1 + 4 * (event['pitch'] - lo) / max(3, hi - lo)), 0, 6))


def add_to_chart(chart, song, spans, events, level):
    base = [n for n in chart['notes'] if n.get('source') != SOURCE and
            not (n.get('source') == 'melody-add-v1' and in_span(n['t'], spans))]
    notes = sorted(base, key=lambda n: (n['t'], n['lane']))
    original_count = sum(n.get('source') == 'attack-v1' for n in notes)
    budget = round(original_count * {'easy': .1, 'normal': .1, 'hard': .1}[level])
    beat = 60 / song['bpm']
    gap = max(.085, beat * {'easy': .48, 'normal': .30, 'hard': .19}[level])
    per_4s = {'easy': 4, 'normal': 6, 'hard': 8}[level]
    used_windows = {}
    added = 0
    represented = 0
    holds = 0
    stair = None
    for event in sorted(events, key=lambda e: e['t']):
        if added >= budget or excluded_effect(event['t'], song):
            continue
        t, span = event['t'], event['span']
        window = (span[0], int((t - span[0]) / 4))
        if used_windows.get(window, 0) >= per_4s:
            continue
        if stair and stair['span'] == span and t - stair['t'] < 1.15:
            direction = 1 if event['pitch'] > stair['pitch'] else -1 if event['pitch'] < stair['pitch'] else stair['dir']
            want = stair['lane'] + direction * (2 if abs(event['pitch'] - stair['pitch']) >= 5 else 1)
            if want > 6 or want < 0:
                if event['pitch'] == stair['pitch']:
                    direction = -direction
                    want = stair['lane'] + direction
                else:
                    want = 0 if want > 6 else 6
        else:
            direction = 1
            want = starting_lane(event, events)
        times = sorted(set(n['t'] for n in notes))
        j = bisect.bisect_left(times, t)
        nearby = [(abs(times[k] - t), times[k]) for k in (j - 1, j) if 0 <= k < len(times)]
        distance, existing_t = min(nearby) if nearby else (99, None)
        same_time = distance <= .025
        if same_time:
            t = existing_t
            group = [n for n in notes if n['t'] == t]
            pitched = [n for n in group if n.get('drum') == 'tom']
            if any(abs(n['lane'] - want) <= 1 for n in pitched):
                represented += 1
                stair = dict(t=t, pitch=event['pitch'], lane=pitched[0]['lane'], dir=direction, span=span)
                continue
            if len(group) >= {'easy': 2, 'normal': 3, 'hard': 4}[level]:
                continue
        elif distance < gap:
            continue
        desired_hold = event['hold'] if event['hold'] >= .55 else 0.0
        options = []
        for lane in sorted(range(7), key=lambda x: (abs(x - want), x != want)):
            if abs(lane - want) > 2:
                continue  # A far-away fallback would reverse or hide the melodic contour.
            if same_time and any(n['lane'] == lane for n in group):
                continue
            prev = next((n for n in reversed(notes) if n['lane'] == lane and n['t'] <= t), None)
            following = next((n for n in notes if n['lane'] == lane and n['t'] > t), None)
            if prev and t - prev['t'] - prev.get('hold', 0) < .22:
                continue
            if following and following['t'] - t < .22:
                continue
            hold = desired_hold
            if hold:
                if following:
                    hold = min(hold, following['t'] - t - .22)
                if hold < .5:
                    hold = 0.0
            options.append((hold > 0, -abs(lane - want), lane, round(max(0.0, hold), 3)))
        if not options:
            continue
        _, _, lane, hold = max(options)
        notes.append({'t': round(t, 4), 'lane': lane, 'hold': hold, 'drum': 'tom',
                      'source': SOURCE, 'melodyPitch': event['pitch'], 'melodyKind': event['kind']})
        notes.sort(key=lambda n: (n['t'], n['lane']))
        used_windows[window] = used_windows.get(window, 0) + 1
        added += 1
        holds += hold > 0
        stair = dict(t=t, pitch=event['pitch'], lane=lane, dir=direction, span=span)
    updated = dict(chart, notes=notes, noteCount=len(notes))
    return updated, {'removed_v1': len(chart['notes']) - len(base), 'new': added,
                     'represented': represented, 'holds': holds}


def main():
    write = '--write' in sys.argv[1:]
    titles = {arg for arg in sys.argv[1:] if not arg.startswith('--')}
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    chosen = [song for song in manifest if not titles or song['title'] in titles]
    if titles - {song['title'] for song in chosen}:
        raise SystemExit('Unknown song: ' + ', '.join(titles - {song['title'] for song in chosen}))
    for song in chosen:
        charts = {level: SONGS / song['charts'][level] for level in LEVELS}
        current = {level: json.loads(path.read_text(encoding='utf-8')) for level, path in charts.items()}
        stem = KEEP / Path(song['file']).stem
        vocal = load_stem(stem / 'vocals.wav')
        other = load_stem(stem / 'other.wav')
        spans = interludes(song, vocal, other)
        events = instrument_events(other, spans) if spans else []
        updates = {level: add_to_chart(current[level], song, spans, events, level) for level in LEVELS}
        summary = ' '.join(f'{level} {data[1]["removed_v1"]}→{data[1]["new"]} ({data[1]["holds"]} holds)'
                           for level, data in updates.items())
        print(f'{song["title"]}: {len(spans)} interludes {sum(b-a for a,b in spans):.0f}s, '
              f'{len(events)} pitched events; {summary}', flush=True)
        if write:
            BACKUP.mkdir(exist_ok=True)
            manifest_backup = BACKUP / 'songs.json'
            if not manifest_backup.exists():
                shutil.copy2(SONGS / 'songs.json', manifest_backup)
            for level, path in charts.items():
                backup = BACKUP / path.name
                if not backup.exists():
                    shutil.copy2(path, backup)
            for level, path in charts.items():
                path.write_text(json.dumps(updates[level][0], ensure_ascii=False, separators=(',', ':')),
                                encoding='utf-8', newline='')
    if write:
        import subprocess
        subprocess.run([sys.executable, str(ROOT / 'tools' / 'update-levels.py'), '--write'], check=True)


if __name__ == '__main__':
    main()
