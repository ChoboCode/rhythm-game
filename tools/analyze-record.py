"""record-play.cjs로 녹음한 게임 소리를 원곡과 비교해 "뚝 빠지는" 순간을 센다.

10ms마다 음량(dB)을 재고, 원곡이 -35dB보다 큰데 녹음이 원곡보다 12dB 넘게 작으면 빠진 것으로 본다.
녹음 첫 샘플은 곡 약 -3초(준비 시간)이므로 2.5~3.6초 사이에서 포락선 상관으로 대강 맞춘 뒤, 파형 상호상관으로
샘플 단위까지 맞춘다(10ms 단위로만 맞추면 원곡을 그대로 녹음해도 타격 경계마다 "빠짐"이 잡혔다 — 기준선 0.713/29번).

사용: python tools/analyze-record.py 녹음.wav "songs/원곡.mp3" [녹음2.wav ...]
"""
import sys
import warnings

import librosa
import numpy as np
import soundfile as sf

warnings.filterwarnings('ignore')
F = 480                                                  # 48kHz에서 10ms


def env(y):
    n = len(y) // F
    return 20 * np.log10(np.sqrt((y[:n * F].reshape(n, F) ** 2).mean(1)) + 1e-6)


def main():
    recs, orig = [sys.argv[1]] + sys.argv[3:], sys.argv[2]
    yo = librosa.load(orig, sr=48000, mono=True, duration=60)[0]
    eo = env(yo)
    for path in recs:
        yr = sf.read(path)[0].mean(1)
        er = env(yr)
        best, lag = -1e9, 0
        for L in range(250, 360):
            a = er[L:L + 2500]
            c = np.corrcoef(a, eo[:len(a)])[0, 1]
            if c > best:
                best, lag = c, L
        # 파형으로 ±15ms 안에서 샘플 단위 맞춤(5~15초 구간)
        seg = yo[5 * 48000:15 * 48000]
        base, bestc, shift = lag * F + 5 * 48000, -1e18, 0
        for d in range(-720, 721, 4):
            c = float(np.dot(yr[base + d:base + d + len(seg)], seg))
            if c > bestc:
                bestc, shift = c, d
        for d in range(shift - 4, shift + 5):
            c = float(np.dot(yr[base + d:base + d + len(seg)], seg))
            if c > bestc:
                bestc, shift = c, d
        start = lag * F + shift
        er = env(yr[start:])
        a = er
        n = min(len(a), len(eo))
        a, b = a[:n], eo[:n]
        t = np.arange(n) * .01
        m = (t > 1) & (t < t[-1] - 1)
        drop = m & (b > -35) & (a < b - 12)
        ev, run = [], 0
        for x in drop:
            if x:
                run += 1
            elif run:
                ev.append(run)
                run = 0
        ev = np.array(ev or [0]) * 10
        best = np.corrcoef(a[m], b[m])[0, 1]
        print(f'{path}: 상관 {best:.3f} | 뚝 빠짐 {int((ev >= 20).sum())}번(20ms↑), 합계 {ev.sum() / 1000:.2f}초, '
              f'가장 긴 것 {ev.max()}ms')


if __name__ == '__main__':
    main()
