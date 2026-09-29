"""Independent signal audit of interlude-v2 notes against the Demucs other stem.

Uses a linear-frequency STFT and waveform energy, rather than the generator's
CQT pitch track and onset picker. Checks original-note preservation, timing,
pitch evidence, audible holds, and playable lane gaps.
    python -X utf8 tools/verify-interlude-charts.py [song title ...]
"""
import json
from math import gcd
from pathlib import Path
import sys
import tempfile

import librosa
import numpy as np
import scipy.signal
import scipy.ndimage
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / 'songs'
ORIGINAL = ROOT / '_chart_backup_melody_add'
KEEP = Path(tempfile.gettempdir()) / 'rhythm-game-stems' / 'keep' / 'htdemucs'
SR = 22050
LEVELS = ('easy', 'normal', 'hard')


def load_other(path):
    y, sr = sf.read(path, dtype='float32')
    if y.ndim == 2:
        y = y.mean(axis=1)
    if sr != SR:
        common = gcd(sr, SR)
        y = scipy.signal.resample_poly(y, SR // common, sr // common)
    return np.asarray(y, dtype=np.float32)


def spectral_flux(y):
    frequency, times, z = scipy.signal.stft(y, fs=SR, nperseg=1024,
                                             noverlap=768, boundary=None)
    # Include low brass/keys and bright lead attacks; other.wav is already
    # separated from the drum stem, so a narrow midrange would miss them.
    band = (frequency >= 90) & (frequency <= 8500)
    magnitude = np.log1p(np.abs(z[band]) * 100)
    flux = np.r_[0, np.maximum(0, np.diff(magnitude, axis=1)).sum(axis=0)]
    return times, flux


def harmonic_energy(y, t, midi, window=4096):
    a = max(0, int((t - .045) * SR))
    b = min(len(y), a + window)
    part = y[a:b]
    if len(part) < 1024:
        return 0.0
    spectrum = np.abs(np.fft.rfft(part * np.hanning(len(part)), n=8192))
    hz = librosa.midi_to_hz(midi)
    total = 0.0
    for multiple, weight in ((1, 1), (2, .55), (3, .25)):
        k = round(hz * multiple * 8192 / SR)
        total += weight * np.max(spectrum[max(0, k - 1):k + 2])
    return float(total)


def audit_note(y, flux_t, flux, envelope, rise, note):
    t, midi = note['t'], note['melodyPitch']
    a = int(np.searchsorted(flux_t, t - .035))
    b = int(np.searchsorted(flux_t, t + .05))
    piece = flux[max(0, a):max(a + 1, b)]
    peak_index = max(0, a) + int(np.argmax(piece))
    local = float(flux[peak_index])
    lag = float(flux_t[peak_index] - t)
    near = flux[max(0, a - 70):min(len(flux), b + 70)]
    baseline = float(np.median(near)) if len(near) else 0
    attack = local > baseline * 1.35 and local > .001
    # A stable-timbre pluck can have little spectral novelty while still
    # producing a sharp level rise in the separated instrument waveform.
    j = int(t * SR / 110)
    rise_slice = rise[max(0, j - 7):min(len(rise), j + 8)]
    rise_index = max(0, j - 7) + int(np.argmax(rise_slice))
    amplitude_rise = float(rise[rise_index])
    level = float(np.median(envelope[max(0, j - 20):min(len(envelope), j + 20)]))
    wave_attack = amplitude_rise > .003 and amplitude_rise > .1 * (level + .005)
    if not attack and wave_attack:
        lag = rise_index * 110 / SR - t
    attack = attack or wave_attack
    # Inspect the first ~110 ms after the note. A 4096-sample window ran past
    # the next 16th-note attack in piano runs and measured that later pitch.
    post = harmonic_energy(y, t + .065, midi, window=2048)
    neighbor = np.median([harmonic_energy(y, t + .065, midi + shift, window=2048)
                          for shift in (-4, -3, -2, 2, 3, 4)])
    pitch = post > neighbor * 1.15
    if note['melodyKind'] == 'transition':
        before = harmonic_energy(y, t - .12, midi, window=2048)
        after = harmonic_energy(y, t + .10, midi, window=2048)
        attack = after > before * 1.1
        lag = None
    hold = True
    if note['hold'] > 0:
        held_start = harmonic_energy(y, t + .11, midi)
        later = harmonic_energy(y, t + min(note['hold'] * .8, note['hold'] - .12), midi,
                                window=4096)
        hold = later > held_start * .24
    return attack, pitch, hold, lag


def main():
    titles = set(sys.argv[1:])
    manifest = json.loads((SONGS / 'songs.json').read_text(encoding='utf-8'))
    selected = [song for song in manifest if not titles or song['title'] in titles]
    if titles - {song['title'] for song in selected}:
        raise SystemExit('Unknown song: ' + ', '.join(titles - {song['title'] for song in selected}))
    counts = {'notes': 0, 'attack': 0, 'pitch': 0, 'holds': 0, 'held': 0}
    attack_lags = []
    problems = []
    for song in selected:
        stem = KEEP / Path(song['file']).stem / 'other.wav'
        y = load_other(stem)
        flux_t, flux = spectral_flux(y)
        envelope = np.sqrt(np.maximum(0, scipy.ndimage.uniform_filter1d(y * y, size=220)[::110]))
        rise = np.maximum(0, np.diff(envelope, prepend=envelope[0]))
        unique = {}
        row = {'notes': 0, 'attack': 0, 'pitch': 0, 'holds': 0, 'held': 0}
        for level in LEVELS:
            name = song['charts'][level]
            chart = json.loads((SONGS / name).read_text(encoding='utf-8'))
            original = json.loads((ORIGINAL / name).read_text(encoding='utf-8'))
            kept = [n for n in chart['notes'] if n.get('source') not in
                    ('melody-add-v1', 'interlude-v2', 'vocal-chorus-v1',
                     'festival-hold-v1', 'festival-fill-v1', 'war-strings-v1',
                     'stay-vocal-v1', 'cocktail-piano-v1',
                     'break-lead-v1', 'intro-motif-v1')]
            if kept != original['notes']:
                problems.append(name + ': original notes changed')
            if chart['noteCount'] != len(chart['notes']):
                problems.append(name + ': noteCount differs')
            lane_end = [-1.0] * 7
            for n in chart['notes']:
                if n['t'] < lane_end[n['lane']] + .059:
                    problems.append(name + f': overlapping lane {n["lane"]} at {n["t"]:.3f}')
                    break
                lane_end[n['lane']] = n['t'] + n.get('hold', 0)
                if n.get('source') != 'interlude-v2':
                    continue
                key = (n['t'], n['melodyPitch'], n['melodyKind'], n['hold'])
                if key not in unique:
                    unique[key] = audit_note(y, flux_t, flux, envelope, rise, n)
                attack, pitch, hold, lag = unique[key]
                row['notes'] += 1
                row['attack'] += attack
                row['pitch'] += pitch
                row['holds'] += n['hold'] > 0
                row['held'] += n['hold'] > 0 and hold
                if lag is not None and attack:
                    attack_lags.append(abs(lag))
        for key in counts:
            counts[key] += row[key]
        print(f'{song["title"]}: added {row["notes"]}, onset {row["attack"]}, '
              f'pitch {row["pitch"]}, sustained {row["held"]}/{row["holds"]}', flush=True)
        if row['notes'] and (row['attack'] / row['notes'] < .85 or row['pitch'] / row['notes'] < .82):
            problems.append(song['title'] + ': melody signal evidence below song threshold')
        if row['holds'] >= 5 and row['held'] / row['holds'] < .85:
            problems.append(song['title'] + ': sustained notes below song threshold')
    if problems:
        print('ERROR:', *problems[:12], sep='\n', file=sys.stderr)
        raise SystemExit(1)
    if not counts['notes']:
        raise SystemExit('No interlude-v2 notes found')
    onset_rate = counts['attack'] / counts['notes']
    pitch_rate = counts['pitch'] / counts['notes']
    hold_rate = counts['held'] / max(1, counts['holds'])
    print(f'TOTAL {counts["notes"]} notes: onset {onset_rate:.1%}, '
          f'pitch {pitch_rate:.1%}, holds {counts["held"]}/{counts["holds"]} ({hold_rate:.1%}), '
          f'onset offset median {np.median(attack_lags)*1000:.0f}ms, '
          f'within 30ms {np.mean(np.array(attack_lags)<=.03):.1%}')
    if not titles and (onset_rate < .97 or pitch_rate < .98 or hold_rate < .98 or
                       np.mean(np.array(attack_lags) <= .03) < .9):
        raise SystemExit('Signal evidence below threshold; review event selection')


if __name__ == '__main__':
    main()
