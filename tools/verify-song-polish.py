"""Check the 2026-09-29 song refinements against backups and stem audio.

Run: python -X utf8 tools/verify-song-polish.py
"""
import importlib.util
import json
from pathlib import Path
import tempfile

import numpy as np
import scipy.ndimage

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
BACKUP = ROOT / '_chart_backup_20260929_polish'
KEEP = Path(tempfile.gettempdir()) / 'rhythm-game-stems' / 'keep' / 'htdemucs'
SOURCES = {'stay-vocal-v1', 'cocktail-piano-v1', 'break-lead-v1', 'intro-motif-v1'}
LEVELS = ('easy', 'normal', 'hard')


def tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_lyrics(path, positions):
    lines = json.loads(path.read_text(encoding='utf-8'))['lines']
    for i in positions:
        line = lines[i]
        words = line['words']
        assert words[0]['t'] == line['t'] and words[-1]['end'] == line['end'], (path, i)
        assert all(a['end'] == b['t'] for a, b in zip(words, words[1:])), (path, i)
        assert all(w['t'] < w['end'] for w in words), (path, i)
        if 'segments' in line:
            segments = line['segments']
            assert ''.join(s['text'] for s in segments) == ''.join(w['text'] for w in words), (path, i)
            assert all(s['t'] < s['end'] for s in segments), (path, i)
    print(f'{path.name}: {len(positions)} measured lines valid')


def main():
    audit = tool('verify-interlude-charts.py', 'signal_audit')
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    indexed = {}
    counts = {source: 0 for source in SOURCES}
    preserved = 0
    for song in manifest:
        if song['title'] in ('Stay with me_ make me real', 'My Cocktail'):
            assert song.get('rests') == [], song['title']
        if song['title'] == 'Break It Down':
            assert len(song.get('drops', [])) == 1 and len(song['drops'][0]['hits']) == 3
        for level in LEVELS:
            path = SONGS / song['charts'][level]
            chart = json.loads(path.read_text(encoding='utf-8'))
            assert chart['noteCount'] == len(chart['notes']), path
            assert chart['notes'] == sorted(chart['notes'], key=lambda n: (n['t'], n['lane'])), path
            original = BACKUP / path.name
            if original.exists():
                before = json.loads(original.read_text(encoding='utf-8'))
                kept = [n for n in chart['notes'] if n.get('source') not in SOURCES]
                assert kept == before['notes'], f'{path.name}: old notes changed'
                preserved += len(kept)
            for n in chart['notes']:
                source = n.get('source')
                if source not in SOURCES:
                    continue
                counts[source] += 1
                if source == 'intro-motif-v1':
                    assert .15 <= n['t'] < 7.8, n
                if source == 'break-lead-v1':
                    assert not 165.744 <= n['t'] <= 168.834, n
                part = n.get('melodyStem', 'vocals' if source == 'stay-vocal-v1' else 'other')
                key = (song['file'], part, source, n['t'], n['melodyPitch'])
                indexed[key] = n
    print('original notes preserved:', preserved, 'added notes:', counts)

    grouped = {}
    for key, note in indexed.items():
        name, part, source, _, _ = key
        grouped.setdefault((name, part), []).append((source, note))
    tally = {source: [0, 0, 0] for source in SOURCES}
    for (name, part), items in grouped.items():
        path = KEEP / Path(name).stem / f'{part}.wav'
        y = audit.load_other(path)
        if all(source == 'intro-motif-v1' for source, _ in items):
            y = y[:int(8.1 * audit.SR)]
        flux_t, flux = audit.spectral_flux(y)
        env = np.sqrt(np.maximum(0, scipy.ndimage.uniform_filter1d(y * y, size=220)[::110]))
        rise = np.maximum(0, np.diff(env, prepend=env[0]))
        for source, note in items:
            onset, pitch, _, lag = audit.audit_note(y, flux_t, flux, env, rise, note)
            row = tally[source]
            row[0] += 1
            row[1] += bool(onset and lag is not None and abs(lag) <= .05)
            row[2] += bool(pitch)
    for source, (total, onset, pitch) in sorted(tally.items()):
        print(f'{source}: unique {total}, onset {onset}/{total}, pitch {pitch}/{total}')
        assert total and onset / total >= (.85 if source == 'stay-vocal-v1' else .99), source
        assert pitch / total >= (.85 if source == 'stay-vocal-v1' else .99), source

    stay = next(s for s in manifest if s['title'].startswith('Stay with me'))
    last = next(s for s in manifest if s['title'] == 'Last Stage')
    check_lyrics(SONGS / stay['lyrics'], [11, 12, 13, 29, 30, 31, 40, 41, 42])
    check_lyrics(SONGS / last['lyrics'], [13, 14, 15, 16, 17, 18, 19, 26, 27, 28, 29, 41, 42, 43, 44, 45])
    print('PASS: song polish')


if __name__ == '__main__':
    main()
