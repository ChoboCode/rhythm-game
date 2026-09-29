"""Add a few measured instrumental attacks to sparse openings across the library.

Only openings with uncovered attacks receive notes. Existing notes stay intact.
Dry run: python -X utf8 tools/refine-song-intros.py
Write:   python -X utf8 tools/refine-song-intros.py --write
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
SOURCE = 'intro-motif-v1'
LEVELS = ('easy', 'normal', 'hard')
SPAN = (.15, 7.8)


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measured_events(song, refine, audit):
    path = Path(tempfile.gettempdir()) / 'rhythm-game-stems' / 'keep' / 'htdemucs' / Path(song['file']).stem / 'other.wav'
    y = refine.load_stem(path)[:int(8.1 * refine.SR)]
    flux_t, flux = audit.spectral_flux(y)
    env = np.sqrt(np.maximum(0, scipy.ndimage.uniform_filter1d(y * y, size=220)[::110]))
    rise = np.maximum(0, np.diff(env, prepend=env[0]))
    events = []
    for event in refine.instrument_events(y, (SPAN,)):
        if event['kind'] != 'attack' or event['strength'] < .7 or event['pitch'] < 60:
            continue
        probe = {'t': event['t'], 'melodyPitch': event['pitch'],
                 'melodyKind': 'attack', 'hold': 0}
        onset, pitch, _, lag = audit.audit_note(y, flux_t, flux, env, rise, probe)
        if onset and pitch and lag is not None and abs(lag) <= .05:
            events.append(event)
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


def update_chart(chart, events, level):
    base = [n for n in chart['notes'] if n.get('source') != SOURCE]
    notes = list(chart['notes'])
    max_add = {'easy': 3, 'normal': 4, 'hard': 5}[level]
    min_space = {'easy': .44, 'normal': .32, 'hard': .25}[level]
    chosen = []
    for event in sorted(events, key=lambda e: -e['strength']):
        t = event['t']
        if any(abs(n['t'] - t) < .12 for n in base if n['drum'] == 'tom'):
            continue
        if any(abs(e['t'] - t) < min_space for e in chosen):
            continue
        chosen.append(event)
        if len(chosen) == max_add:
            break
    added = []
    stair = None
    if events:
        low, high = np.percentile([e['pitch'] for e in events], [15, 85])
    for event in sorted(chosen, key=lambda e: e['t']):
        t, pitch = event['t'], event['pitch']
        if any(n.get('source') == SOURCE and n.get('melodyPitch') == pitch and
               abs(n['t'] - t) < .001 for n in notes):
            continue
        desired = int(np.clip(round(1 + 4 * (pitch - low) / max(3, high - low)), 0, 6))
        if stair and t - stair['t'] < 1.2 and pitch != stair['pitch']:
            desired = int(np.clip(stair['lane'] + (1 if pitch > stair['pitch'] else -1) *
                                  (2 if abs(pitch - stair['pitch']) >= 5 else 1), 0, 6))
        lane = safe_lane(notes, t, desired, level)
        if lane is None:
            continue
        note = {'t': t, 'lane': lane, 'hold': 0.0, 'drum': 'tom',
                'source': SOURCE, 'melodyPitch': pitch, 'melodyKind': 'attack'}
        notes.append(note)
        notes.sort(key=lambda n: (n['t'], n['lane']))
        added.append(note)
        stair = {'t': t, 'pitch': pitch, 'lane': lane}
    return dict(chart, notes=notes, noteCount=len(notes)), added


def main():
    write = '--write' in sys.argv[1:]
    titles = {arg for arg in sys.argv[1:] if not arg.startswith('--')}
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    refine = load_tool('refine-interludes.py', 'interlude_detector')
    audit = load_tool('verify-interlude-charts.py', 'signal_audit')
    totals = {level: 0 for level in LEVELS}
    changed = 0
    for song in manifest:
        if titles and song['title'] not in titles:
            continue
        events = measured_events(song, refine, audit)
        outputs = []
        counts = []
        for level in LEVELS:
            path = SONGS / song['charts'][level]
            chart, added = update_chart(json.loads(path.read_text(encoding='utf-8')), events, level)
            outputs.append((path, chart, bool(added)))
            counts.append(len(added))
            totals[level] += len(added)
        changed += any(counts)
        print(f'{song["title"]}: {len(events)} verified attacks; +{counts[0]}/{counts[1]}/{counts[2]}', flush=True)
        if write:
            BACKUP.mkdir(exist_ok=True)
            for path, chart, altered in outputs:
                if not altered:
                    continue
                target = BACKUP / path.name
                if not target.exists():
                    shutil.copy2(path, target)
                path.write_text(json.dumps(chart, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('changed songs:', changed, 'totals:', totals, 'write=', write)


if __name__ == '__main__':
    main()
