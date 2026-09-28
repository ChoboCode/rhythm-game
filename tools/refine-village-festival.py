"""Polish the sustained '공' and a few sparse instrumental rushes.

Dry run: python -X utf8 tools/refine-village-festival.py
Write:   python -X utf8 tools/refine-village-festival.py --write

The two vocal holds were measured from the Demucs vocal stem. Instrumental
events were selected from the other stem only where independent onset and FFT
pitch checks passed. Existing notes are never moved or removed.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
BACKUP = ROOT / '_chart_backup_village_festival'
LEVELS = ('easy', 'normal', 'hard')

# Start at the consonant of the held final syllable. The pitch remains audible
# through the end of each hold; EASY releases before the next existing hold.
HOLDS = {
    'easy': ((58.634, 3, 2.35, 53), (119.117, 2, 1.85, 65)),
    'normal': ((58.634, 3, 2.35, 53), (119.117, 6, 2.30, 65)),
    'hard': ((58.634, 3, 2.35, 53), (119.117, 6, 2.30, 65)),
}

# Measured attacks in the 61.9-73.7 and 129.9-144.2 instrumental spans.
# Add only selected gaps between the existing dense pattern's notes.
FILL = (
    (64.494, 77), (64.912, 75),
    (68.525, 65), (69.148, 65),
    (72.442, 58), (73.255, 75),
    (133.443, 75),
    (136.269, 84), (136.675, 82),
    (140.808, 65), (141.502, 65),
)
NORMAL_FILL = {69.148, 72.442, 133.443, 136.269, 136.675, 141.502}


def safe_lane(notes, at, desired, max_distance=2):
    group = [n for n in notes if abs(n['t'] - at) < .0001]
    for lane in sorted(range(7), key=lambda x: (abs(x - desired), -x if desired >= 4 else x)):
        if abs(lane - desired) > max_distance or any(n['lane'] == lane for n in group):
            continue
        prev = next((n for n in reversed(notes) if n['lane'] == lane and n['t'] <= at), None)
        following = next((n for n in notes if n['lane'] == lane and n['t'] > at), None)
        if prev and at - prev['t'] - prev.get('hold', 0) < .22:
            continue
        if following and following['t'] - at < .22:
            continue
        return lane
    return None


def update_chart(chart, level):
    notes = list(chart['notes'])
    added_holds, added_fills = [], []
    for at, lane, duration, pitch in HOLDS[level]:
        if any(n.get('source') == 'festival-hold-v1' and abs(n['t'] - at) < .001 for n in notes):
            continue
        end = at + duration
        if any(n['lane'] == lane and n['t'] <= at and n['t'] + n.get('hold', 0) > at - .22
               for n in notes):
            raise SystemExit(f'{level}: held-note lane blocked before {at}')
        if any(n['lane'] == lane and at < n['t'] < end + .22 for n in notes):
            raise SystemExit(f'{level}: held-note lane blocked after {at}')
        note = {'t': at, 'lane': lane, 'hold': duration, 'drum': 'tom',
                'source': 'festival-hold-v1', 'melodyPitch': pitch}
        notes.append(note)
        notes.sort(key=lambda n: (n['t'], n['lane']))
        added_holds.append(note)
    if level != 'easy':
        for at, pitch in FILL:
            if level == 'normal' and at not in NORMAL_FILL:
                continue
            if any(n.get('drum') == 'tom' and abs(n['t'] - at) < .06 for n in notes):
                continue
            desired = max(0, min(6, round((pitch - 58) * 6 / 26)))
            lane = safe_lane(notes, at, desired)
            if lane is None:
                raise SystemExit(f'{level}: no playable lane for {at}')
            note = {'t': at, 'lane': lane, 'hold': 0.0, 'drum': 'tom',
                    'source': 'festival-fill-v1', 'melodyPitch': pitch,
                    'melodyKind': 'attack'}
            notes.append(note)
            notes.sort(key=lambda n: (n['t'], n['lane']))
            added_fills.append(note)
    return dict(chart, notes=notes, noteCount=len(notes)), added_holds, added_fills


def update_lyrics(lyrics):
    changed = []
    for line in lyrics['lines']:
        if not line['text'].endswith('주인공'):
            continue
        if abs(line['t'] - 54.72) < .1:
            end = 61.65
        elif abs(line['t'] - 115.2) < .1:
            end = 120.99  # next lyric line starts at 121.03
        else:
            continue
        if line['end'] != end:
            line['end'] = end
            line['words'][-1]['end'] = end
            changed.append(line['t'])
    return lyrics, changed


def main():
    write = '--write' in sys.argv[1:]
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    song = next(s for s in manifest if s['file'].endswith('_2_24.mp3') and s['title'].startswith('우리'))
    paths = [SONGS / song['charts'][level] for level in LEVELS]
    updates = []
    for level, path in zip(LEVELS, paths):
        updated, holds, fills = update_chart(json.loads(path.read_text(encoding='utf-8')), level)
        updates.append(updated)
        print(f'{level}: +{len(holds)} vocal holds; +{len(fills)} instrumental notes '
              + ', '.join(f'{n["t"]:.3f}/{n["lane"]}' for n in fills))
    lyric_path = SONGS / song['lyrics']
    lyrics, changed = update_lyrics(json.loads(lyric_path.read_text(encoding='utf-8')))
    print(f'lyric endings extended: {changed}; write={write}')
    if not write:
        return
    if not BACKUP.exists():
        BACKUP.mkdir()
        for path in [SONGS / 'songs.json', lyric_path, *paths]:
            shutil.copy2(path, BACKUP / path.name)
    for path, chart in zip(paths, updates):
        path.write_text(json.dumps(chart, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    if changed:
        lyric_path.write_text(json.dumps(lyrics, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'update-levels.py'), '--write'], check=True)


if __name__ == '__main__':
    main()
