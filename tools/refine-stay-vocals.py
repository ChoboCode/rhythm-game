"""Align Stay with me's repeated vocal phrases and fill missing syllable notes.

Dry run: python -X utf8 tools/refine-stay-vocals.py
Write:   python -X utf8 tools/refine-stay-vocals.py --write

The phrase starts were checked against the separated vocal waveform, pYIN,
and focused Whisper word timing. Existing chart notes remain intact.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
BACKUP = ROOT / '_chart_backup_20260929_polish'
SOURCE = 'stay-vocal-v1'
LEVELS = ('easy', 'normal', 'hard')

# line index: (start of each whitespace-delimited word, end of line)
TIMES = {
    11: ([50.46, 50.94, 51.80, 52.196, 52.450, 52.730], 54.001),
    12: ([54.001, 54.526, 55.438, 55.853, 56.620, 56.860, 57.880, 58.060], 58.870),
    13: ([58.870, 59.510, 60.030, 60.560, 61.100, 61.590, 61.840, 62.100, 62.860], 63.180),
    29: ([103.10, 103.513, 104.400, 104.560, 105.017, 105.289], 106.581),
    30: ([106.581, 107.126, 108.005, 108.469, 109.160, 109.520, 110.340, 110.620], 111.500),
    31: ([111.500, 111.940, 112.640, 113.140, 113.700, 114.170, 114.560, 114.960, 115.720], 116.000),
    40: ([152.842, 153.331, 153.874, 154.205, 154.740, 155.160, 156.100, 156.420], 157.200),
    41: ([157.200, 157.640, 158.640, 158.860, 159.380, 159.870, 160.120, 160.660, 161.160], 161.660),
    42: ([161.660, 162.030, 162.240, 162.720, 163.120, 163.380], 163.980),
}

# Per-syllable start times for "따라 하는가" (word indexes 4 and 5).
FOLLOW = {
    11: ([52.450, 52.584], [52.730, 53.031, 53.458]),
    29: ([105.017, 105.153], [105.289, 105.411, 106.029]),
}
# Per-syllable starts in "나도 숨을 쉬고 싶어" (first four words).
BREATH = {
    12: ([54.001, 54.260], [54.526, 54.802], [55.438, 55.603], [55.853, 56.239]),
    30: ([106.581, 106.862], [107.126, 107.359], [108.005, 108.301], [108.469, 108.777]),
    40: ([152.842, 153.051], [153.331, 153.709], [153.874, 154.016], [154.205, 154.410]),
}

# Vocal pYIN notes (MIDI); weaker syllables use the adjacent stable pitch.
# Audio attacks are retained even when an existing drum note plays there.
EVENTS = (
    (52.450, 57), (52.584, 59), (52.730, 57), (53.031, 61), (53.458, 64),
    (54.001, 66), (54.260, 68), (54.526, 68), (54.802, 71),
    (55.438, 66), (55.603, 66), (55.853, 71), (56.239, 71),
    (105.017, 57), (105.153, 59), (105.289, 57), (105.411, 59), (106.029, 64),
    (106.581, 66), (106.862, 68), (107.126, 69), (107.359, 71),
    (108.005, 66), (108.301, 66), (108.469, 71), (108.777, 71),
    (152.842, 69), (153.051, 71), (153.331, 71), (153.709, 66),
    (153.874, 66), (154.016, 66), (154.205, 71), (154.410, 72),
)


def retime(data):
    lines = data['lines']
    changed = []
    for index, (starts, end) in TIMES.items():
        line = lines[index]
        words = line['words']
        if len(words) != len(starts):
            raise SystemExit(f'line {index}: expected {len(starts)} words, found {len(words)}')
        before = (line['t'], line['end'], [w['t'] for w in words])
        line['t'], line['end'] = starts[0], end
        for i, word in enumerate(words):
            word['t'] = starts[i]
            word['end'] = starts[i + 1] if i + 1 < len(words) else end
        if before != (line['t'], line['end'], [w['t'] for w in words]):
            changed.append(index)
    for index in (*FOLLOW, *BREATH):
        line = lines[index]
        splits = {}
        if index in FOLLOW:
            splits = dict(zip((4, 5), FOLLOW[index]))
        else:
            splits = dict(enumerate(BREATH[index]))
        segments = []
        for i, word in enumerate(line['words']):
            if i not in splits:
                segments.append(dict(word))
                continue
            pieces = [*word['text']]
            starts = splits[i]
            if len(pieces) == len(starts) + 1 and not pieces[-1].isalnum():
                pieces[-2:] = [''.join(pieces[-2:])]
            if len(pieces) != len(starts):
                raise SystemExit(f'line {index}, word {i}: syllable count changed')
            for k, piece in enumerate(pieces):
                segments.append({'text': piece, 't': starts[k],
                                 'end': starts[k + 1] if k + 1 < len(starts) else word['end']})
        line['segments'] = segments
    return data, changed


def playable_lane(notes, at, desired, level):
    gap = {'easy': .13, 'normal': .12, 'hard': .105}[level]
    for lane in sorted(range(7), key=lambda x: (abs(x - desired), x)):
        prev = next((n for n in reversed(notes) if n['lane'] == lane and n['t'] <= at), None)
        following = next((n for n in notes if n['lane'] == lane and n['t'] > at), None)
        if prev and at - prev['t'] - prev.get('hold', 0) < gap:
            continue
        if following and following['t'] - at < gap:
            continue
        return lane
    return None


def update_chart(chart, level):
    notes = list(chart['notes'])
    added = []
    represented = 0
    for at, pitch in EVENTS:
        if any(n.get('source') == SOURCE and abs(n['t'] - at) < .001 for n in notes):
            continue
        if any(n.get('drum') == 'tom' and abs(n['t'] - at) <= .055 for n in notes):
            represented += 1
            continue
        desired = max(0, min(6, round((pitch - 57) * 6 / 21)))
        lane = playable_lane(notes, at, desired, level)
        if lane is None:
            raise SystemExit(f'{level}: no playable lane at {at:.3f}')
        note = {'t': at, 'lane': lane, 'hold': 0.0, 'drum': 'tom', 'source': SOURCE,
                'melodyPitch': pitch, 'melodyKind': 'attack'}
        notes.append(note)
        notes.sort(key=lambda n: (n['t'], n['lane']))
        added.append(note)
    return dict(chart, notes=notes, noteCount=len(notes)), added, represented


def main():
    write = '--write' in sys.argv[1:]
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    song = next(s for s in manifest if s['file'].startswith('Stay with me_'))
    lyrics_path = SONGS / song['lyrics']
    data, changed = retime(json.loads(lyrics_path.read_text(encoding='utf-8')))
    updates = []
    for level in LEVELS:
        path = SONGS / song['charts'][level]
        chart, added, represented = update_chart(json.loads(path.read_text(encoding='utf-8')), level)
        updates.append((path, chart))
        print(f'{level}: +{len(added)}, existing melody hits {represented}: ' +
              ', '.join(f'{n["t"]:.3f}/{n["lane"]}' for n in added))
    print('retimed lines:', changed, 'write=', write)
    if not write:
        return
    BACKUP.mkdir(exist_ok=True)
    for path in [lyrics_path, *(p for p, _ in updates)]:
        target = BACKUP / path.name
        if not target.exists():
            target.write_bytes(path.read_bytes())
    lyrics_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for path, chart in updates:
        path.write_text(json.dumps(chart, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    main()
