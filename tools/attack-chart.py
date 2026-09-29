"""실제 소리 위치로만 채보를 만든다 — 노트는 드럼 타격·멜로디 시작음에만, 난이도는 "얼마나 촘촘히 따라가나"와
"동시에 몇 키를 누르나"로 조절한다(사용자: "타이밍에 맞춰 노트는 내려오되, 동시에 여러 개일 경우로 난이도 조절").

1. 드럼 스템과 멜로디(보컬+기타 악기) 스템에서 소리 시작과 세기를 찾는다(1ms 단위로 가장 가파르게 오르는 곳).
   30ms 안의 드럼·멜로디 시작은 한 사건(드럼 시각)으로 묶고, 둘 다 있으면 더 세다.
2. 난이도마다 가사 단어 시작(가사 없는 곡은 센 멜로디)을 먼저, 그다음 센 사건부터 고른다(사용자: 가사가 들릴 때는
   늘 노트). 쉬움 ⊂ 보통 ⊂ 어려움(쉬움 노트는 보통·어려움에도 있다). 최소 간격 안의 단어는 빠질 수 있다(쉬움은 1박).
     쉬움   최소 간격 1박, 초당 약 1.5개      보통 최소 ½박, 초당 약 3개      어려움 최소 ¼박, 초당 약 4개
3. 동시 키: 센 순서(그 난이도 안 백분위)로 — 쉬움 상위 4% 2키 / 보통 25% 2키·5% 3키 / 어려움 30% 2키·8% 3키·1% 4키.
   3키 이상은 앞뒤로 ½박 여유가 있을 때만(사용자: 어려움이 너무 어렵다).
4. 레인(7레인 0~6, 가운데 3): 드럼은 킥 3·2·4, 스네어 5·1, 하이햇 6·0, 크래시 0·6. 멜로디는 음높이(스펙트럼 중심)가
   최근 4초 안에서 어디쯤인지로 낮으면 왼쪽·높으면 오른쪽. 같은 레인을 0.18초(또는 ½박) 안에 다시 쓰지 않는다.
   동시 키는 반대 손부터(거울 자리), 그다음 같은 손 옆자리.
5. 긴 노트: 멜로디만 있는 한 키 노트에서 소리가 0.6초 넘게 이어지면(시작 크기의 45% 아래로 떨어질 때까지, 최대 2초).
   모든 난이도에서 누르는 동안 다른 노트가 오지 않을 만큼만(사용자: 롱노트가 너무 많다).

채보에 "snapped": "attack-v1"(snap-notes.py가 다시 옮기지 않게), 노트에 "source": "attack-v1".
사용: python tools/attack-chart.py "곡 제목" [...] [--write]   (쓰기 전 원본은 _chart_backup_attack/ 에 복사)
"""
import bisect
import json
import os
import shutil
import sys
import tempfile
import warnings

import librosa
import numpy as np

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP = os.path.join(tempfile.gettempdir(), 'rhythm-game-stems', 'keep', 'htdemucs')
BACKUP = os.path.join(ROOT, '_chart_backup_attack')
SR, HOP = 22050, 64
LEVEL = {
    #          최소 간격(박)  초당   2키   3키   4키
    'easy':   (1.0,          1.5,  .04,  0,    0),
    'normal': (.5,           3.0,  .25,  .05,  0),
    'hard':   (.25,          4.0,  .30,  .08,  .01),
}
# 드럼 자리(앞쪽이 기본, 최근 덜 쓴 키부터). 스네어가 D·K에만 가서 두 키가 25~29%로 몰렸다 → 자리를 넓혔다.
DRUM_LANES = {'kick': [3, 2, 4], 'snare': [5, 1, 4, 2], 'hat': [6, 0, 5, 1], 'crash': [0, 6]}
# 어려움 레벨을 곡마다 다르게(사용자: "난이도 12·13·14·15 다양하게 몇 곡"). 에너지(드럼 밀도 × 드럼 비중 × 템포)가
# 높은 곡일수록 높게. 없으면 기본(보통 11~12). 적어 둔 곡은 목표 레벨이 될 때까지 밀도를 올린다.
HARD_LEVEL = {
    'Soda Pop': 15, '야자 탈출': 15, '터뜨려라': 15,
    'G_Force': 14, '하동으로가요': 14, '다시 떠오른다': 14, 'Break It Down': 14,
    'Bass Control': 13, 'Paper Airplane': 13, '오늘부터 우리': 13, '스파이크': 13, '시험이 끝났다': 13,
    'Stay with me_ make me real': 12, 'ITer': 12, '하얀 눈위의 발자국': 12, '깊은 밤': 12,
}
#            2키   3키   4키   (높은 레벨일수록 동시 키도 조금 더)
HARD_CHORDS = {12: (.30, .08, .01), 13: (.34, .10, .02), 14: (.38, .12, .02), 15: (.42, .14, .03)}
# 보통 레벨도 곡마다(사용자 "개선해줘" — 보통이 전부 7~8이었다). 어려움 레벨을 따라 15→10, 14→9, 12~13→8, 11→7,
# 발라드·잔잔한 곡은 6.
NORMAL_FROM_HARD = {15: 10, 14: 9, 13: 8, 12: 8}
NORMAL_CALM = {'두 사람의 행복을 빌어', '말하지 못한 진심', '우린 봄이야', 'Last Stage', '가을의 질주'}
NORMAL_CHORDS = {6: (.15, .02, 0), 7: (.25, .05, 0), 8: (.25, .05, 0), 9: (.30, .07, 0), 10: (.34, .08, 0)}


def normal_level(title):
    return 6 if title in NORMAL_CALM else NORMAL_FROM_HARD.get(HARD_LEVEL.get(title), 7)


# 멜로디 구간: 그 안에서는 멜로디 음이 바뀌는 순간마다 꼭 노트. 몽환적인 멜로디는 크기가 부드럽게 이어져 소리 시작
# (크기가 뛰는 곳)으로는 안 잡히므로 음높이가 바뀌는 순간(CQT에서 가장 센 음)을 쓴다.
# 사용자(다시 떠오른다): 0:48~53 몽환적인 멜로디, 1:09 "나는 다시 떠오른다" 멜로디와 가사 각각, 1:22 "올라가" 뒤, 1:36,
# 2:18 "틈새" 뒤, 2:26, 2:46 하이라이트 간주 — "나머지도 알아서 잘".
MELODY_SPANS = {
    '다시 떠오른다': [(48.0, 54.0), (68.8, 71.3), (81.2, 86.2), (95.5, 101.1), (137.9, 140.6), (145.8, 149.5), (162.3, 182.6)],
}
# "알아서": 가사에 이 낱말이 있는 줄 전체 + 노래가 1.2초 넘게 쉬는 틈(악기가 들리는 곳)과 전주도 멜로디 구간으로
MELODY_AUTO = {'다시 떠오른다': '떠오른다'}


def melody_spans(song, lines, other):
    spans = list(MELODY_SPANS.get(song['title'], []))
    word = MELODY_AUTO.get(song['title'])
    if word and lines:
        step = int(SR * .1)
        n = len(other) // step
        level = (other[:n * step].reshape(n, step) ** 2).mean(axis=1)
        active = lambda a, b: len(level[int(a * 10):int(b * 10)]) and np.median(level[int(a * 10):int(b * 10)]) > np.percentile(level, 90) * .04
        spans += [(l['t'], l['end']) for l in lines if word in l['text']]
        gaps = [(1.0, lines[0]['t'])] + [(l['end'], nx['t']) for l, nx in zip(lines, lines[1:])] + [(lines[-1]['end'], len(other) / SR - 1)]
        spans += [(a, b) for a, b in gaps if b - a >= 1.2 and active(a, b)]
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + .1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def beat_grid(drums, bpm):
    """드럼으로 박을 따라가(librosa beat_track) 16분 격자를 만든다. 곡의 박 길이도 돌려준다."""
    import scipy.signal
    import scipy.signal.windows
    if not hasattr(scipy.signal, 'hann'):
        scipy.signal.hann = scipy.signal.windows.hann       # librosa 0.9 + 새 scipy
    _, bf = librosa.beat.beat_track(y=drums, sr=SR, hop_length=256, start_bpm=bpm, tightness=200)
    beats = librosa.frames_to_time(bf, sr=SR, hop_length=256)
    if len(beats) < 8:
        return None, None
    grid = np.concatenate([np.linspace(beats[i], beats[i + 1], 5)[:-1] for i in range(len(beats) - 1)] + [beats[-1:]])
    return grid, float(np.median(np.diff(beats)))


def on_grid(notes, grid, onsets):
    """멜로디 음을 16분 격자에 맞춘다(정박 느낌): 격자에서 45ms 넘게 벗어난 것은 검출 흔들림으로 보고 버리고,
    격자 칸마다 하나만, 시각은 그 칸 ±30ms 안의 실제 악기 소리 시작(없으면 격자 시각)."""
    out, used = [], set()
    for t, s in notes:
        k = int(np.argmin(np.abs(grid - t)))
        if abs(grid[k] - t) > .045 or k in used:
            continue
        used.add(k)
        j = np.searchsorted(onsets, grid[k])
        near = [onsets[x] for x in (j - 1, j) if 0 <= x < len(onsets) and abs(onsets[x] - grid[k]) <= .03]
        out.append((round(float(min(near, key=lambda o: abs(o - grid[k])) if near else grid[k]), 4), s))
    return out


def melody_notes(y, spans):
    """구간 안에서 멜로디 음이 바뀌는 순간: CQT 가장 센 음(5칸 중앙값으로 떨림 제거)이 바뀌고 60ms 넘게 유지,
    또는 조용하다가 소리가 날 때. 80ms 안의 두 번째는 버린다. 돌려주는 값: [(시각, 세기)], 시각 → 음높이(반음 칸)."""
    import scipy.ndimage
    hop = 256
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=hop, fmin=librosa.note_to_hz('C2'), n_bins=84))
    # 배음까지 더해(기음 + ½·2배음 + ⅓·3배음) 가장 센 음을 고른다 — 한 옥타브씩 튀는 것을 줄인다
    sal = C[:-24] + .5 * C[12:-12] + .33 * C[19:-5]
    pitch = scipy.ndimage.median_filter(sal.argmax(axis=0), size=5)
    level = C.max(axis=0)
    ft = np.arange(len(pitch)) * hop / SR
    floor, top = np.percentile(level, 50), np.percentile(level, 95)
    out = []
    for a, b in spans:
        last = -9.0
        for i in np.where((ft >= a) & (ft < b))[0]:
            if i < 1 or i + 5 >= len(pitch) or level[i] < floor:
                continue
            if not (pitch[i] != pitch[i - 1] or level[i - 1] < floor) or np.any(pitch[i:i + 5] != pitch[i]):
                continue
            if ft[i] - last < .08:
                continue
            out.append((round(float(ft[i]), 4), float(min(2.0, 1.5 * level[i] / (top or 1)))))
            last = ft[i]
    def pitch_at(t):                                  # 음이 시작한 뒤 0.1초 동안의 중앙값(시작 순간의 흔들림을 피해)
        f = min(len(pitch) - 1, int(t * SR / hop) + 1)
        return float(np.median(pitch[f:f + 9])) if f < len(pitch) else float(pitch[-1])
    return out, pitch_at


def audible_end(y):
    """귀에 들리는 소리가 끝나는 시각 — 게임(index.html soundEndOf)과 같은 기준: 0.1초 묶음 세기의 95백분위보다
    30dB 넘게 작아지기 전 마지막 곳. 그 뒤(거의 안 들리는 페이드아웃)에는 노트를 두지 않는다."""
    step = int(SR * .1)
    n = len(y) // step
    level = (y[:n * step].reshape(n, step)[:, :2048] ** 2).mean(axis=1)
    quiet = np.percentile(level, 95) * 1e-3
    loud = np.where(level > quiet)[0]
    return (loud[-1] + 1) * step / SR if len(loud) else len(y) / SR


def rating(chart):
    """게임(index.html ratingFromChart)과 같은 식: 초당 노트 × 2.1 + 긴 노트 비율 × 3, 1~15."""
    notes = chart['notes']
    dur = notes[-1]['t'] or 1
    hold = sum(1 for n in notes if n['hold'] > 0) / len(notes)
    return max(1, min(15, round(len(notes) / dur * 2.1 + hold * 3)))


def detect(y):
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, n_fft=1024, lag=2, max_size=3)
    peaks = librosa.util.peak_pick(env, pre_max=8, post_max=8, pre_avg=40, post_avg=40,
                                   delta=float(np.median(env)), wait=8)
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
    return np.array(times), np.minimum(2, s / (np.percentile(s, 90) or 1))


def drum_kind(S, freqs, t):
    """타격 직후 50ms의 대역 에너지로 킥·스네어·하이햇, 0.3초 뒤에도 고음이 남으면 크래시."""
    f0 = int(t * SR / 256)
    spec = S[:, f0:f0 + 4].sum(axis=1)
    low, mid, high = spec[freqs < 150].sum(), spec[(freqs >= 150) & (freqs < 3000)].sum(), spec[freqs >= 5000].sum()
    total = low + mid + high + 1e-9
    if low / total > .45:
        return 'kick'
    if high / total > .5:
        later = S[freqs >= 5000, f0 + 25:f0 + 29].sum()
        return 'crash' if later > .4 * high else 'hat'
    return 'snare'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    songs = json.load(open(os.path.join(ROOT, 'songs', 'songs.json'), encoding='utf-8'))
    for song in [s for s in songs if s['title'] in args]:
        name = os.path.splitext(song['file'])[0]
        load = lambda part: librosa.load(os.path.join(KEEP, name, part + '.wav'), sr=SR, mono=True)[0]
        other = load('other')
        drums, mel = load('drums'), load('vocals') + other
        heard_end = audible_end(drums + mel + load('bass'))
        d_t, d_s = detect(drums)
        m_t, m_s = detect(mel)
        S = np.abs(librosa.stft(drums, n_fft=1024, hop_length=256))
        freqs = librosa.fft_frequencies(sr=SR, n_fft=1024)
        cent = librosa.feature.spectral_centroid(y=mel, sr=SR, n_fft=2048, hop_length=256)[0]
        rms = librosa.feature.rms(y=mel, frame_length=1024, hop_length=256)[0]
        fr = lambda t: min(len(rms) - 1, int(t * SR / 256))

        # 1. 사건: 드럼·멜로디 시작을 30ms 안에서 묶는다
        raw = [(t, s, 'd') for t, s in zip(d_t, d_s)] + [(t, s, 'm') for t, s in zip(m_t, m_s)]
        raw.sort()
        events = []
        for t, s, k in raw:
            if events and t - events[-1]['t'] < .03 and k not in events[-1]['src']:
                e = events[-1]
                e['src'][k] = s
                if k == 'd':
                    e['t'] = t
            else:
                events.append({'t': t, 'src': {k: s}})
        # 1-1. 가사가 들릴 때는 늘 노트(사용자): 가사 단어 시작(align-lyrics.py로 보컬에 맞춘 시각)에 가장 가까운
        #      멜로디 시작(±0.06초, 없으면 아무 시작 ±0.03초)을 "꼭" 사건으로, 그것도 없으면 단어 시작에 새 사건.
        #      가사가 없는 연주곡은 센 멜로디 시작(세기 0.6↑)을 꼭 사건으로.
        words, lines = [], []
        if song.get('lyrics'):
            lj = json.load(open(os.path.join(ROOT, 'songs', song['lyrics']), encoding='utf-8'))
            lines = [l for l in lj['lines'] if l.get('text', '').strip()]
            words = sorted(w['t'] for l in lines for w in (l.get('words') or []))
        if words:
            et = np.array([e['t'] for e in events])
            for w in words:
                near = [i for i in np.where(np.abs(et - w) <= .06)[0] if 'm' in events[i]['src']]
                near = near or list(np.where(np.abs(et - w) <= .03)[0])
                if near:
                    events[min(near, key=lambda i: abs(et[i] - w))]['must'] = True
                else:
                    events.append({'t': w, 'src': {'m': .5}, 'must': True})
            events.sort(key=lambda e: e['t'])
        else:
            for e in events:
                if e['src'].get('m', 0) >= .6:
                    e['must'] = True
        # 1-2. 멜로디 구간(MELODY_SPANS·MELODY_AUTO): 멜로디 음이 바뀌는 순간마다 꼭 노트, 레인도 실제 음높이로
        pitch_at = None
        mspans = melody_spans(song, lines, other)
        if mspans:
            m_notes, pitch_at = melody_notes(other, mspans)
            raw_count = len(m_notes)
            # 음높이가 바뀌는 곳만으로는 같은 음을 다시 치는 것을 놓친다 → 악기(전자피아노)를 실제로 치는 순간도 멜로디 음으로
            o_t, o_s = detect(other)
            m_notes = sorted(m_notes + [(float(t), float(s)) for t, s in zip(o_t, o_s)
                                        if s >= .25 and any(a <= t < b for a, b in mspans)])
            grid, _ = beat_grid(drums, song['bpm'])
            if grid is not None:
                m_notes = on_grid(m_notes, grid, o_t)                    # 정박 느낌: 16분 격자 + 실제 타건 시각
            et = np.array([e['t'] for e in events])
            for t, s in m_notes:
                j = int(np.argmin(np.abs(et - t)))
                if abs(et[j] - t) <= .04:
                    events[j]['must'] = True
                    events[j]['src'].setdefault('m', s)
                else:
                    events.append({'t': t, 'src': {'m': s}, 'must': True})
            events.sort(key=lambda e: e['t'])
            # 멜로디 구간 안에서는 멜로디·가사 노트만(드럼·화음을 섞지 않아 계단 모양이 또렷하게)
            for e in events:
                if any(a <= e['t'] < b for a, b in mspans):
                    e['in_span'] = True
            print(f"  멜로디 구간 {len(mspans)}곳 {sum(b - a for a, b in mspans):.0f}초 · 멜로디 음 {raw_count}개 → 16분 격자 {len(m_notes)}개", flush=True)
        for e in events:
            v = sorted(e['src'].values(), reverse=True)
            e['s'] = v[0] + (.5 * v[1] if len(v) > 1 else 0)
            e['drum'] = drum_kind(S, freqs, e['t']) if 'd' in e['src'] and e['src']['d'] >= e['src'].get('m', 0) * .6 else None
            e['pitch'] = pitch_at(e['t']) if pitch_at else float(np.log(np.median(cent[fr(e['t'] + .02):fr(e['t'] + .08) + 1]) + 1))
            a = fr(e['t'])
            top = rms[a:a + 4].max() if a < len(rms) else 0
            end = a + 4
            while end < len(rms) and rms[end] > .45 * top and end - a < 2 * SR / 256:
                end += 1
            e['sustain'] = (end - a) * 256 / SR
        times = [e['t'] for e in events]
        print(f"{song['title']}: 드럼 시작 {len(d_t)} · 멜로디 시작 {len(m_t)} → 사건 {len(events)}", flush=True)

        # 2. 난이도별 선택(쉬움 ⊂ 보통 ⊂ 어려움)
        beat = 60 / song['bpm']
        def build(level, base, params):
            gap_beats, rate, p2, p3, p4 = params
            chosen = set(base)
            old = json.load(open(os.path.join(ROOT, 'songs', song['charts'][level]), encoding='utf-8'))
            gap = max(.09, gap_beats * beat)
            target = int(old['duration'] * rate)
            picked = sorted(chosen, key=lambda i: times[i])
            picked_t = [times[i] for i in picked]
            # 꼭 사건(가사·멜로디)을 먼저 시간 순으로(최소 간격은 지킨다), 그다음 드럼 뼈대(킥·스네어·크래시)를
            # 센 순서로 — 리듬감(사용자: "드럼은 웬만하면 채보로"), 그다음 나머지(멜로디·하이햇)를 센 순서로 채운다
            musts = sorted((i for i in range(len(events)) if events[i].get('must')), key=lambda i: times[i])
            backbone = sorted((i for i in range(len(events)) if events[i]['drum'] in ('kick', 'snare', 'crash')),
                              key=lambda i: -events[i]['s'])
            for i in musts + backbone + sorted(range(len(events)), key=lambda i: -events[i]['s']):
                if len(picked_t) >= target and not events[i].get('must'):
                    break
                if i in chosen or times[i] < .5 or times[i] > min(old['duration'] - .3, heard_end - .1):
                    continue
                if events[i].get('in_span') and not events[i].get('must'):
                    continue                                   # 멜로디 구간엔 멜로디·가사 노트만
                if events[i].get('in_span') and events[i].get('must'):
                    # 계단 멜로디는 16분(¼박)까지 따라간다 — 쉬움은 ½박, 보통은 ¼박 간격이면 된다(사용자: 멜로디마다)
                    g2 = max(.09, .8 * (.5 if gap_beats >= 1 else .25) * beat)   # 격자 위 실제 타건은 조금씩 당겨지고 밀린다
                    j = bisect.bisect_left(picked_t, times[i])
                    if (j > 0 and times[i] - picked_t[j - 1] < g2) or (j < len(picked_t) and picked_t[j] - times[i] < g2):
                        continue
                    picked_t.insert(j, times[i])
                    chosen.add(i)
                    continue
                j = bisect.bisect_left(picked_t, times[i])
                if (j > 0 and times[i] - picked_t[j - 1] < gap) or (j < len(picked_t) and picked_t[j] - times[i] < gap):
                    continue
                picked_t.insert(j, times[i])
                chosen.add(i)
            order = sorted(chosen, key=lambda i: times[i])

            # 3. 동시 키 수
            strengths = np.array([events[i]['s'] for i in order])
            rank = strengths.argsort().argsort() / max(1, len(order) - 1)      # 0 약함 ~ 1 셈
            room = beat * .5                                               # 3키 이상은 앞뒤 ½박 여유
            size = []
            for k, i in enumerate(order):
                before = times[i] - times[order[k - 1]] if k else 9
                after = times[order[k + 1]] - times[i] if k + 1 < len(order) else 9
                n = 1 + (p2 > 0 and rank[k] >= 1 - p2) + (p3 > 0 and rank[k] >= 1 - p3 and min(before, after) >= room) \
                    + (p4 > 0 and rank[k] >= 1 - p4 and min(before, after) >= beat * .5)
                size.append(1 if events[i].get('in_span') else int(n))     # 계단은 한 키씩

            # 4. 레인 + 5. 긴 노트
            notes, last_use, busy_until = [], [-9.0] * 7, [-9.0] * 7
            recent, uses = [], []                            # 멜로디 음높이 기록, (시각, 레인) 최근 사용
            jack = max(.25, beat * .5)                       # 같은 키를 0.25초(또는 ½박) 안에 다시 쓰지 않는다
            side = lambda x: 'L' if x < 3 else 'R' if x > 3 else 'C'
            run_side, run_len, run_t = None, 0, -9.0         # 한 손으로만 이어지는 중인지
            lock_side, lock_until = None, -9.0               # 어려움 긴 노트를 누르는 손(그동안 그 손엔 노트 없음)
            holds = 0
            stair = {'t': None, 'p': 0.0, 'lane': 3, 'dir': 1}   # 멜로디 구간 계단: 직전 멜로디 노트

            def free(lane, t, gap=None):
                return t - last_use[lane] >= (jack if gap is None else gap) and t >= busy_until[lane] + .06 and \
                    not (t < lock_until and side(lane) == lock_side)

            for k, i in enumerate(order):
                e, t = events[i], times[i]
                uses = [(ut, ul) for ut, ul in uses if t - ut < 2]
                used = lambda x: sum(1 for _, ul in uses if ul == x)
                if e.get('in_span'):
                    # 계단(사용자: 전자피아노가 올라갔다 내려오는 계단 비트): 음이 오르면 오른쪽 한 칸, 내리면 왼쪽 한 칸
                    # (5반음 넘게 뛰면 두 칸), 같은 음이면 가던 방향으로 한 칸. 끝을 넘으면 반대쪽 끝에서 같은 방향으로
                    # 새 계단을 시작한다(끝에서 튕기면 0·1·0·1 지그재그가 돼 계속 내려가는 멜로디와 안 맞았다).
                    if stair['t'] is not None and t - stair['t'] < 1.0:
                        dp = e['pitch'] - stair['p']
                        stair['dir'] = 1 if dp > 0 else -1 if dp < 0 else stair['dir']
                        want = stair['lane'] + stair['dir'] * (2 if abs(dp) >= 5 else 1)
                        if want > 6 or want < 0:
                            want = 0 if want > 6 else 6
                    else:
                        recent = [(rt, p) for rt, p in recent if t - rt < 4] + [(t, e['pitch'])]
                        ps = [p for _, p in recent]
                        want = 3 if max(ps) - min(ps) < 1e-6 else int(round((e['pitch'] - min(ps)) / (max(ps) - min(ps)) * 6))
                    cands = [want] + sorted((x for x in range(7) if x != want), key=lambda x: (abs(x - want), used(x)))
                    lane = next((x for x in cands if free(x, t, .2)), None)
                    if lane is None:
                        continue
                    stair.update(t=t, p=e['pitch'], lane=lane)
                    lanes = [lane]
                    hold = 0.0
                    nxt = times[order[k + 1]] if k + 1 < len(order) else old['duration']
                    quiet = min(e['sustain'], 2.0, nxt - t - .15, heard_end - t - .05)
                    if not e['drum'] and e['sustain'] >= .6 and quiet >= .4:
                        hold = round(quiet, 3)
                        holds += 1
                    last_use[lane] = t
                    busy_until[lane] = t + hold
                    uses.append((t, lane))
                    notes.append({'t': round(t, 4), 'lane': lane, 'hold': hold, 'drum': e['drum'] or 'tom', 'source': 'attack-v1'})
                    run_side, run_len, run_t = None, 0, t
                    continue
                if e['drum']:
                    # 드럼 자리 안에서 최근 2초 동안 덜 쓴 키부터(한 키에 몰리지 않게)
                    base = DRUM_LANES[e['drum']]
                    cands = sorted(base, key=lambda x: (used(x), base.index(x)))
                else:
                    recent = [(rt, p) for rt, p in recent if t - rt < 4] + [(t, e['pitch'])]
                    ps = [p for _, p in recent]
                    lo, hi = min(ps), max(ps)
                    pos = .5 if hi - lo < 1e-6 else (e['pitch'] - lo) / (hi - lo)
                    want = int(round(pos * 6))
                    if run_len >= 4 and t - run_t < .3 and side(want) == run_side:
                        want = 6 - want                       # 한 손으로 4번 넘게 이어지면 반대 손으로
                    cands = sorted(range(7), key=lambda x: (abs(x - want), used(x)))
                if run_len >= 4 and t - run_t < .3:
                    cands = sorted(cands, key=lambda x: side(x) == run_side)   # 드럼도 반대 손 먼저(순서는 유지)
                lane = next((x for x in cands if free(x, t)), None)
                if lane is None:
                    lane = min(range(7), key=lambda x: (not free(x, t), used(x), -(t - last_use[x])))
                    if not free(lane, t):
                        continue
                lanes = [lane]
                partners = [6 - lane if lane != 3 else 1, 6 - lane if lane != 3 else 5]
                for extra in partners + [lane - 1, lane + 1, lane - 2, lane + 2, 3, 0, 6]:
                    if len(lanes) >= size[k]:
                        break
                    if 0 <= extra <= 6 and extra not in lanes and free(extra, t):
                        lanes.append(extra)
                hold = 0.0
                nxt = times[order[k + 1]] if k + 1 < len(order) else old['duration']
                if len(lanes) == 1 and not e['drum'] and e['sustain'] >= .6:
                    # 누르는 동안 다른 노트가 오지 않을 만큼(모든 난이도)
                    quiet = min(e['sustain'], 2.0, nxt - t - .15, heard_end - t - .05)
                    if quiet >= .4:
                        hold = round(quiet, 3)
                    elif level == 'hard' and side(lane) != 'C' and holds < .05 * len(order) and t >= lock_until:
                        # 어려움: 반대 손은 계속 치면서 누르는 긴 노트(박자의 5%까지) — 그동안 이 손엔 노트를 두지 않는다
                        busy = min(e['sustain'], 1.6, heard_end - t - .05)
                        if busy >= .5:
                            hold = round(busy, 3)
                            lock_side, lock_until = side(lane), t + hold + .15
                if hold:
                    holds += 1
                for x in lanes:
                    last_use[x] = t
                    busy_until[x] = t + hold
                    uses.append((t, x))
                    notes.append({'t': round(t, 4), 'lane': x, 'hold': hold, 'drum': e['drum'] or 'tom', 'source': 'attack-v1'})
                sides = {side(x) for x in lanes} - {'C'}
                s1 = next(iter(sides)) if len(sides) == 1 else None
                if s1 and s1 == run_side and t - run_t < .3:
                    run_len += 1
                else:
                    run_side, run_len = s1, 1 if s1 else 0
                run_t = t

            chart = dict(old)
            chart['notes'] = sorted(notes, key=lambda n: (n['t'], n['lane']))
            chart['noteCount'] = len(notes)
            chart['snapped'] = 'attack-v1'
            chart['bpm'] = song['bpm']                        # 곡 목록의 BPM을 따른다(목록을 고치면 채보도)
            return chosen, chart, size, order

        chosen = set()
        for level in ('easy', 'normal', 'hard'):
            path = os.path.join(ROOT, 'songs', song['charts'][level])
            want = HARD_LEVEL.get(song['title']) if level == 'hard' else \
                normal_level(song['title']) if level == 'normal' else None
            if want:
                # 목표 레벨이 될 때까지 밀도(초당 시각)를 0.25씩 올린다(보통은 1.5부터 — 낮은 레벨도 되게). 동시 키는 레벨표대로.
                # 가사 단어는 늘 먼저 들어가므로 가장 낮은 밀도에서도 목표를 넘으면 그 결과를 쓴다.
                gap_beats, rates, chords = (.25, np.arange(4.0, 7.01, .25), HARD_CHORDS) if level == 'hard' else \
                    (.5, np.arange(1.5, 5.01, .25), NORMAL_CHORDS)
                for rate in rates:
                    got = build(level, chosen, (gap_beats, float(rate)) + chords[want])
                    if rating(got[1]) >= want:
                        break
            else:
                got = build(level, chosen, LEVEL[level])
            chosen, chart, size, order = got
            old = chart
            dist = np.bincount(size, minlength=5)[1:]
            nt = np.array(sorted({n['t'] for n in chart['notes']}))
            cover = (sum(1 for w in words if len(nt) and np.min(np.abs(nt - w)) <= .07) / len(words) * 100) if words else None
            print(f"  {level}: 레벨 {rating(chart)} 가사 노트 {'-' if cover is None else f'{cover:.0f}%'} 시각 {len(order)}(초당 {len(order) / old['duration']:.2f}) 노트 {len(chart['notes'])} "
                  f"동시키 1:{dist[0]} 2:{dist[1]} 3:{dist[2]} 4:{dist[3]} 긴노트 {sum(1 for n in chart['notes'] if n['hold'] > 0)}", flush=True)
            if '--write' in sys.argv:
                os.makedirs(BACKUP, exist_ok=True)
                if not os.path.exists(os.path.join(BACKUP, song['charts'][level])):
                    shutil.copy(path, os.path.join(BACKUP, song['charts'][level]))
                with open(path, 'w', encoding='utf-8', newline='') as out:
                    json.dump(chart, out, ensure_ascii=False, separators=(',', ':'))
    if '--write' in sys.argv:
        # 곡 목록의 레벨 숫자(곡 찾기·난이도 버튼)도 새 채보에 맞춘다
        import subprocess
        subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'update-levels.py'), '--write'], check=True,
                       stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
