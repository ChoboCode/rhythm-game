"""채보 노트를 음원의 실제 타격 시각에 붙인다(키음과 판정이 소리와 딱 맞도록).

측정해 보니 노트가 실제 드럼 타격과 중앙값 40ms, 27%는 60ms 넘게 어긋나 있었다(PERFECT 창이 42ms).
키음은 친 순간 그 드럼 조각을 트니, 노트가 어긋나면 정확히 쳐도 드럼이 반주와 어긋나게 들린다.

방법
  1. 드럼 스템에서 타격을 찾고(온셋 피크), 각 타격을 1ms 단위로 "에너지가 가장 가파르게 오르는 곳"에 맞춘다.
  2. 같은 시각의 노트(화음)를 한 묶음으로, ±min(0.10초, 8분음표의 45%) 안에서 "가깝고 센" 타격으로 옮긴다
     (점수 = 세기 − 거리 × 25/초 — 가까움 우선). 드럼 타격이 없으면 원곡 전체의 타격에 ±0.06초로 좁게 맞춘다.
  3. 서로 다른 묶음이 한 타격으로 합쳐지지 않게, 시간 순서가 뒤바뀌지 않게 한다.
  4. 옮긴 뒤 같은 레인에서 롱노트와 겹치거나 0.09초(롱노트 끝 뒤 0.06초) 안에 두 번이 되면 그 노트는 원래 자리로 둔다.
롱노트는 통째로 옮긴다(길이 유지). 채보에 "snapped": "onset-v1"을 남겨 두 번 옮기지 않는다.

사용: python tools/snap-notes.py [곡 제목 ...] [--write]   (쓰기 전 원본은 _chart_backup_snap/ 에 복사)
"""
import json
import os
import shutil
import sys
import tempfile

import librosa
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, 'songs', 'songs.json')
KEEP = os.path.join(tempfile.gettempdir(), 'rhythm-game-stems', 'keep', 'htdemucs')
BACKUP = os.path.join(ROOT, '_chart_backup_snap')
SR, HOP = 22050, 64
DRUM_WIN, MIX_WIN, DIST_PENALTY = .10, .06, 25.0


def onsets(y):
    """타격 시각(초)과 세기. 피크를 1ms 단위로 에너지 상승이 가장 가파른 곳으로 다듬는다."""
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, n_fft=1024, lag=2, max_size=3)
    peaks = librosa.util.peak_pick(env, pre_max=20, post_max=20, pre_avg=60, post_avg=60,
                                   delta=np.percentile(env, 75), wait=20)
    frame = int(SR * .001)
    power = np.convolve(y * y, np.ones(frame) / frame, mode='same')
    times, strength = [], []
    for p in peaks:
        t = p * HOP / SR
        a, b = max(1, int((t - .015) * SR)), min(len(y) - 1, int((t + .005) * SR))
        seg = np.sqrt(power[a:b:frame] + 1e-12)
        if len(seg) > 2:
            t = (a + frame * int(np.argmax(np.diff(seg)) + 1)) / SR
        times.append(t)
        strength.append(float(env[p]))
    s = np.array(strength)
    return np.array(times), s / (np.percentile(s, 90) or 1)


def snap_chart(chart, drum_on, mix_on):
    notes = chart['notes']
    eighth = 30 / (chart.get('bpm') or 120)
    drum_win = min(DRUM_WIN, .45 * eighth)            # 빠른 곡에서 옆 16분음표로 잘못 붙지 않게
    mix_win = min(MIX_WIN, drum_win)
    groups = {}
    for n in notes:
        groups.setdefault(round(n['t'], 4), []).append(n)
    keys = sorted(groups)
    claimed, moved, prev_new = set(), {}, -1.0
    for t in keys:
        best = None
        for (times, power), win, tag in ((drum_on, drum_win, 'd'), (mix_on, mix_win, 'm')):
            lo, hi = np.searchsorted(times, t - win), np.searchsorted(times, t + win)
            cands = sorted(((power[i] - DIST_PENALTY * abs(times[i] - t), i) for i in range(lo, hi)
                            if (tag, i) not in claimed and times[i] > prev_new + .02), reverse=True)
            if cands:
                best = (tag, cands[0][1], times[cands[0][1]])
                break
        if best:
            claimed.add(best[:2])
            moved[t] = round(float(best[2]), 4)
            prev_new = moved[t]
        else:
            moved[t] = t
            prev_new = t
    before = {id(n): n['t'] for n in notes}
    for t in keys:
        for n in groups[t]:
            n['t'] = moved[t]
    # 같은 레인에서 겹치거나 너무 붙으면 그 노트는 원래 자리로
    by_lane = {}
    for n in notes:
        by_lane.setdefault(n['lane'], []).append(n)
    reverted = 0
    for lane_notes in by_lane.values():
        changed = True
        while changed:                                     # 되돌린 뒤 새로 생긴 겹침도 다시 본다
            changed = False
            lane_notes.sort(key=lambda n: n['t'])
            for i in range(1, len(lane_notes)):
                p, n = lane_notes[i - 1], lane_notes[i]
                if n['t'] < p['t'] + (p.get('hold') or 0) + (.09 if not p.get('hold') else .06):
                    # 옮겨진 쪽을 되돌린다(둘 다 옮겨졌으면 뒤의 것부터). 둘 다 원래 자리면 원래부터 있던 것.
                    for x in (n, p):
                        if x['t'] != before[id(x)]:
                            x['t'] = before[id(x)]
                            reverted += 1
                            changed = True
                            break
                    if changed:
                        break
    chart['notes'] = sorted(notes, key=lambda n: (n['t'], n['lane']))
    chart['snapped'] = 'onset-v1'
    shifts = np.array([moved[t] - t for t in keys]) * 1000
    return shifts, reverted


def main():
    songs = json.load(open(MANIFEST, encoding='utf-8'))
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    if only:
        songs = [s for s in songs if s['title'] in only]
    for song in songs:
        name = os.path.splitext(song['file'])[0]
        drums, _ = librosa.load(os.path.join(KEEP, name, 'drums.wav'), sr=SR, mono=True)
        mix, _ = librosa.load(os.path.join(ROOT, 'songs', song['file']), sr=SR, mono=True)
        drum_on, mix_on = onsets(drums), onsets(mix)
        line = []
        for level in ('easy', 'normal', 'hard'):
            path = os.path.join(ROOT, 'songs', song['charts'][level])
            chart = json.load(open(path, encoding='utf-8'))
            if chart.get('snapped'):
                line.append(f'{level} 이미 맞춤')
                continue
            shifts, reverted = snap_chart(chart, drum_on, mix_on)
            moved = np.abs(shifts) > .5
            line.append(f'{level} {moved.mean() * 100:.0f}% 옮김(중앙 {np.median(np.abs(shifts[moved])) if moved.any() else 0:.0f}ms, 되돌림 {reverted})')
            if '--write' in sys.argv:
                os.makedirs(BACKUP, exist_ok=True)
                if not os.path.exists(os.path.join(BACKUP, song['charts'][level])):
                    shutil.copy(path, os.path.join(BACKUP, song['charts'][level]))
                with open(path, 'w', encoding='utf-8', newline='') as out:
                    json.dump(chart, out, ensure_ascii=False, separators=(',', ':'))
        print(f"{song['title']}: " + ' · '.join(line), flush=True)


if __name__ == '__main__':
    main()
