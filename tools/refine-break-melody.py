"""Add audible lead attacks to Break It Down without replacing saved notes.

The instrumental intro and sung phrases are detected separately. Candidates
must pass an independent waveform/STFT onset and pitch audit before charting.
Dry run: python -X utf8 tools/refine-break-melody.py
Write:   python -X utf8 tools/refine-break-melody.py --write
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
SOURCE = 'break-lead-v1'
LEVELS = ('easy', 'normal', 'hard')
SPANS = {
    'other': ((.2, 23.9), (64, 65.7), (69.8, 71.3), (81, 85.6),
              (132, 142.8), (155, 164.2), (172, 183.9)),
    'vocals': ((26.0, 60.0), (66, 80.8), (85.8, 115.2),
               (125, 132), (143, 155), (166, 171.8), (184, 199.5)),
}


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measured_events(song):
    refine = load_tool('refine-interludes.py', 'interlude_detector')
    audit = load_tool('verify-interlude-charts.py', 'signal_audit')
    stem = Path(tempfile.gettempdir()) / 'rhythm-game-stems' / 'keep' / 'htdemucs' / Path(song['file']).stem
    events = []
    for part, spans in SPANS.items():
        y = refine.load_stem(stem / f'{part}.wav')
        flux_t, flux = audit.spectral_flux(y)
        env = np.sqrt(np.maximum(0, scipy.ndimage.uniform_filter1d(y * y, size=220)[::110]))
        rise = np.maximum(0, np.diff(env, prepend=env[0]))
        total = 0
        for event in refine.instrument_events(y, spans):
            if event['kind'] != 'attack' or event['strength'] < (.7 if part == 'other' else .62):
                continue
            if part == 'vocals' and event['pitch'] < 59:
                continue
            probe = {'t': event['t'], 'melodyPitch': event['pitch'],
                     'melodyKind': 'attack', 'hold': 0}
            onset, pitch, _, lag = audit.audit_note(y, flux_t, flux, env, rise, probe)
            if not (onset and pitch and lag is not None and abs(lag) <= .05):
                continue
            events.append(dict(event, part=part))
            total += 1
        print(f'{part}: {total} validated attacks')
    return events


def safe_lane(notes, t, desired, level):
    gap = {'easy': .20, 'normal': .17, 'hard': .14}[level]
    for lane in sorted(range(7), key=lambda x: (abs(x - desired), x)):
        if abs(lane - desired) > 2:
            continue
        prev = next((n for n in reversed(notes) if n['lane'] == lane and n['t'] <= t), None)
        following = next((n for n in notes if n['lane'] == lane and n['t'] > t), None)
        if prev and t - prev['t'] - prev.get('hold', 0) < gap:
            continue
        if following and following['t'] - t < gap:
            continue
        return lane
    return None


def in_drop(t, song):
    return any(drop.get('from', min(drop['hits']) - .65) <= t <= max(drop['hits']) + .25
               for drop in song.get('drops', []))


def update_chart(chart, events, level, song):
    base = [n for n in chart['notes'] if n.get('source') != SOURCE]
    notes = [*base, *(n for n in chart['notes']
                      if n.get('source') == SOURCE and not in_drop(n['t'], song))]
    notes.sort(key=lambda n: (n['t'], n['lane']))
    min_space = {'easy': .43, 'normal': .30, 'hard': .24}[level]
    per_4s = {'easy': 2, 'normal': 3, 'hard': 4}[level]
    near_melody = {'easy': .125, 'normal': .11, 'hard': .095}[level]
    chosen, windows = [], {}
    for event in sorted(events, key=lambda e: -e['strength']):
        t = event['t']
        if in_drop(t, song):
            continue
        if any(abs(n['t'] - t) < near_melody for n in base if n['drum'] == 'tom'):
            continue
        bucket = (event['part'], int(t // 4))
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
        phrase = [e['pitch'] for e in events if e['part'] == event['part'] and e['span'] == span]
        low, high = np.percentile(phrase, [15, 85])
        desired = int(np.clip(round(1 + 4 * (pitch - low) / max(3, high - low)), 0, 6))
        key = (event['part'], span)
        if stair and stair['key'] == key and t - stair['t'] < 1.2:
            delta = pitch - stair['pitch']
            if delta:
                desired = int(np.clip(stair['lane'] + (1 if delta > 0 else -1) *
                                      (2 if abs(delta) >= 5 else 1), 0, 6))
        lane = safe_lane(notes, t, desired, level)
        if lane is None:
            continue
        note = {'t': t, 'lane': lane, 'hold': 0.0, 'drum': 'tom',
                'source': SOURCE, 'melodyPitch': pitch, 'melodyKind': 'attack',
                'melodyStem': event['part']}
        notes.append(note)
        notes.sort(key=lambda n: (n['t'], n['lane']))
        added.append(note)
        stair = {'t': t, 'pitch': pitch, 'lane': lane, 'key': key}
    return dict(chart, notes=notes, noteCount=len(notes)), added


def main():
    write = '--write' in sys.argv[1:]
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    song = next(s for s in manifest if s['file'].startswith('Break It Down_'))
    events = measured_events(song)
    print('total validated:', len(events))
    updates = []
    for level in LEVELS:
        path = SONGS / song['charts'][level]
        chart, added = update_chart(json.loads(path.read_text(encoding='utf-8')), events, level, song)
        updates.append((path, chart))
        print(f'{level}: +{len(added)} lead notes ({sum(n["melodyStem"] == "vocals" for n in added)} vocal)')
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
