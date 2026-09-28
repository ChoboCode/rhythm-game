"""Independently audit War's new middle melody notes and chart preservation.

Run after refine-war-strings.py --write:
    python -X utf8 tools/verify-war-strings.py
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import numpy as np
import scipy.ndimage

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
BACKUP = ROOT / '_chart_backup_war_strings'
SOURCE = 'war-strings-v1'
LEVELS = ('easy', 'normal', 'hard')

spec = importlib.util.spec_from_file_location('audio_audit', ROOT / 'tools' /
                                               'verify-interlude-charts.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def main():
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    song = next(s for s in manifest if s['file'].startswith('War_'))
    stem = Path(tempfile.gettempdir()) / 'rhythm-game-stems' / 'keep' / 'htdemucs' / 'War_2_49' / 'other.wav'
    y = audit.load_other(stem)
    flux_t, flux = audit.spectral_flux(y)
    envelope = np.sqrt(np.maximum(0, scipy.ndimage.uniform_filter1d(y * y, size=220)[::110]))
    rise = np.maximum(0, np.diff(envelope, prepend=envelope[0]))
    problems = []
    seen = {}
    counts = {}
    for level in LEVELS:
        name = song['charts'][level]
        chart = json.loads((SONGS / name).read_text(encoding='utf-8'))
        previous = json.loads((BACKUP / name).read_text(encoding='utf-8'))
        old = [n for n in chart['notes'] if n.get('source') != SOURCE]
        added = [n for n in chart['notes'] if n.get('source') == SOURCE]
        counts[level] = len(added)
        if old != previous['notes']:
            problems.append(level + ': preexisting notes changed')
        if chart['noteCount'] != len(chart['notes']):
            problems.append(level + ': noteCount differs')
        lane_end = [-1.0] * 7
        for note in chart['notes']:
            lane = note['lane']
            if note['t'] < lane_end[lane] + .059:
                problems.append(f'{level}: overlapping lane {lane} at {note["t"]:.3f}')
            lane_end[lane] = note['t'] + note.get('hold', 0)
        for note in added:
            key = (note['t'], note['melodyPitch'], note['melodyKind'], note['hold'])
            if key not in seen:
                seen[key] = audit.audit_note(y, flux_t, flux, envelope, rise, note)
            onset, pitch, sustained, lag = seen[key]
            if not onset or not pitch or not sustained:
                problems.append(f'{level}: weak signal at {note["t"]:.3f}: '
                                f'onset={onset}, pitch={pitch}, hold={sustained}')
            if lag is not None and abs(lag) > .03:
                problems.append(f'{level}: onset offset {lag:.3f}s at {note["t"]:.3f}')
        print(f'{level}: {len(added)} added, {sum(n["hold"] > 0 for n in added)} holds')
    if counts != {'easy': 8, 'normal': 12, 'hard': 12}:
        problems.append(f'unexpected counts: {counts}')
    if problems:
        print('ERROR:', *problems, sep='\n', file=sys.stderr)
        raise SystemExit(1)
    print(f'PASS: {sum(counts.values())} notes; all independent onset, pitch, '
          f'hold and lane checks; original notes preserved')


if __name__ == '__main__':
    main()
