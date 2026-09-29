"""몰아치기(drops)·쉬어가기(rests) 순간을 여러 독립 증거가 함께 가리키는 곳에서만 찾는다.

한 지표가 크게 튀는 곳이 아니라, 악기 분리(Demucs htdemucs)로 얻은 드럼·베이스와 원곡의 여러 특징이
동시에 "여기서 곡이 터진다 / 쉬어 간다"고 말하는 곳만 고른다.

증거(후보 시각 t 기준, 직전 B=[t-2,t-0.15] vs 직후 A=[t+0.05,t+2])
  1 drum    드럼 스템 음량이 크게 돌아옴/빠짐 (악기 분리)
  2 bass    베이스 스템 음량이 크게 돌아옴/빠짐
  3 mix     원곡 전체 음량 차
  4 bright  4kHz 이상 고음(심벌·하이햇, 필터 열림) 차
  5 density 드럼 타격 밀도(앞 4초 vs 뒤 4초)
  6 novelty 음색·화성 구조가 바뀌는 경계(자기유사 행렬 체커보드 노벨티)
  7 section 뒤(몰아치기) 또는 앞(쉬어가기) 8초가 곡에서 센 구간인지
  8 buildup (몰아치기) 앞 4초에 저음/드럼 빠짐, 또는 밀도·밝기가 차오름(스네어 롤·라이저)
  9 chorus  (몰아치기) 그 자리(-1.5~+2.5초)에서 반복 가사(후렴)가 시작됨
필수 조건: 박 위에 있음(곡 BPM으로 잡은 박마다 평가), 뒤 구간이 유지됨(몰아치기) / 빠진 채 유지됨(쉬어가기).
판정(사람이 듣는 방식에 맞춰 증거를 똑같이 한 표씩 세지 않는다)
  몰아치기: 임팩트 필수 — 전체 +4dB 이상 그리고 (베이스 +15dB 또는 드럼 +10dB), 뒤 6초 유지.
            맥락 6개(빌드업·구조경계·센구간·후렴·밝아짐·밀도) 중 3개 이상. 후렴이면 가점.
  쉬어가기: 센 구간(앞 8초 상위 30%)에서 전체 -4dB 이상 그리고 (베이스 -15dB 또는 드럼 -10dB),
            3초 이상 빠진 채. 맥락 4개(구조경계·어두워짐·밀도 감소·뒤가 잔잔) 중 2개 이상.
  점수가 곡 전체 하한(몰아치기 14, 쉬어가기 12.5) 이상인 것만, 곡당 몰아치기 2·쉬어가기 1,
  20초 간격, 20초 이전(도입부)·끝 10초 제외. 착지 박은 이웃 박 중 리듬 파트가 가장 가파르게
  들어오는(빠지는) 박으로 맞춘다.

사용: python tools/find-drops.py            # 결과·근거 출력 (처음엔 악기 분리에 GPU로 곡당 몇 초)
      python tools/find-drops.py --write    # songs.json 각 곡의 "drops"·"rests" 한 줄씩만 넣거나 바꿈
악기 분리 결과는 %TEMP%/rhythm-game-stems 에 곡별 요약(npz)으로 캐시하고 원본 wav는 지운다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import librosa
import numpy as np
import scipy.signal

if not hasattr(scipy.signal, 'hann'):          # librosa 0.9 박 추적이 옛 scipy 이름을 쓴다
    scipy.signal.hann = scipy.signal.windows.hann

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, 'songs', 'songs.json')
CACHE = os.path.join(tempfile.gettempdir(), 'rhythm-game-stems')
SR, HOP = 22050, 512
FPS = SR / HOP

SKIP_INTRO, SKIP_OUTRO, MIN_GAP = 20.0, 10.0, 20.0
MAX_DROPS, MAX_RESTS = 2, 1
DROP_CONTEXT, REST_CONTEXT = 3, 2
# 곡 전체에 걸친 하한 — 곡별 점수 분포에서 뚜렷한 순간(몰아치기 14↑, 쉬어가기 12.5↑)과
# 애매한 순간(8~13)이 갈린다. 이 아래는 어느 곡이든 넣지 않는다.
DROP_MIN_SCORE, REST_MIN_SCORE = 14.0, 12.5
# 사람이 들어 보고 몰아치기를 빼기로 한 곡과 이유
NO_DROPS = {
    '두 사람의 행복을 빌어': '발라드라 빠르게 쏟아지는 연출이 곡과 어울리지 않음(사용자 확인)',
    'My Cocktail': '몰아치기가 어울리는 노래가 아님(사용자 확인)',
    '말하지 못한 진심': '몰아치기 삭제(사용자 확인)',
    '폴라로이드 사진': '몰아치기는 아예 안 맞음(사용자 확인) — 시티팝이라 쉬어가기만(find-rests.py)',
}
# 쉬어가기를 find-rests.py가 맡는 곡(시티팝·발라드, 사용자 선택) — 여기서는 rests를 쓰지 않는다
_spec = __import__('importlib.util').util.spec_from_file_location('find_rests', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'find-rests.py'))
_fr = __import__('importlib.util').util.module_from_spec(_spec)
_spec.loader.exec_module(_fr)
SOFT_SONGS = _fr.SOFT_SONGS
# 연출을 아예 넣지 않는 곡
NO_EFFECTS = {
    '입시 스트레스': '어울리는 노래가 아님 — 구간 전부 제거(사용자 확인)',
}
# 몰아치기는 두되 그 앞에서 느려지지(쉬어 가지) 않는 곡: 드롭에 "slow": false를 적는다
NO_SLOW = {
    'Bass Control': '쉬어가기가 곡과 안 맞음(사용자 확인) — 느려지지 않고 착지에서 바로 몰아친다',
}
# 선율을 계속 연주해야 하는 곡은 자동 검출 결과도 쉬어가기로 넣지 않는다.
NO_RESTS = {'Stay with me_ make me real', 'My Cocktail'}
# 가사의 특정 낱말에서 "숨 쉬기"(쉬어가기)를 한다: 곡 → (그 낱말, 끝낼 낱말까지의 개수, 이유)
BREATH_WORDS = {}
# 사람이 비교해 고르도록 미리보기 후보를 함께 적어 두는 곡(게임은 쓰지 않고 rush-check가 보여 준다)
DROP_CANDIDATES = {}
# 사람이 들어 보고 하이라이트를 직접 고른 곡: 리듬이 돌아오는 대략의 시각(초)과 이유.
# 정확한 착지·타격·브레이크 시작은 여기서부터 다시 분석해 잰다.
MANUAL_DROPS = {
    '거침없이 가자 (NC 다이노스)': ([{'t': 57.353, 'hits': [57.353, 57.775, 58.958, 59.35]},
                                   {'t': 112.632, 'hits': [112.632, 112.957, 114.225, 114.611]},
                                   {'t': 158.398, 'hits': [158.398, 158.824, 160.033, 160.395]}],
                                  '"Dinos, Go!" 세 곳 — "고"(드럼·기타 재진입, 스템) + 관중 "헤이!" 두 번(사용자 탭 57.724/59.284, '
                                  '112.952/114.534, 158.758/160.318을 원곡 온셋 ±0.08초로 보정: 탭보다 0.005~0.08초 늦음). '
                                  '사용자: "고랑 헤이 둘 다 구현". "Dinos, Go!"가 구간마다 두 번 → 두 번째 "고"(한 마디 뒤 드럼 재진입 58.958/114.225/'
                                  '160.033)도 타격으로(사용자: 두 번인데 한 번만 몰아침)'),
    # 숫자 대신 {'t', 'hits'}를 주면 그 타격들을 그대로 쓴다(보컬 스템 온셋으로 잰 시각)
    # 'keys'는 타격마다 누를 손가락 자리(a s d = 왼손 S D F, j k l = 오른손 J K L)
    'G_Force': ([{'t': 66.427, 'hits': [66.427, 66.842, 67.301, 67.727], 'keys': ['asdjkl', 'adjl', 'sk', 'sk']}],
                '"3, 2, 1, Ho!" 카운트다운에 맞춰 네 번, 3=6키·2=4키·1=2키·Ho=2키(사용자). 보컬 온셋 66.427/66.842/'
                '67.301/67.727, 박 0.43초'),
    'Break It Down': ([{'t': 167.85, 'hits': [167.85, 168.202, 168.584]}],
                      '2:47.8 세 번 — 사용자 탭 167.841/168.191/168.591이 드럼 스템의 실제 시작(167.850/168.202/168.584)과 '
                      '맞음. 자동 측정 첫 타격 167.771은 0.08초 빨랐다'),
    'Stay with me_ make me real': ([96.29], '0:54.6 몰아치기는 보컬 구절에 겹쳐서 뺌. 쉬어가기는 사용자가 전부 제거 요청'),
}


def breath_spans(lyrics_path, word, count):
    """가사에서 word가 시작하는 순간부터 그 뒤 count개 낱말이 끝나는 순간까지."""
    spans = []
    for line in json.load(open(lyrics_path, encoding='utf-8'))['lines']:
        words = line.get('words') or []
        for i, w in enumerate(words):
            if w['text'].startswith(word) and i + count - 1 < len(words):
                spans.append({'from': round(w['t'], 3), 'to': round(words[i + count - 1]['end'], 3), 'breath': True})
    return spans
FEATURE_VERSION = 2      # 박별 증거 계산을 바꾸면 올린다(캐시 무효화)


def f(t):
    return int(round(t * FPS))


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-6))


def rms_env(y):
    return db(librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0])


def separate(paths):
    todo = [p for p in paths if not os.path.exists(cache_file(p))]
    if not todo:
        return
    out = os.path.join(CACHE, 'sep')
    subprocess.run([sys.executable, '-m', 'demucs', '-n', 'htdemucs', '-d',
                    'cuda' if torch_cuda() else 'cpu', '-o', out] + todo, check=True)
    for p in todo:
        stem_dir = os.path.join(out, 'htdemucs', os.path.splitext(os.path.basename(p))[0])
        env = {}
        for stem in ('drums', 'bass', 'vocals', 'other'):
            y, _ = librosa.load(os.path.join(stem_dir, stem + '.wav'), sr=SR, mono=True)
            env[stem] = rms_env(y)
            if stem == 'drums':
                env['drum_onset'] = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
        np.savez_compressed(cache_file(p), **env)
        shutil.rmtree(stem_dir, ignore_errors=True)


def torch_cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def cache_file(path):
    return os.path.join(CACHE, os.path.splitext(os.path.basename(path))[0] + '.npz')


def chorus_starts(lyrics_path):
    if not lyrics_path or not os.path.exists(lyrics_path):
        return []
    lines = json.load(open(lyrics_path, encoding='utf-8'))['lines']
    keys = [''.join(ch for ch in str(l.get('text', '')).lower() if ch.isalnum()) for l in lines]
    count = {}
    for k in keys:
        if len(k) >= 4:
            count[k] = count.get(k, 0) + 1
    return [l['t'] for l, k in zip(lines, keys) if count.get(k, 0) >= 2]


def novelty_curve(y):
    """MFCC+크로마 자기유사 행렬에 체커보드 커널(약 8초)을 대어 구간 경계의 세기를 0~1로."""
    hop = 2048                                  # 약 0.09초
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=13, hop_length=hop)
    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=hop)
    feat = np.vstack([librosa.util.normalize(mfcc, axis=1), chroma])
    feat = librosa.util.normalize(feat, axis=0)
    ssm = feat.T @ feat
    half = int(4 * SR / hop)
    g = np.outer(np.hanning(2 * half), np.hanning(2 * half))
    sign = np.ones((2 * half, 2 * half))
    sign[:half, half:] = -1
    sign[half:, :half] = -1
    kernel = g * sign
    n = ssm.shape[0]
    pad = np.pad(ssm, half, mode='constant')
    nov = np.array([np.sum(pad[i:i + 2 * half, i:i + 2 * half] * kernel) for i in range(n)])
    nov = np.maximum(nov, 0)
    nov = nov / (nov.max() or 1)
    t_nov = np.arange(n) * hop / SR
    return t_nov, nov


def analyze(path, lyrics_path, bpm):
    y, _ = librosa.load(path, sr=SR, mono=True)
    duration = len(y) / SR
    stems = np.load(cache_file(path))
    spec = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    mix = rms_env(y)
    bright = db(spec[freqs > 4000].mean(axis=0))
    drums, bass, onset = stems['drums'], stems['bass'], stems['drum_onset']
    n = min(len(mix), len(bright), len(drums), len(bass), len(onset))
    mix, bright, drums, bass, onset = mix[:n], bright[:n], drums[:n], bass[:n], onset[:n]
    t_nov, nov = novelty_curve(y)
    choruses = chorus_starts(lyrics_path)

    # 박: 드럼 온셋으로 곡 BPM에 맞춰 잡는다. 어느 박이 마디 첫 박인지는 추정이 흔들리므로
    # 모든 박을 후보로 두고, 실제로 터지는 박(=첫 박)이 증거로 가려지게 한다.
    _, beats = librosa.beat.beat_track(onset_envelope=onset, sr=SR, hop_length=HOP,
                                       start_bpm=bpm or 120, tightness=400)
    beat_t = librosa.frames_to_time(beats, sr=SR, hop_length=HOP)

    hits = librosa.util.peak_pick(onset, pre_max=3, post_max=3, pre_avg=10, post_avg=10,
                                  delta=np.percentile(onset, 60) * .5, wait=3) / FPS

    full_drum = np.percentile(drums, 75)
    full_bass = np.percentile(bass, 75)
    win8 = np.array([np.median(mix[f(s):f(s + 8)]) for s in np.arange(0, duration - 8, 1)])

    def med(a, t0, t1):
        seg = a[max(0, f(t0)):max(1, f(t1))]
        return float(np.median(seg)) if len(seg) else float('nan')

    def rate(t0, t1):
        return np.sum((hits >= t0) & (hits < t1)) / max(.1, t1 - t0)

    def pct(v):
        return float((win8 < v).mean())

    def nov_at(t):
        i0, i1 = np.searchsorted(t_nov, t - .5), np.searchsorted(t_nov, t + .5)
        return float(nov[i0:i1].max()) if i1 > i0 else 0.

    # 박마다 증거를 모은다 (도입부·끝 제외)
    rows = []
    for t in beat_t:
        if t < SKIP_INTRO or t > duration - SKIP_OUTRO:
            continue
        d = {k: med(a, t + .05, t + 2) - med(a, t - 2, t - .15)
             for k, a in (('drum', drums), ('bass', bass), ('mix', mix), ('bright', bright))}
        rows.append(dict(
            t=round(float(t), 3), **{k: round(v, 2) for k, v in d.items()},
            dens=round(float(rate(t, t + 4) / max(.25, rate(t - 4, t))), 3),
            novelty=round(nov_at(t), 3),
            after8=round(pct(med(mix, t, t + 8)), 3), before8=round(pct(med(mix, t - 8, t)), 3),
            chorus=any(-1.5 <= c - t <= 2.5 for c in choruses),
            edge=round(med(bass, t + .02, t + .5) - med(bass, t - .5, t - .05)
                       + med(drums, t + .02, t + .5) - med(drums, t - .5, t - .05), 2),
            kept=round(float(np.mean((drums[f(t):f(t + 6)] >= full_drum - 8) |
                                     (bass[f(t):f(t + 6)] >= full_bass - 8))), 3),
            held=round(float(max(np.mean(bass[f(t):f(t + 3)] < full_bass - 12),
                                 np.mean(drums[f(t):f(t + 3)] < full_drum - 12))), 3),
            gone=round(float(max(np.mean(bass[f(t - 4):f(t)] < full_bass - 15),
                                 np.mean(drums[f(t - 4):f(t)] < full_drum - 15))), 3),
            rising=bool(rate(t - 2, t) / max(.25, rate(t - 4, t - 2)) >= 1.5
                        or med(bright, t - 1, t) - med(bright, t - 4, t - 3) >= 6),
        ))
    return rows


def judge_drop(r):
    """몰아치기: 임팩트(필수) + 맥락 증거. 통과하면 (점수, 근거), 아니면 None."""
    if r['kept'] < .85 or r['mix'] < 4 or not (r['bass'] >= 15 or r['drum'] >= 10):
        return None
    ctx = {'빌드업': r['gone'] >= .5 or r['rising'], '구조경계': r['novelty'] >= .4,
           '센구간': r['after8'] >= .7, '후렴': r['chorus'], '밝아짐': r['bright'] >= 6,
           '밀도': r['dens'] >= 1.5}
    if sum(ctx.values()) < DROP_CONTEXT:
        return None
    score = (r['mix'] / 3 + max(r['bass'] / 15, r['drum'] / 10) + 1.2 * sum(ctx.values())
             + r['novelty'] + r['after8'] + (2.5 if r['chorus'] else 0))
    return score, [k for k, v in ctx.items() if v]


def judge_rest(r):
    """쉬어가기: 센 구간에서 리듬 파트가 확 빠짐(필수) + 맥락 증거."""
    if (r['held'] < .85 or r['mix'] > -4 or r['before8'] < .7
            or not (r['bass'] <= -15 or r['drum'] <= -10)):
        return None
    ctx = {'구조경계': r['novelty'] >= .4, '어두워짐': r['bright'] <= -6, '밀도': r['dens'] <= 1 / 1.5,
           '뒤가잔잔': r['after8'] <= .4}
    if sum(ctx.values()) < REST_CONTEXT:
        return None
    score = -r['mix'] / 3 + max(-r['bass'] / 15, -r['drum'] / 10) + 1.2 * sum(ctx.values()) + r['novelty']
    return score, [k for k, v in ctx.items() if v]


def features(path, lyrics_path, bpm):
    cached = cache_file(path).replace('.npz', '.rows.json')
    if os.path.exists(cached):
        data = json.load(open(cached, encoding='utf-8'))
        if isinstance(data, dict) and data.get('version') == FEATURE_VERSION:
            return data['rows']
    rows = analyze(path, lyrics_path, bpm)
    json.dump({'version': FEATURE_VERSION, 'rows': rows}, open(cached, 'w', encoding='utf-8'))
    return rows


def sharpest(rows, t, sign):
    """이웃한 박들(±0.6초) 중 리듬 파트가 가장 가파르게 들어오는/빠지는 박 = 실제 첫 박."""
    near = [r for r in rows if abs(r['t'] - t) <= .6]
    return max(near, key=lambda r: sign * r['edge'])['t'] if near else t


def pick(found, limit):
    found.sort(reverse=True)
    chosen = []
    for score, t, why in found:
        if len(chosen) >= limit:
            break
        if all(abs(t - c[0]) >= MIN_GAP for c in chosen):
            chosen.append((t, round(score, 1), why))
    return sorted(chosen)


def write_field(text, title, key, values):
    """다른 줄의 서식은 그대로 두고 그 곡의 key 한 줄만 넣거나 바꾼다."""
    start = text.index('"title": ' + json.dumps(title, ensure_ascii=False))
    end = text.find('"title": ', start + 1)
    end = len(text) if end < 0 else end
    block = text[start:end]
    field = '"' + key + '": '
    line = field + json.dumps(values) + ','
    if field in block:
        head, rest = block.split(field, 1)
        block = head + line + '\n' + rest.split('\n', 1)[1]
    else:
        bpm = block.index('"bpm": ')
        eol = block.index('\n', bpm)
        indent = block[block.rindex('\n', 0, bpm) + 1:bpm]
        block = block[:eol + 1] + indent + line + '\n' + block[eol + 1:]
    return text[:start] + block + text[end:]


def rhythm_presence(stems):
    """드럼·베이스가 각각 "꽉 찬 수준"에서 12dB 안에 있는지(0.3초로 고르게)."""
    k = np.ones(13) / 13
    drums = np.convolve(stems['drums'], k, mode='same')
    bass = np.convolve(stems['bass'], k, mode='same')
    return drums >= np.percentile(drums, 75) - 12, bass >= np.percentile(bass, 75) - 12


def break_before(both, land):
    """착지 직전, 드럼과 베이스가 함께 꽉 차 있지 않던 구간의 시작(최대 12초 전). 1.5초 미만이면 None."""
    i = f(land - .15)
    while i > 0 and not both[i] and land - i / FPS < 12:
        i -= 1
    start = (i + 1) / FPS
    return round(start, 3) if land - start >= 1.5 else None


def rest_span(both, either, t):
    """쉬어가기: 둘이 함께 차 있다가 빠지는 순간 → 리듬(드럼이나 베이스)이 다시 0.5초 이상 찰 때까지, 최대 10초."""
    i = f(t - .5)
    while i < f(t + .5) and both[i]:
        i += 1
    start = i / FPS
    j, run = f(start + 1), 0
    while j < len(both) and (j - i) / FPS < 10:
        run = run + 1 if either[j] else 0
        if run >= f(.5):
            return round(start, 3), round((j - run + 1) / FPS, 3)
        j += 1
    return round(start, 3), round(min(start + 10, j / FPS), 3)


def strong_hits(audio_path, entry, bar):
    """리듬이 돌아온 뒤 한 마디 안에서, 뒤따르는 리듬(1~3마디 뒤)보다 확실히 도드라지는 원곡 타격들.
    원곡 3ms 해상도의 스펙트럼 변화(온셋 세기)로 잰다. 기준: 구간 최대의 55% 이상이고, 뒤따르는 리듬
    상위 10%의 1.2배(착지) / 1.5배(이어지는 타격) 이상. 0.15초 안의 연타는 하나로. 첫 타격이 "빡"(착지), 개수만큼 연출·S·K 노트.
    타격은 앞 타격에서 1.5박 안에 이어질 때만 한 묶음("빡·빡·빡")이다 — 더 떨어지면 평소 리듬의 킥이다
    (Bass Control 39.37·39.61은 착지 2박 뒤 그루브였는데 타격으로 잡혀 드롭 한가운데서 출렁였다)."""
    t0 = max(0, entry - .15)
    y, sr = librosa.load(audio_path, sr=SR, mono=True, offset=t0, duration=3 * bar + .3)
    hop = 64
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, n_fft=1024, lag=2, max_size=3)
    pk = librosa.util.peak_pick(env, pre_max=15, post_max=15, pre_avg=40, post_avg=40, delta=.3, wait=25)
    times = t0 + pk * hop / sr
    strength = env[pk]
    groove = strength[(times >= entry + bar) & (times <= t0 + 3 * bar)]
    win = (times >= t0) & (times <= entry + bar)
    if not win.any():
        return [round(entry, 3)]
    p90 = np.percentile(groove, 90) if len(groove) else 0
    land_floor = max(1.2 * p90, .55 * strength[win].max())      # 착지: 리듬이 돌아오는 첫 센 타격
    next_floor = max(1.5 * p90, .55 * strength[win].max())      # 이어지는 타격: 더 확실히 도드라져야
    beat = bar / 4
    hits = []
    for t, st in zip(times[win], strength[win]):
        if st < (next_floor if hits else land_floor) or (hits and t - hits[-1] < .15):
            continue
        if hits and t - hits[-1] > 1.5 * beat:
            break
        hits.append(round(float(t), 3))
        if len(hits) == 4:
            break
    return hits or [round(entry, 3)]


def mmss(t):
    return f'{int(t // 60)}:{t % 60:04.1f}'


def main():
    os.makedirs(CACHE, exist_ok=True)
    songs = json.load(open(MANIFEST, encoding='utf-8'))
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    if only:
        songs = [s for s in songs if s['title'] in only]
    separate([os.path.join(ROOT, 'songs', s['file']) for s in songs])
    text = open(MANIFEST, encoding='utf-8').read()
    for song in songs:
        lyrics = os.path.join(ROOT, 'songs', song['lyrics']) if song.get('lyrics') else None
        rows = features(os.path.join(ROOT, 'songs', song['file']), lyrics, song.get('bpm'))
        drop_c, rest_c = [], []
        for r in rows:
            for judge, bucket, floor in ((judge_drop, drop_c, DROP_MIN_SCORE), (judge_rest, rest_c, REST_MIN_SCORE)):
                verdict = judge(r)
                if verdict and verdict[0] >= floor:
                    bucket.append((verdict[0], r['t'], verdict[1]))
        drop_c = [(sc, sharpest(rows, t, 1), why) for sc, t, why in drop_c]
        rest_c = [(sc, sharpest(rows, t, -1), why) for sc, t, why in rest_c]
        audio_path = os.path.join(ROOT, 'songs', song['file'])

        def attack(t):
            """박 추적(약 23ms 격자, 온셋 지연 있음) 시각을 원음 3ms 해상도에서 ±0.2초 안
            에너지가 가장 가파르게 뛰는 순간(실제 타격)으로 맞춘다."""
            seg, _ = librosa.load(audio_path, sr=SR, mono=True, offset=max(0, t - .2), duration=.4)
            flux = librosa.onset.onset_strength(y=seg, sr=SR, hop_length=64, n_fft=512, lag=1, max_size=1)
            return round(max(0, t - .2) + int(np.argmax(flux)) * 64 / SR, 3)

        drop_c = [(sc, attack(t), why) for sc, t, why in drop_c]
        if song['title'] in NO_EFFECTS:
            text = write_field(text, song['title'], 'drops', [])
            if song['title'] not in SOFT_SONGS:
                text = write_field(text, song['title'], 'rests', [])
            print(f"{song['title']}: 연출 없음 — {NO_EFFECTS[song['title']]}", flush=True)
            continue
        fixed_hits = {}
        if song['title'] in MANUAL_DROPS:
            drops = []
            for m in MANUAL_DROPS[song['title']][0]:
                if isinstance(m, dict):
                    fixed_hits[m['t']] = m
                    drops.append((m['t'], 0, ['직접 지정']))
                else:
                    drops.append((attack(m), 0, ['직접 지정']))
        else:
            drops = [] if song['title'] in NO_DROPS else pick(drop_c, MAX_DROPS)
        stems = np.load(cache_file(audio_path))
        drums_on, bass_on = rhythm_presence(stems)
        both = drums_on & bass_on
        bar = 4 * 60 / (song.get('bpm') or 120)
        drop_out = []
        for t, sc, why in drops:
            fixed = fixed_hits.get(t)
            hits = fixed['hits'] if fixed else strong_hits(audio_path, t, bar)
            item = {'t': hits[0], 'hits': hits}
            if fixed and fixed.get('keys'):
                item['keys'] = fixed['keys']
            start = break_before(both, t)
            if song['title'] in NO_SLOW:
                item['slow'] = False
            elif start is not None:
                item['from'] = start
            drop_out.append(item)
        rest_out = []
        for t, sc, why in pick(rest_c, MAX_RESTS + 2):
            start, end = rest_span(both, drums_on | bass_on, t)
            # 몰아치기의 브레이크와 겹치면 그 몰아치기가 이미 "살살 쭉 → 빡"을 한다
            if any(d.get('from', d['t']) - 2 <= end and start <= d['t'] for d in drop_out):
                continue
            if len(rest_out) < MAX_RESTS and end - start >= 2:
                rest_out.append({'from': start, 'to': end})
        if song['title'] in BREATH_WORDS:
            word, count, _ = BREATH_WORDS[song['title']]
            rest_out = breath_spans(lyrics, word, count)
        if song['title'] in NO_RESTS:
            rest_out = []
        if song['title'] in DROP_CANDIDATES:
            cands = []
            for c in DROP_CANDIDATES[song['title']]:
                t = attack(c)
                hits = strong_hits(audio_path, t, bar)
                item = {'t': hits[0], 'hits': hits}
                start = break_before(both, t)
                if start is not None:
                    item['from'] = start
                cands.append(item)
            text = write_field(text, song['title'], 'dropCandidates', cands)
            print(f"  후보: {', '.join(mmss(c['t']) for c in cands)}")
        text = write_field(text, song['title'], 'drops', drop_out)
        if song['title'] not in SOFT_SONGS:
            text = write_field(text, song['title'], 'rests', rest_out)
        desc = ' · '.join(
            f"몰아치기 {mmss(d['t'])}" + (f" (브레이크 {mmss(d['from'])}부터)" if 'from' in d else '')
            + f" 타격 {len(d['hits'])}번 {d['hits']}" for d in drop_out)
        desc2 = ' · '.join(f"{'숨' if r.get('breath') else '쉬어가기'} {mmss(r['from'])}~{mmss(r['to'])}" for r in rest_out)
        print(f"{song['title']}: {desc or '-'} | {desc2 or '-'}", flush=True)
    json.loads(text)
    if '--write' in sys.argv:
        with open(MANIFEST, 'w', encoding='utf-8', newline='') as out:
            out.write(text)
        print('songs.json 갱신')


if __name__ == '__main__':
    main()
