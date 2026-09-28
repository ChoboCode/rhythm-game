"""Remove generated interlude presses whose instrument energy is fading.

Dry run: python -X utf8 tools/prune-weak-interlude-notes.py [song title ...]
Write:   python -X utf8 tools/prune-weak-interlude-notes.py [song title ...] --write

Keeps every original and melody-add-v1 note. The first write saves the current
interlude charts in _chart_backup_interlude_v2_audit. This is a small final
polish after refine-interludes.py, which otherwise recreates these candidates.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import scipy.ndimage

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_interlude', ROOT / 'tools' / 'verify-interlude-charts.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
BACKUP = ROOT / '_chart_backup_interlude_v2_audit'


def main():
    write = '--write' in sys.argv[1:]
    songs = json.loads((verify.SONGS / 'songs.json').read_text(encoding='utf-8'))
    titles = {arg for arg in sys.argv[1:] if not arg.startswith('--')}
    if titles - {song['title'] for song in songs}:
        raise SystemExit('Unknown song: ' + ', '.join(titles - {song['title'] for song in songs}))
    if write and not BACKUP.exists():
        BACKUP.mkdir()
        shutil.copy2(verify.SONGS / 'songs.json', BACKUP / 'songs.json')
        for song in songs:
            for level in verify.LEVELS:
                path = verify.SONGS / song['charts'][level]
                shutil.copy2(path, BACKUP / path.name)
    total = 0
    for song in songs:
        if titles and song['title'] not in titles:
            continue
        y = verify.load_other(verify.KEEP / Path(song['file']).stem / 'other.wav')
        flux_t, flux = verify.spectral_flux(y)
        envelope = np.sqrt(np.maximum(0, scipy.ndimage.uniform_filter1d(y * y, size=220)[::110]))
        rise = np.maximum(0, np.diff(envelope, prepend=envelope[0]))
        decisions = {}
        for level in verify.LEVELS:
            path = verify.SONGS / song['charts'][level]
            chart = json.loads(path.read_text(encoding='utf-8'))
            kept = []
            removed = []
            for note in chart['notes']:
                if note.get('source') != 'interlude-v2':
                    kept.append(note)
                    continue
                key = (note['t'], note['melodyPitch'], note['melodyKind'], note['hold'])
                if key not in decisions:
                    onset, _, _, _ = verify.audit_note(y, flux_t, flux, envelope, rise, note)
                    t, pitch = note['t'], note['melodyPitch']
                    before = verify.harmonic_energy(y, t - .12, pitch, window=2048)
                    after = verify.harmonic_energy(y, t + .10, pitch, window=2048)
                    # A new key press during a steep decay has no independent
                    # attack and does not feel like the sampled instrument.
                    decisions[key] = not onset and after < before * .5
                if decisions[key]:
                    removed.append(note)
                else:
                    kept.append(note)
            if removed:
                total += len(removed)
                print(f'{song["title"]} {level}: remove {len(removed)} at '
                      + ', '.join(f'{n["t"]:.3f}s/{n["melodyPitch"]}' for n in removed), flush=True)
                if write:
                    chart['notes'] = kept
                    chart['noteCount'] = len(kept)
                    path.write_text(json.dumps(chart, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'TOTAL removed {total}; write={write}')


if __name__ == '__main__':
    main()
