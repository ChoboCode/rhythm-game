"""Repair collapsed/early Last Stage chorus words against the separated vocal.

The times were checked with focused English word transcription and vocal RMS.
Dry run: python -X utf8 tools/refine-last-stage-lyrics.py
Write:   python -X utf8 tools/refine-last-stage-lyrics.py --write
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'songs' / 'Last Stage_4_01.lyrics.json'
BACKUP = ROOT / '_chart_backup_20260929_polish' / PATH.name

# Line: (word starts, line end). A single sung Gloria can carry both printed
# chant words; the longer gap between repeats is kept instead of compressing
# the entire following lyric into a few tenths of a second.
TIMES = {
    13: ([75.00, 75.66, 75.90, 76.38, 76.56, 77.02], 77.72),
    14: ([78.12, 78.18, 78.88, 79.10, 79.72, 79.92, 80.28, 80.78], 81.32),
    15: ([81.70, 82.40, 82.62, 82.96, 83.50], 84.84),
    16: ([85.30, 85.72], 86.18),
    17: ([88.48, 91.42], 92.44),
    18: ([97.78, 98.10, 98.38, 98.62, 98.82, 98.98, 99.20, 99.38, 99.72, 100.06, 100.24], 100.58),
    19: ([101.12, 101.42, 101.62, 101.84, 102.08, 102.50, 102.80, 103.00, 103.34], 103.68),
    26: ([129.66, 129.76, 130.48, 130.66, 131.26, 131.48, 131.82, 132.32], 132.60),
    27: ([133.00, 133.72, 133.98, 134.28, 134.80], 136.54),
    28: ([136.90, 137.14], 137.72),
    29: ([140.02, 140.30], 140.84),
    41: ([210.62, 211.26, 211.48, 211.80, 212.32], 214.30),
    42: ([214.30, 214.64], 215.05),
    43: ([217.32, 217.78], 218.20),
    44: ([218.20, 219.32, 219.86, 220.08], 220.62),
    45: ([220.62], 220.80),
}


def refine(data):
    for i, (starts, end) in TIMES.items():
        line = data['lines'][i]
        if len(starts) != len(line['words']):
            raise SystemExit(f'line {i}: word count changed')
        if not all(a < b for a, b in zip(starts, [*starts[1:], end])):
            raise SystemExit(f'line {i}: invalid word times')
        line['t'], line['end'] = starts[0], end
        for k, word in enumerate(line['words']):
            word['t'] = starts[k]
            word['end'] = starts[k + 1] if k + 1 < len(starts) else end
        line.pop('estimated', None)
    data['timing'] = 'vocal-aligned-v3'
    data['resyncNote'] = ('Focused English word timestamps and separated-vocal energy; '
                          'corrected compressed and early chorus lines.')
    return data


def main():
    refined = refine(json.loads(PATH.read_text(encoding='utf-8')))
    print('retimed lines:', ', '.join(map(str, TIMES)), 'write=', '--write' in sys.argv)
    if '--write' in sys.argv:
        if not BACKUP.exists():
            BACKUP.parent.mkdir(exist_ok=True)
            BACKUP.write_bytes(PATH.read_bytes())
        PATH.write_text(json.dumps(refined, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
