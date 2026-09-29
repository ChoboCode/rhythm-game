"""시티팝·발라드의 "쉬어가기"(느려지는 연출) 자리를 찾는다 — 끌어올렸다가 여려지는 순간.

사용자: "쉬어가는 것(느려지는 것)은 시티팝 형태에 어울리니 거기 적용, 발라드같이 감정을 끌어올리다 여려지는 영역이
있다면 거기 적용". 곡은 사용자가 골랐다(SOFT_SONGS). find-drops.py는 이 곡들의 rests를 건드리지 않는다.

1. 세기(intensity): 반 박마다 원곡 음량(dB) + 드럼·베이스 음량(dB)의 평균(한 박으로 부드럽게).
2. 여린 구간: 세기가 곡 중앙값보다 발라드 5dB·시티팝 4dB 넘게 낮은 채 발라드 1.5초·시티팝 0.9초 넘게 이어지는 곳.
   그 앞 2마디 평균이 곡 중앙값 − 2dB 이상(끌어올렸다가)이고, 떨어진 폭이 같은 기준 이상일 때만.
3. 여려지는 순간을 구간 시작 −반 마디~+1박 안에서 원곡 음량이 가장 가파르게 떨어지는 곳으로 다듬는다.
4. 쉬어가기 길이 = 여린 구간 + 반 박(그 끝에서 원래 속도), 1.5~6초.
5. 곡마다 떨어진 폭이 큰 순서로 최대 2곳, 20초 이상 떨어지게. 처음 15초, 끝까지 이어지는 여린 구간(페이드아웃),
   몰아치기 앞뒤 3초는 피한다.

사용: python tools/find-rests.py [--plot 폴더] [--write]
"""
import importlib.util
import json
import os
import sys
import tempfile
import warnings

import librosa
import numpy as np

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, 'songs', 'songs.json')
KEEP = os.path.join(tempfile.gettempdir(), 'rhythm-game-stems', 'keep', 'htdemucs')
SR = 22050
# 사용자가 고른 곡: 제목 → 종류(시티팝은 조금 덜 떨어져도 쉬어 간다)
SOFT_SONGS = {
    '깊은 밤': 'citypop',
    '폴라로이드 사진': 'citypop',
    '두 사람의 행복을 빌어': 'ballad',
    '말하지 못한 진심': 'ballad',
}
MIN_DROP = {'ballad': 5.0, 'citypop': 4.0}
MIN_SOFT = {'ballad': 1.5, 'citypop': .9}             # 시티팝은 한 마디 안팎의 짧은 멈춤도 쉬어 간다


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-6))


def find(song):
    name = os.path.splitext(song['file'])[0]
    load = lambda p: librosa.load(os.path.join(KEEP, name, p + '.wav'), sr=SR, mono=True)[0]
    parts = {p: load(p) for p in ('drums', 'bass', 'vocals', 'other')}
    mix = sum(parts.values())
    beat = 60 / (song.get('bpm') or 120)
    bar = beat * 4
    hop = int(SR * beat / 2)
    rms = lambda y: librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
    inten = (db(rms(mix)) + db(rms(parts['drums'] + parts['bass']))) / 2
    smooth = np.convolve(inten, np.ones(2) / 2, mode='same')              # 반 박 두 칸(한 박)만 부드럽게
    ft = np.arange(len(smooth)) * hop / SR
    dur = len(mix) / SR
    kind = SOFT_SONGS[song['title']]
    med = float(np.median(smooth))
    hi, lo = med, med - MIN_DROP[kind]
    drops = [d['t'] if isinstance(d, dict) else d for d in (song.get('drops') or [])]
    # 여린 구간: 세기가 (중앙값 − 폭) 아래로 1.5초 넘게 이어지는 곳
    soft, cands, i = smooth < lo, [], 0
    while i < len(soft):
        if not soft[i]:
            i += 1
            continue
        j = i
        while j < len(soft) and soft[j]:
            j += 1
        a0, a1 = float(ft[i]), float(ft[j - 1])
        pre = smooth[(ft >= a0 - 2 * bar) & (ft < a0)]
        if a1 - a0 >= MIN_SOFT[kind] and a0 >= 15 and a1 <= dur - 8 and len(pre) and pre.mean() >= hi - 2:
            cands.append((float(pre.mean() - smooth[i:j].mean()), a0, a1))
        i = j
    fine = db(librosa.feature.rms(y=mix, frame_length=1024, hop_length=256)[0])
    fine_t = np.arange(len(fine)) * 256 / SR
    picked = []
    for fall, a0, a1 in sorted(cands, reverse=True):
        if fall < MIN_DROP[kind] or any(abs(a0 - p['from']) < 20 for p in picked) or any(-3 < a0 - d < 3 for d in drops):
            continue
        m = (fine_t >= a0 - bar / 2) & (fine_t < a0 + beat)             # 여려지는 순간: 원곡 음량이 가장 가파르게 떨어지는 곳
        seg = np.convolve(fine[m], np.ones(8) / 8, mode='same')
        t0 = float(fine_t[m][int(np.argmin(np.diff(seg)))]) if m.sum() > 9 else a0
        to = t0 + min(6.0, max(1.5, a1 - t0 + beat * .5))      # 여린 구간이 끝날 때 원래 속도로
        picked.append({'from': round(t0, 3), 'to': round(to, 3), 'fall': round(fall, 1)})
        if len(picked) == 2:
            break
    return sorted(picked, key=lambda r: r['from']), (ft, smooth, hi, lo)


def main():
    spec = importlib.util.spec_from_file_location('fd', os.path.join(ROOT, 'tools', 'find-drops.py'))
    fd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fd)
    songs = json.load(open(MANIFEST, encoding='utf-8'))
    text = open(MANIFEST, encoding='utf-8').read()
    plot = sys.argv[sys.argv.index('--plot') + 1] if '--plot' in sys.argv else None
    for song in [s for s in songs if s['title'] in SOFT_SONGS]:
        rests, (ft, smooth, hi, lo) = find(song)
        print(f"{song['title']} ({SOFT_SONGS[song['title']]}): " + (', '.join(
            f"{int(r['from'] // 60)}:{r['from'] % 60:04.1f}~{int(r['to'] // 60)}:{r['to'] % 60:04.1f} (−{r['fall']}dB)" for r in rests) or '없음'), flush=True)
        if plot:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            plt.figure(figsize=(16, 3))
            plt.plot(ft, smooth, lw=.8)
            plt.axhline(hi, color='g', ls=':'); plt.axhline(lo, color='r', ls=':')
            for r in rests:
                plt.axvspan(r['from'], r['to'], color='orange', alpha=.4)
            for d in song.get('drops') or []:
                plt.axvline(d['t'] if isinstance(d, dict) else d, color='k', ls='--')
            plt.title(song['title'] + ' ' + SOFT_SONGS[song['title']])
            plt.xticks(np.arange(0, ft[-1], 10))
            plt.grid(alpha=.3); plt.tight_layout()
            plt.savefig(os.path.join(plot, 'rests-' + os.path.splitext(song['file'])[0] + '.png'), dpi=70)
            plt.close()
        text = fd.write_field(text, song['title'], 'rests', [{'from': r['from'], 'to': r['to']} for r in rests])
    json.loads(text)
    if '--write' in sys.argv:
        with open(MANIFEST, 'w', encoding='utf-8', newline='') as out:
            out.write(text)
        print('songs.json 갱신')


if __name__ == '__main__':
    main()
