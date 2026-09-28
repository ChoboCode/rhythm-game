"""모든 곡·모든 난이도의 노트가 실제 소리(드럼 타격·멜로디 시작음)에 얼마나 정확히 놓였는지 잰다.

드럼 스템과 멜로디(보컬+기타 악기) 스템에서 소리 시작을 찾아(온셋 피크 → 1ms 단위 "에너지가 가장 가파르게
오르는 곳"), 노트(같은 시각 묶음)마다 가장 가까운 시작음과의 차이를 본다.
  딱 맞음 ≤10ms · 맞음 ≤25ms · 어긋남 25~60ms · 소리 없음(60ms 안에 시작음 없음 — 이어지는 소리 위 노트 등)
스템은 make-stems.py가 남긴 %TEMP%/rhythm-game-stems/keep/htdemucs/<곡>/ 를 쓴다.

사용: python tools/check-note-sync.py [곡 제목 ...] [--json 결과.json]
"""
import json
import os
import sys
import tempfile
import warnings

import librosa
import numpy as np

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP = os.path.join(tempfile.gettempdir(), 'rhythm-game-stems', 'keep', 'htdemucs')
SR, HOP = 22050, 64
LEVELS = ('easy', 'normal', 'hard')


def attacks(y):
    """소리 시작 시각. 약한 시작도 놓치지 않게 피크 기준을 중앙값으로 낮게 잡는다."""
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, n_fft=1024, lag=2, max_size=3)
    peaks = librosa.util.peak_pick(env, pre_max=8, post_max=8, pre_avg=40, post_avg=40,
                                   delta=float(np.median(env)), wait=8)
    frame = int(SR * .001)
    power = np.convolve(y * y, np.ones(frame) / frame, mode='same')
    out = []
    for p in peaks:
        t = p * HOP / SR
        a, b = max(1, int((t - .015) * SR)), min(len(y) - 1, int((t + .005) * SR))
        seg = np.sqrt(power[a:b:frame] + 1e-12)
        if len(seg) > 2:
            t = (a + frame * int(np.argmax(np.diff(seg)) + 1)) / SR
        out.append(t)
    return np.array(sorted(out))


def nearest(times, t):
    i = np.searchsorted(times, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(times) and (best is None or abs(times[j] - t) < abs(best)):
            best = times[j] - t
    return best


def check(chart, drum_on, mel_on):
    groups = sorted({round(n['t'], 3) for n in chart['notes']})
    errs, src = [], []
    for t in groups:
        d, m = nearest(drum_on, t), nearest(mel_on, t)
        cands = [(abs(x), x, k) for x, k in ((d, 'drum'), (m, 'melody')) if x is not None and abs(x) <= .06]
        if cands:
            _, x, k = min(cands)
            errs.append(-x)                     # 양수 = 노트가 소리보다 늦다
            src.append(k)
        else:
            errs.append(None)
            src.append(None)
    e = np.array([abs(x) for x in errs if x is not None])
    n = len(groups)
    return {
        'notes': n,
        'tight': float((e <= .010).sum() / n), 'ok': float(((e > .010) & (e <= .025)).sum() / n),
        'off': float((e > .025).sum() / n), 'none': float(sum(x is None for x in errs) / n),
        'median_ms': float(np.median(e) * 1000) if len(e) else None,
        'bias_ms': float(np.median([x for x in errs if x is not None]) * 1000) if len(e) else None,
        'off_times': [round(t, 3) for t, x in zip(groups, errs) if x is not None and abs(x) > .025][:40],
    }


def main():
    songs = json.load(open(os.path.join(ROOT, 'songs', 'songs.json'), encoding='utf-8'))
    args = sys.argv[1:]
    out_json = args[args.index('--json') + 1] if '--json' in args else None
    only = [a for a in args if not a.startswith('--') and a != out_json]
    if only:
        songs = [s for s in songs if s['title'] in only]
    result = {}
    for s in songs:
        name = os.path.splitext(s['file'])[0]
        load = lambda part: librosa.load(os.path.join(KEEP, name, part + '.wav'), sr=SR, mono=True)[0]
        drum_on = attacks(load('drums'))
        mel_on = attacks(load('vocals') + load('other'))
        row = {}
        for lv in LEVELS:
            chart = json.load(open(os.path.join(ROOT, 'songs', s['charts'][lv]), encoding='utf-8'))
            row[lv] = check(chart, drum_on, mel_on)
        result[s['title']] = row
        print(s['title'][:22].ljust(23) + ' · '.join(
            f"{lv[0].upper()} 맞음 {(r['tight'] + r['ok']) * 100:3.0f}% 어긋남 {r['off'] * 100:3.0f}% 없음 {r['none'] * 100:3.0f}%"
            f" 치우침 {r['bias_ms']:+.0f}ms" for lv, r in row.items()), flush=True)
    if out_json:
        json.dump(result, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False)


if __name__ == '__main__':
    main()
