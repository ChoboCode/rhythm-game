"""Check chart integrity and timing against an independent mix onset detector."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy.signal

# librosa 0.9 expects the alias removed from newer SciPy.
if not hasattr(scipy.signal, 'hann'):
    scipy.signal.hann = scipy.signal.windows.hann
import librosa


source = Path(sys.argv[1])
sr, hop = 22050, 256
pcm = subprocess.run(
    ['ffmpeg', '-v', 'error', '-i', str(source), '-f', 'f32le', '-ac', '1',
     '-ar', str(sr), 'pipe:1'], capture_output=True, check=True,
).stdout
audio = np.frombuffer(pcm, dtype='<f4').astype(np.float32)
duration = len(audio) / sr
strength = librosa.onset.onset_strength(y=audio, sr=sr, hop_length=hop)
onsets = librosa.onset.onset_detect(onset_envelope=strength, sr=sr,
                                   hop_length=hop, units='time')
print('independent mix onsets:', len(onsets))

for difficulty in ('easy', 'normal', 'hard'):
    chart = json.loads(source.with_name(f'{source.stem}.{difficulty}.json').read_text(encoding='utf8'))
    notes = chart['notes']
    ends = [-1.] * 7
    attacks = sorted({n['t'] for n in notes})
    for note in notes:
        t, lane, hold = note['t'], note['lane'], note['hold']
        assert 0 <= t <= duration and 0 <= lane < 7 and hold >= 0
        assert t + hold <= duration
        assert t >= ends[lane] - .001, f'{difficulty}: lane {lane} overlap at {t}'
        ends[lane] = t + hold
    for hold in (note for note in notes if note['hold']):
        for note in notes:
            if note is hold or not hold['t'] - .18 <= note['t'] <= hold['t'] + hold['hold'] + .18:
                continue
            assert note['lane'] != hold['lane'], f'{difficulty}: occupied lane near {hold["t"]}'
            if note['lane'] != 3:
                assert (note['lane'] < 3) != (hold['lane'] < 3), (
                    f'{difficulty}: occupied hand near {hold["t"]}')
    assert notes == sorted(notes, key=lambda n: (n['t'], n['lane']))
    delta = np.array([np.min(np.abs(onsets - t)) for t in attacks])
    print(difficulty, 'notes', len(notes), 'attacks', len(attacks),
          'holds', sum(n['hold'] > 0 for n in notes),
          'median onset offset', round(float(np.median(delta))*1000), 'ms',
          'within 50ms', round(float(np.mean(delta <= .05))*100, 1), '%',
          'within 100ms', round(float(np.mean(delta <= .1))*100, 1), '%')
