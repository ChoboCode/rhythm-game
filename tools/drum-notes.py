"""곡의 한 구간을 실제 드럼 타격으로 다시 채보한다(구간 밖 노트는 그대로).

드럼이 일정한 비트로 반복되는 구간에서, 그 드럼을 그대로 치는 느낌을 주려고 만든 도구다.
Demucs로 드럼만 분리 → 원음 3ms 해상도로 타격 시각을 잰다 → 박 격자(곡 BPM)에 가까운 타격(박 타격)과
반 박 타격(8분)을 나눈다.
  EASY   : 두 박마다 한 번(박 타격만)
  NORMAL : 박 타격마다
  HARD   : 박 타격 + 반 박 타격
레인은 손을 번갈아 쓰는 D→K→F→J(7레인 기준 1,5,2,4) 순환, HARD의 반 박 타격은 S·L(0,6)을 번갈아.
가운데(스페이스) 레인은 쓰지 않는다. 구간 안의 기존 노트(롱노트 포함)는 지운다.

사용: python tools/drum-notes.py "System" 72.0 109.3            # 결과만 출력
      python tools/drum-notes.py "System" 72.0 109.3 --write    # 세 난이도 채보 파일에 반영
"""
import json
import os
import subprocess
import sys
import tempfile

import librosa
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR, HOP = 22050, 64
KEEP = os.path.join(tempfile.gettempdir(), 'rhythm-game-stems', 'keep')
BEAT_LANES = [1, 5, 2, 4]
OFF_LANES = [0, 6]


def drum_stem(song_file):
    name = os.path.splitext(song_file)[0]
    path = os.path.join(KEEP, 'htdemucs', name, 'drums.wav')
    if not os.path.exists(path):
        subprocess.run([sys.executable, '-m', 'demucs', '-n', 'htdemucs', '-o', KEEP,
                        os.path.join(ROOT, 'songs', song_file)], check=True)
    return path


def drum_hits(path, t0, t1):
    y, _ = librosa.load(path, sr=SR, mono=True, offset=max(0, t0 - .5), duration=t1 - t0 + 1)
    base = max(0, t0 - .5)
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, n_fft=1024, lag=2, max_size=3)
    peaks = librosa.util.peak_pick(env, pre_max=20, post_max=20, pre_avg=40, post_avg=40,
                                   delta=np.percentile(env, 75), wait=40)
    return [round(base + p * HOP / SR, 3) for p in peaks if t0 - .02 <= base + p * HOP / SR < t1]


def build(hits, beat):
    """첫 타격을 박의 기준으로, 이전 박 타격에서 반 박(±25%) 떨어진 타격은 반 박 타격으로 나눈다."""
    on, off = [], []
    for t in hits:
        if not on or (t - on[-1]) / beat >= .75:
            on.append(t)
        else:
            off.append(t)
    return on, off


def notes_for(level, on, off):
    notes = []
    step = 2 if level == 'easy' else 1
    for i, t in enumerate(on[::step]):
        notes.append({'t': t, 'lane': BEAT_LANES[i % len(BEAT_LANES)], 'hold': 0, 'drum': 'kick', 'source': 'drum-section-v1'})
    if level == 'hard':
        for i, t in enumerate(off):
            notes.append({'t': t, 'lane': OFF_LANES[i % len(OFF_LANES)], 'hold': 0, 'drum': 'snare', 'source': 'drum-section-v1'})
    return notes


def main():
    title, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    songs = json.load(open(os.path.join(ROOT, 'songs', 'songs.json'), encoding='utf-8'))
    song = next(s for s in songs if s['title'] == title)
    beat = 60 / song['bpm']
    hits = drum_hits(drum_stem(song['file']), t0, t1)
    on, off = build(hits, beat)
    print(f'{title} {t0}~{t1}s: 드럼 타격 {len(hits)}개 = 박 {len(on)} + 반 박 {len(off)}')
    for level in ('easy', 'normal', 'hard'):
        path = os.path.join(ROOT, 'songs', song['charts'][level])
        chart = json.load(open(path, encoding='utf-8'))
        kept = [n for n in chart['notes'] if not (n['t'] < t1 and n['t'] + (n.get('hold') or 0) > t0)]
        new = notes_for(level, on, off)
        chart['notes'] = sorted(kept + new, key=lambda n: (n['t'], n['lane']))
        chart['noteCount'] = len(chart['notes'])
        before = len(json.load(open(path, encoding='utf-8'))['notes']) - len(kept)
        print(f'  {level}: 구간 노트 {before}개 → {len(new)}개')
        if '--write' in sys.argv:
            with open(path, 'w', encoding='utf-8', newline='') as out:
                json.dump(chart, out, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main()
