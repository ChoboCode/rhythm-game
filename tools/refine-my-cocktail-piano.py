"""Add measured piano-like attacks to My Cocktail's instrumental phrases.

Dry run: python -X utf8 tools/refine-my-cocktail-piano.py
Write:   python -X utf8 tools/refine-my-cocktail-piano.py --write
"""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np
import scipy.ndimage

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
BACKUP = ROOT / '_chart_backup_20260929_polish'
SOURCE = 'cocktail-piano-v1'
LEVELS = ('easy', 'normal', 'hard')
SPANS = ((.2, 11.9), (74.8, 84.7), (139.9, 159.7), (223.5, 245.0))


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measured_events(song):
    refine = load_tool('refine-interludes.py', 'interlude_detector')
    audit = load_tool('verify-interlude-charts.py', 'signal_audit')
    path = Path(tempfile.gettempdir()) / 'rhythm-game-stems' / 'keep' / 'htdemucs' / Path(song['file']).stem / 'other.wav'
    y = refine.load_stem(path)
    flux_t, flux = audit.spectral_flux(y)
    envelope = np.sqrt(np.maximum(0, scipy.ndimage.uniform_filter1d(y * y, size=220)[::110]))
    rise = np.maximum(0, np.diff(envelope, prepend=envelope[0]))
    valid = []
    for event in refine.instrument_events(y, SPANS):
        if event['kind'] != 'attack' or event['pitch'] < 61 or event['strength'] < .7:
            continue
        note = {'t': event['t'], 'melodyPitch': event['pitch'], 'melodyKind': 'attack', 'hold': 0.0}
        onset, pitch, _, lag = audit.audit_note(y, flux_t, flux, envelope, rise, note)
        if onset and pitch and lag is not None and abs(lag) <= .05:
            valid.append(event)
    return valid


def safe_lane(notes, at, desired, level):
    gap = {'easy': .22, 'normal': .17, 'hard': .14}[level]
    for lane in sorted(range(7), key=lambda x: (abs(x - desired), x)):
        if abs(lane - desired) > 2:
            continue
        prev = next((n for n in reversed(notes) if n['lane'] == lane and n['t'] <= at), None)
        following = next((n for n in notes if n['lane'] == lane and n['t'] > at), None)
        if prev and at - prev['t'] - prev.get('hold', 0) < gap:
            continue
        if following and following['t'] - at < gap:
            continue
        return lane
    return None


def update_chart(chart, events, level):
    base = [n for n in chart['notes'] if n.get('source') != SOURCE]
    notes = list(chart['notes'])
    min_space = {'easy': .49, 'normal': .30, 'hard': .24}[level]
    per_4s = {'easy': 3, 'normal': 5, 'hard': 5}[level]
    gap_from_melody = {'easy': .13, 'normal': .11, 'hard': .09}[level]
    chosen, windows = [], {}
    for event in sorted(events, key=lambda e: -e['strength']):
        t = event['t']
        if any(abs(n['t'] - t) < gap_from_melody for n in base if n['drum'] == 'tom'):
            continue
        bucket = int(t // 4)
        if windows.get(bucket, 0) >= per_4s or any(abs(e['t'] - t) < min_space for e in chosen):
            continue
        chosen.append(event)
        windows[bucket] = windows.get(bucket, 0) + 1
    added = []
    stair = None
    for event in sorted(chosen, key=lambda e: e['t']):
        t, pitch, span = event['t'], event['pitch'], event['span']
        if any(n.get('source') == SOURCE and n.get('melodyPitch') == pitch and
               abs(n['t'] - t) < .001 for n in notes):
            continue
        phrase = [e['pitch'] for e in events if e['span'] == span]
        low, high = np.percentile(phrase, [15, 85])
        desired = int(np.clip(round(1 + 4 * (pitch - low) / max(3, high - low)), 0, 6))
        if stair and stair['span'] == span and t - stair['t'] < 1.0:
            delta = pitch - stair['pitch']
            if delta:
                desired = int(np.clip(stair['lane'] + (1 if delta > 0 else -1) *
                                      (2 if abs(delta) >= 5 else 1), 0, 6))
            else:
                desired = stair['lane']
        lane = safe_lane(notes, t, desired, level)
        if lane is None:
            continue
        note = {'t': t, 'lane': lane, 'hold': 0.0, 'drum': 'tom', 'source': SOURCE,
                'melodyPitch': pitch, 'melodyKind': 'attack'}
        notes.append(note)
        notes.sort(key=lambda n: (n['t'], n['lane']))
        added.append(note)
        stair = {'t': t, 'pitch': pitch, 'lane': lane, 'span': span}
    return dict(chart, notes=notes, noteCount=len(notes)), added


def main():
    write = '--write' in sys.argv[1:]
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    song = next(s for s in manifest if s['file'].startswith('My Cocktail_'))
    events = measured_events(song)
    print('validated instrument attacks:', len(events))
    updates = []
    for level in LEVELS:
        path = SONGS / song['charts'][level]
        chart, added = update_chart(json.loads(path.read_text(encoding='utf-8')), events, level)
        updates.append((path, chart))
        by_span = [sum(a <= n['t'] < b for n in added) for a, b in SPANS]
        print(f'{level}: +{len(added)} piano notes by phrase {by_span}')
    print('write=', write)
    if not write:
        return
    BACKUP.mkdir(exist_ok=True)
    for path, chart in updates:
        target = BACKUP / path.name
        if not target.exists():
            shutil.copy2(path, target)
        path.write_text(json.dumps(chart, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    main()
