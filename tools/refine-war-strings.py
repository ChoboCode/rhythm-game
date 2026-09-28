"""Add the measured middle string-like lead phrases to War's saved charts.

Dry run: python -X utf8 tools/refine-war-strings.py
Write:   python -X utf8 tools/refine-war-strings.py --write

Onsets and pitches were checked in the Demucs other stem with CQT and an
independent waveform/STFT/FFT audit. Original notes remain byte-for-byte as
objects; this script only appends source-tagged notes and is idempotent.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
BACKUP = ROOT / '_chart_backup_war_strings'
SOURCE = 'war-strings-v1'
LEVELS = ('easy', 'normal', 'hard')

# Measured lead onsets in the other stem. The pitch steps at 95-98 s and
# 112-116 s are the clearest middle phrases. Long notes end before the line's
# next articulation and are shortened further when a lane needs to be free.
# (time, MIDI pitch, desired lane, hold seconds, included difficulties)
PHRASE = (
    (95.329, 67, 2, 0.0, 'nh'),
    (95.492, 69, 3, 0.0, 'nh'),
    (95.965, 67, 2, 0.0, 'enh'),
    (96.427, 74, 5, 0.0, 'enh'),
    (96.743, 73, 4, 0.0, 'nh'),
    (97.212, 70, 2, 0.0, 'enh'),
    (97.679, 69, 1, 1.0, 'enh'),
    (112.213, 67, 2, 0.0, 'enh'),
    (112.678, 70, 3, 0.54, 'enh'),
    (113.939, 67, 2, 0.0, 'enh'),
    (115.172, 73, 5, 0.75, 'enh'),
    (116.436, 65, 1, 0.0, 'nh'),
)
LANE_HINTS = {
    'easy': {97.212: 3, 97.679: 2},
    'normal': {97.212: 3, 97.679: 2},
}


def playable_lane(notes, at, desired, requested_hold, min_gap):
    options = []
    for lane in range(7):
        if abs(lane - desired) > 2:
            continue
        prev = next((n for n in reversed(notes) if n['lane'] == lane and n['t'] <= at), None)
        following = next((n for n in notes if n['lane'] == lane and n['t'] > at), None)
        if prev and at - prev['t'] - prev.get('hold', 0) < min_gap:
            continue
        if following and following['t'] - at < min_gap:
            continue
        hold = requested_hold
        if following and hold:
            hold = min(hold, following['t'] - at - min_gap)
        if requested_hold and hold < .5:
            continue
        shortened = bool(requested_hold and hold < requested_hold * .8)
        options.append((shortened, abs(lane - desired), -hold, lane, round(hold, 3)))
    if not options:
        return None
    _, _, _, lane, hold = min(options)
    return lane, hold


def update_chart(chart, level):
    notes = list(chart['notes'])
    added = []
    for at, pitch, desired, duration, difficulties in PHRASE:
        if level[0] not in difficulties:
            continue
        desired = LANE_HINTS.get(level, {}).get(at, desired)
        if any(n.get('source') == SOURCE and n.get('melodyPitch') == pitch
               and abs(n['t'] - at) <= .025 for n in notes):
            continue
        # Existing chart attacks within a few milliseconds already express
        # the beat; a second lane lets the player follow the lead contour.
        nearby = min((n['t'] for n in notes if abs(n['t'] - at) <= .015),
                     key=lambda t: abs(t - at), default=at)
        lane_hold = playable_lane(notes, nearby, desired, duration,
                                  {'easy': .22, 'normal': .20, 'hard': .14}[level])
        if lane_hold is None:
            raise SystemExit(f'{level}: no playable melody lane at {at:.3f}')
        lane, hold = lane_hold
        note = {'t': round(nearby, 4), 'lane': lane, 'hold': hold, 'drum': 'tom',
                'source': SOURCE, 'melodyPitch': pitch,
                'melodyKind': 'transition' if at == 95.492 else 'attack'}
        notes.append(note)
        notes.sort(key=lambda n: (n['t'], n['lane']))
        added.append(note)
    return dict(chart, notes=notes, noteCount=len(notes)), added


def main():
    write = '--write' in sys.argv[1:]
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    song = next(s for s in manifest if s['file'].startswith('War_'))
    paths = [SONGS / song['charts'][level] for level in LEVELS]
    updates = []
    for level, path in zip(LEVELS, paths):
        chart, added = update_chart(json.loads(path.read_text(encoding='utf-8')), level)
        updates.append(chart)
        print(f'{level}: +{len(added)} lead notes: ' + ', '.join(
              f'{n["t"]:.3f}/{n["lane"]}' + (f'~{n["hold"]:.2f}' if n['hold'] else '')
              for n in added))
    print(f'write={write}')
    if not write:
        return
    if not BACKUP.exists():
        BACKUP.mkdir()
        for path in [SONGS / 'songs.json', *paths]:
            shutil.copy2(path, BACKUP / path.name)
    for path, chart in zip(paths, updates):
        path.write_text(json.dumps(chart, ensure_ascii=False, separators=(',', ':')),
                        encoding='utf-8')
    subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'update-levels.py'),
                    '--write'], check=True)


if __name__ == '__main__':
    main()
