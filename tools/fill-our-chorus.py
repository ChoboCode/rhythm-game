"""Fill the six repeated title phrases of '오늘부터 우리' from the vocal stem.

Dry run: python -X utf8 tools/fill-our-chorus.py
Write:   python -X utf8 tools/fill-our-chorus.py --write

Times and MIDI pitches were checked against vocal onsets, pYIN stable pitch
runs, and a separate short-window FFT. Existing notes are never moved or
removed; a nearby pitched note represents the same sung note. The first write
backs up the three charts, lyrics, and manifest.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
BACKUP = ROOT / '_chart_backup_our_chorus'
SOURCE = 'vocal-chorus-v1'
LEVELS = ('easy', 'normal', 'hard')

# Each row follows the repeated vocal shape, with the final two sounds of
# '우리, 우리' kept even where the existing drum chart fills that beat.
PHRASES = (
    ((59.984, 64), (60.249, 67), (60.470, 69), (60.683, 62), (60.943, 69), (61.072, 71)),
    ((82.487, 64), (82.742, 67), (82.967, 69), (83.146, 62), (83.422, 69), (83.578, 71)),
    ((135.000, 64), (135.244, 67), (135.465, 69), (135.718, 69), (135.914, 69), (136.080, 71)),
    ((157.471, 64), (157.748, 67), (158.006, 69), (158.200, 69), (158.433, 69), (158.595, 71)),
    ((181.884, 64), (182.127, 67), (182.341, 69), (182.543, 62), (182.795, 69), (182.910, 71)),
    ((204.373, 64), (204.620, 67), (204.864, 69), (205.025, 62), (205.309, 69), (205.456, 71)),
)
PICK = {'easy': (0, 1, 3, 4), 'normal': (0, 1, 2, 3, 4), 'hard': (0, 1, 2, 3, 4, 5)}
PITCH_LANE = {62: 1, 64: 2, 67: 3, 69: 4, 71: 5}
MAX_CHORD = {'easy': 2, 'normal': 3, 'hard': 4}


def add_phrase_notes(chart, level):
    notes = list(chart['notes'])
    added = []
    represented = 0
    crowded = 0
    for phrase in PHRASES:
        for index in PICK[level]:
            t, pitch = phrase[index]
            if any(n.get('drum') == 'tom' and abs(n['t'] - t) <= .06 for n in notes):
                represented += 1
                continue
            nearest = min(notes, key=lambda n: abs(n['t'] - t))
            at = nearest['t'] if abs(nearest['t'] - t) <= .06 else t
            group = [n for n in notes if abs(n['t'] - at) < .0001]
            if len(group) >= MAX_CHORD[level]:
                crowded += 1
                continue
            desired = PITCH_LANE[pitch]
            place = None
            for lane in sorted(range(7), key=lambda k: (abs(k - desired), k)):
                if abs(lane - desired) > 2 or any(n['lane'] == lane for n in group):
                    continue
                before = next((n for n in reversed(notes) if n['lane'] == lane and n['t'] <= at), None)
                after = next((n for n in notes if n['lane'] == lane and n['t'] > at), None)
                if before and at - before['t'] - before.get('hold', 0) < .22:
                    continue
                if after and after['t'] - at < .22:
                    continue
                place = lane
                break
            if place is None:
                crowded += 1
                continue
            note = {'t': round(at, 4), 'lane': place, 'hold': 0.0, 'drum': 'tom',
                    'source': SOURCE, 'melodyPitch': pitch}
            notes.append(note)
            notes.sort(key=lambda n: (n['t'], n['lane']))
            added.append(note)
    return dict(chart, notes=notes, noteCount=len(notes)), added, represented, crowded


def correct_estimated_lyric(lyrics):
    lines = lyrics['lines']
    match = [line for line in lines if line['text'].startswith(lyrics['title'])
             and 181 < line['t'] < 183]
    if len(match) != 1:
        raise SystemExit('Expected one estimated title phrase near 182s')
    line = match[0]
    if not line.get('estimated'):
        return lyrics, False
    # The previous estimated line ended at 182.61s; the separated vocal keeps
    # singing through about 183.0s, with two clear '우리' entries at 182.54/182.79.
    line['t'], line['end'] = 181.58, 183.00
    for word, start, end in zip(line['words'], (181.58, 182.54, 182.79),
                                 (182.54, 182.79, 183.00)):
        word['t'], word['end'] = start, end
    del line['estimated']
    return lyrics, True


def main():
    write = '--write' in sys.argv[1:]
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    song = next(s for s in manifest if s['file'].endswith('_3_41.mp3') and s.get('lyrics'))
    paths = [SONGS / song['charts'][level] for level in LEVELS]
    lyric_path = SONGS / song['lyrics']
    updates = []
    for level, path in zip(LEVELS, paths):
        chart = json.loads(path.read_text(encoding='utf-8'))
        updated, added, represented, crowded = add_phrase_notes(chart, level)
        updates.append(updated)
        print(f'{level}: +{len(added)} voice notes, {represented} already pitched, '
              f'{crowded} blocked; ' + ', '.join(f'{n["t"]:.3f}/{n["melodyPitch"]}' for n in added))
    lyric = json.loads(lyric_path.read_text(encoding='utf-8'))
    lyric, corrected = correct_estimated_lyric(lyric)
    print(f'estimated 182s lyric corrected: {corrected}; write={write}')
    if not write:
        return
    if not BACKUP.exists():
        BACKUP.mkdir()
        for path in [SONGS / 'songs.json', lyric_path, *paths]:
            shutil.copy2(path, BACKUP / path.name)
    for path, chart in zip(paths, updates):
        path.write_text(json.dumps(chart, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    if corrected:
        lyric_path.write_text(json.dumps(lyric, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'update-levels.py'), '--write'], check=True)


if __name__ == '__main__':
    main()
