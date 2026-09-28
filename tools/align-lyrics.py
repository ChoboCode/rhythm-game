"""가사 시각을 실제 노래에 다시 맞춘다 — 황금빛(가사 채우기)이 노래와 같이 움직이고, 채보가 가사에 노트를 놓을 수 있게.

사용자: "멜로디에는 항상 노트가 오도록, 가사가 들려올 때 노트가 오도록. 가사 작업을 연동하면 편할 듯.
        일부 곡엔 황금빛이 안 맞고, 황금빛이 안 될 때도 있음."
예전 가사 파일은 줄의 절반만 단어 시각이 있고(나머지는 줄 전체에 고르게 채움), 0.3초짜리 줄도 있어 채우기가 한순간에
끝나거나 바로 사라졌다.

1. 분리된 보컬 스템(%TEMP%/rhythm-game-stems/keep/htdemucs/<곡>/vocals.wav)을 faster-whisper large-v3로 단어 시각과 함께 받아 적는다
   (반주가 없어 정확하다. 가사 앞부분을 힌트로 준다).
2. 알고 있는 가사와 받아 적은 글자를 **글자 단위**로, 줄마다 그 줄 시각 ±2초 안에서만 맞춘다(공백·문장부호 무시,
   띄어쓰기·일부 오인식에 강하고, 반복되는 후렴에 엉뚱하게 붙지 않는다). 예전 자료에서 글자 수에 비해 짧게 몰려 있던
   줄은 앞뒤 정상 줄 사이 전체(최대 +12초)에서 찾는다.
   맞은 글자의 시각으로 각 단어의 시작을 정한다.
3. 단어 시작을 보컬의 실제 소리 시작(±0.08초)에 붙인다.
4. 못 맞춘 단어는 앞뒤 단어 사이에 글자 수대로 나눈다. 한 줄에서 맞은 글자가 30% 미만이면 그 줄은 예전 시각의 창 안에서 나눈다.
5. 모든 줄에 단어 시각(t·end)을 넣고, 줄 끝 = 마지막 단어 끝(다음 줄 시작을 넘지 않게, 글자당 최소 0.1초).

사용: python tools/align-lyrics.py [곡 제목 ...] [--write]   (쓰기 전 원본은 _lyrics_backup/ 에 복사)
      python tools/align-lyrics.py --sanitize                  (받아쓰기 없이 몰린 줄 펴기·단어를 줄 안으로 다듬기)
"""
import difflib
import json
import os
import re
import shutil
import sys
import tempfile
import warnings

import librosa
import numpy as np

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP = os.path.join(tempfile.gettempdir(), 'rhythm-game-stems', 'keep', 'htdemucs')
BACKUP = os.path.join(ROOT, '_lyrics_backup')
SR, HOP = 22050, 64
SNAP = .08


def norm_chars(text):
    return [c for c in text.lower() if c.isalnum()]


def vocal_onsets(y):
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, n_fft=1024, lag=2, max_size=3)
    peaks = librosa.util.peak_pick(env, pre_max=8, post_max=8, pre_avg=40, post_avg=40,
                                   delta=float(np.median(env)), wait=8)
    return np.array(sorted(p * HOP / SR for p in peaks))


def snap(t, onsets):
    i = np.searchsorted(onsets, t)
    best = t
    for j in (i - 1, i):
        if 0 <= j < len(onsets) and abs(onsets[j] - t) <= SNAP and abs(onsets[j] - t) < abs(best - t) + 1e-9:
            best = float(onsets[j])
    return best


def transcribe(model, path, lang, prompt):
    segments, _ = model.transcribe(path, language=lang, word_timestamps=True, beam_size=5,
                                   condition_on_previous_text=False, initial_prompt=prompt,
                                   vad_filter=True, vad_parameters={'min_silence_duration_ms': 400})
    chars = []                                         # (글자, 시각)
    for seg in segments:
        for w in seg.words or []:
            cs = norm_chars(w.word)
            for k, c in enumerate(cs):
                chars.append((c, w.start + (w.end - w.start) * k / max(1, len(cs)), w.end))
    return chars


def align(lines, rec, onsets):
    # 알고 있는 가사의 글자 → (줄, 단어) 위치
    words = [[w for w in line['text'].split()] for line in lines]
    k_chars, k_pos = [], []
    for li, ws in enumerate(words):
        for wi, w in enumerate(ws):
            for c in norm_chars(w):
                k_chars.append(c)
                k_pos.append((li, wi))
    # 줄마다 그 줄 시각 ±2초 안에서 받아 적은 글자와만 맞춘다(후렴처럼 같은 가사가 반복돼도 엉뚱한 곳에 붙지 않게)
    rec_t = np.array([t for _, t, _ in rec])

    def squeezed(i):
        l = lines[i]
        end = l['end'] if (l.get('end') or 0) > l['t'] else (lines[i + 1]['t'] if i + 1 < len(lines) else l['t'] + 5)
        return end - l['t'] < min(.6, .06 * max(1, len(norm_chars(l['text']))))
    first, ends = {}, {}
    matched_chars = [0] * len(lines)
    total_chars = [0] * len(lines)
    start_idx = 0
    for li, line in enumerate(lines):
        idxs = [i for i in range(start_idx, len(k_chars)) if k_pos[i][0] == li]
        start_idx = idxs[-1] + 1 if idxs else start_idx
        total_chars[li] = len(idxs)
        if not idxs:
            continue
        nxt = lines[li + 1]['t'] if li + 1 < len(lines) else line['t'] + 8
        hi_t = line['end'] if (line.get('end') or 0) > line['t'] else nxt
        lo_w, hi_w = line['t'] - 2, max(hi_t, line['t'] + 1) + 2
        if squeezed(li):
            # 예전 자료에서 글자 수에 비해 짧게 몰린 줄(반복 후렴 등): 앞뒤 정상 줄 사이 전체에서 찾는다
            a = li - 1
            while a >= 0 and squeezed(a):
                a -= 1
            b = li + 1
            while b < len(lines) and squeezed(b):
                b += 1
            lo_w = (lines[a]['end'] if a >= 0 and (lines[a].get('end') or 0) > lines[a]['t'] else line['t'] - 8) - .5
            hi_w = min(lines[b]['t'] + 2 if b < len(lines) else line['t'] + 12, line['t'] + 12)
        win = np.where((rec_t >= lo_w) & (rec_t <= hi_w))[0]
        if not len(win):
            continue
        sm = difflib.SequenceMatcher(None, ''.join(k_chars[i] for i in idxs), ''.join(rec[j][0] for j in win), autojunk=False)
        for x, y, n in sm.get_matching_blocks():
            for k in range(n):
                pos, r = k_pos[idxs[x + k]], rec[win[y + k]]
                matched_chars[li] += 1
                if pos not in first:
                    first[pos] = r[1]
                ends[pos] = r[2]
    out, stats = [], {'lines': len(lines), 'kept': 0, 'shift': []}
    for li, line in enumerate(lines):
        ws = words[li]
        nxt = lines[li + 1]['t'] if li + 1 < len(lines) else line['t'] + 30
        ok = total_chars[li] and matched_chars[li] / total_chars[li] >= .3
        starts = [first.get((li, wi)) if ok else None for wi in range(len(ws))]
        if not any(s is not None for s in starts):
            lo, hi = line['t'], line.get('end') if (line.get('end') or 0) > line['t'] else nxt
            stats['kept'] += 1
        else:
            lo = min(s for s in starts if s is not None)
            hi = max(ends.get((li, wi), 0) for wi in range(len(ws)) if starts[wi] is not None)
            lo = min(lo, lo if starts[0] is not None else lo - .15 * len(norm_chars(ws[0])))
        # 못 맞춘 단어는 앞뒤 사이에 글자 수대로
        size = [max(1, len(norm_chars(w))) for w in ws]
        known = [(i, s) for i, s in enumerate(starts) if s is not None]
        anchors = [(-1, lo)] + known + [(len(ws), max(hi, lo + .1 * sum(size)))]
        for (i0, t0), (i1, t1) in zip(anchors, anchors[1:]):
            gap = [i for i in range(i0 + 1, i1)]
            if not gap:
                continue
            span_chars = sum(size[i] for i in range(max(0, i0), i1)) or 1
            acc = sum(size[i] for i in range(max(0, i0), gap[0])) if i0 >= 0 else 0
            for i in gap:
                starts[i] = t0 + (t1 - t0) * acc / span_chars
                acc += size[i]
        starts = [snap(s, onsets) for s in starts]
        for i in range(1, len(starts)):                 # 순서 보장
            starts[i] = max(starts[i], starts[i - 1] + .05)
        line_end = max(hi, starts[-1] + .1 * size[-1])
        line_end = min(line_end, nxt - .02) if li + 1 < len(lines) else line_end
        line_end = max(line_end, starts[-1] + .12)
        wl = []
        for i, w in enumerate(ws):
            e = starts[i + 1] if i + 1 < len(ws) else line_end
            wl.append({'t': round(starts[i], 3), 'end': round(max(e, starts[i] + .08), 3), 'text': w})
        new = dict(line)
        new.pop('resynced', None)
        new['t'], new['end'], new['words'] = wl[0]['t'], round(line_end, 3), wl
        stats['shift'].append(abs(new['t'] - line['t']))
        out.append(new)
    # 줄 순서가 뒤집히면(뒤 줄이 앞 줄보다 먼저 시작) 예전 시각에서 더 많이 벗어난 줄을 예전 창으로 되돌린다
    def back_to_old(i):
        line, ws = lines[i], words[i]
        nxt = lines[i + 1]['t'] if i + 1 < len(lines) else line['t'] + 8
        lo, hi = line['t'], line['end'] if (line.get('end') or 0) > line['t'] else nxt
        size = [max(1, len(norm_chars(w))) for w in ws]
        acc, st = 0, []
        for n in size:
            st.append(snap(lo + (hi - lo) * acc / sum(size), onsets))
            acc += n
        for k in range(1, len(st)):
            st[k] = max(st[k], st[k - 1] + .05)
        end = max(hi, st[-1] + .12)
        new = dict(line)
        new.pop('resynced', None)
        new['words'] = [{'t': round(st[k], 3), 'end': round(st[k + 1] if k + 1 < len(st) else end, 3), 'text': w}
                        for k, w in enumerate(ws)]
        new['t'], new['end'] = new['words'][0]['t'], round(end, 3)
        out[i] = new
        stats['kept'] += 1
    need = lambda i: min(.6, .06 * len(norm_chars(lines[i]['text'])))
    for _ in range(3):
        for i in range(1, len(out)):
            # 앞 줄이 글자 수만큼 불릴 틈도 없이 뒤 줄이 시작하면 부딪힌 것(비슷한 가사를 앞 줄 소리에서 잡은 경우가 많다)
            if out[i]['t'] < out[i - 1]['t'] + max(.1, min(need(i - 1), lines[i]['t'] - lines[i - 1]['t'])):
                worse = i if abs(out[i]['t'] - lines[i]['t']) >= abs(out[i - 1]['t'] - lines[i - 1]['t']) else i - 1
                back_to_old(worse)
    # 글자 수에 비해 너무 짧은 줄(두 줄의 맞춤이 부딪힘)은 예전 창이 더 길면 예전 창으로
    for i in range(len(out)):
        nxt = out[i + 1]['t'] if i + 1 < len(out) else out[i]['end']
        if min(out[i]['end'], nxt) - out[i]['t'] < need(i):
            old_hi = lines[i]['end'] if (lines[i].get('end') or 0) > lines[i]['t'] else lines[i]['t'] + need(i)
            prev_ok = i == 0 or out[i - 1]['t'] + .1 <= lines[i]['t']
            next_ok = i + 1 >= len(out) or lines[i]['t'] + need(i) <= out[i + 1]['t']
            if old_hi - lines[i]['t'] >= need(i) and prev_ok and next_ok:
                back_to_old(i)
    for i in range(len(out) - 1):                      # 줄 끝은 다음 줄 시작을 넘지 않게(단, 시작보다는 뒤)
        out[i]['end'] = round(max(out[i]['t'] + .12, min(out[i]['end'], out[i + 1]['t'])), 3)
        out[i]['words'][-1]['end'] = round(max(out[i]['words'][-1]['t'] + .08, min(out[i]['words'][-1]['end'], out[i]['end'])), 3)
    return out, stats


def spread_squeezed(lines, onsets):
    """예전 자료에서 온, 글자 수에 비해 너무 짧게 몰린 줄 묶음(예: 후렴 4줄이 1.2초)을 다음 정상 줄 전까지 글자 수대로 편다.
    한 줄은 글자당 최대 0.35초까지만(뒤에 긴 간주가 있어도 끝없이 늘이지 않는다). 단어 시작은 보컬 소리 시작에 붙인다."""
    chars = lambda l: max(1, len(norm_chars(l['text'])))
    short = lambda l: l['end'] - l['t'] < min(.6, .06 * chars(l))
    i = 0
    while i < len(lines):
        if not short(lines[i]):
            i += 1
            continue
        j = i
        while j < len(lines) and short(lines[j]):
            j += 1
        start = lines[i]['t']
        stop = lines[j]['t'] - .05 if j < len(lines) else start + .35 * sum(chars(l) for l in lines[i:j])
        total = sum(chars(l) for l in lines[i:j])
        span = min(stop - start, .35 * total)
        if span > lines[j - 1]['end'] - start + .2:
            t = start
            for l in lines[i:j]:
                dur = span * chars(l) / total
                ws = l['words']
                size = [max(1, len(norm_chars(w['text']))) for w in ws]
                acc, st = 0, []
                for n in size:
                    st.append(snap(t + dur * acc / sum(size), onsets))
                    acc += n
                st[0] = t
                for k in range(1, len(st)):
                    st[k] = min(max(st[k], st[k - 1] + .05), t + dur - .02)
                for k, w in enumerate(ws):
                    w['t'] = round(st[k], 3)
                    w['end'] = round(st[k + 1] if k + 1 < len(st) else t + dur, 3)
                l['t'], l['end'] = round(t, 3), round(t + dur, 3)
                l['spread'] = True
                t += dur
        i = j
    return lines


def sanitize(lines, duration):
    """단어는 줄 안에(line.t ≤ 단어 시작, 단어 끝 ≤ line.end), 순서대로, 줄 끝은 곡 길이 안에."""
    for l in lines:
        l['end'] = round(min(l['end'], duration + .2), 3)
        if l['end'] <= l['t']:
            l['end'] = round(l['t'] + .1, 3)
        ws, n = l['words'], len(l['words'])
        room = l['end'] - l['t']
        for i, w in enumerate(ws):
            lo = l['t'] if i == 0 else ws[i - 1]['t'] + min(.01, room / (2 * n))
            w['t'] = round(min(max(w['t'], lo), l['end'] - room * (n - i) / (2 * n)), 3)
        ws[0]['t'] = l['t']
        for i, w in enumerate(ws):
            nxt = ws[i + 1]['t'] if i + 1 < n else l['end']
            w['end'] = round(max(min(w['end'], nxt if i + 1 < n else l['end'], l['end']), w['t'] + .001), 3)
            w['end'] = min(w['end'], l['end'])
    return lines


def cuda_dlls():
    """pip으로 깐 nvidia-cublas-cu12·cudnn의 DLL 폴더를 찾아 등록한다(윈도우에서 cublas64_12.dll을 못 찾는 문제)."""
    import importlib.util
    spec = importlib.util.find_spec('nvidia')
    for base in (list(spec.submodule_search_locations) if spec else []):
        for sub in ('cublas', 'cudnn'):
            d = os.path.join(base, sub, 'bin')
            if os.path.isdir(d):
                os.add_dll_directory(d)
                os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH', '')


def main():
    if '--sanitize' in sys.argv:                       # 받아쓰기 없이 지금 가사 파일만 다듬는다
        for song in json.load(open(os.path.join(ROOT, 'songs', 'songs.json'), encoding='utf-8')):
            if not song.get('lyrics'):
                continue
            path = os.path.join(ROOT, 'songs', song['lyrics'])
            data = json.load(open(path, encoding='utf-8'))
            vocals = os.path.join(KEEP, os.path.splitext(song['file'])[0], 'vocals.wav')
            onsets = vocal_onsets(librosa.load(vocals, sr=SR, mono=True)[0])
            data['lines'] = sanitize(spread_squeezed(data['lines'], onsets), song['duration'])
            with open(path, 'w', encoding='utf-8', newline='') as out:
                json.dump(data, out, ensure_ascii=False, indent=1)
        print('가사 파일 다듬음')
        return
    cuda_dlls()
    from faster_whisper import WhisperModel
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    songs = json.load(open(os.path.join(ROOT, 'songs', 'songs.json'), encoding='utf-8'))
    songs = [s for s in songs if s.get('lyrics') and (not args or s['title'] in args)]
    model = WhisperModel('large-v3', device='cuda', compute_type='float16')
    for song in songs:
        path = os.path.join(ROOT, 'songs', song['lyrics'])
        data = json.load(open(path, encoding='utf-8'))
        lines = [l for l in data['lines'] if l.get('text', '').strip()]
        text = ' '.join(l['text'] for l in lines)
        lang = 'ko' if sum('가' <= c <= '힣' for c in text) > .3 * max(1, sum(c.isalpha() for c in text)) else 'en'
        name = os.path.splitext(song['file'])[0]
        vocals = os.path.join(KEEP, name, 'vocals.wav')
        rec = transcribe(model, vocals, lang, text[:200])
        onsets = vocal_onsets(librosa.load(vocals, sr=SR, mono=True)[0])
        new_lines, st = align(lines, rec, onsets)
        k = len(norm_chars(text))
        sm = difflib.SequenceMatcher(None, ''.join(norm_chars(text)), ''.join(c for c, _, _ in rec), autojunk=False)
        matched = sum(n for _, _, n in sm.get_matching_blocks()) / max(1, k)
        sh = np.array(st['shift'])
        print(f"{song['title']}: 글자 일치 {matched * 100:.0f}% · 줄 {st['lines']} (예전 창 유지 {st['kept']}) · "
              f"줄 시작 이동 중앙 {np.median(sh):.2f}s 최대 {sh.max():.2f}s", flush=True)
        if '--write' in sys.argv:
            os.makedirs(BACKUP, exist_ok=True)
            if not os.path.exists(os.path.join(BACKUP, song['lyrics'])):
                shutil.copy(path, os.path.join(BACKUP, song['lyrics']))
            data['lines'] = sanitize(spread_squeezed(new_lines, onsets), song['duration'])
            data['timing'] = 'vocal-aligned-v2'
            data['resyncNote'] = ('align-lyrics.py: 보컬 스템 faster-whisper large-v3 받아쓰기와 글자 단위로 맞춘 뒤 '
                                  '단어 시작을 보컬 소리 시작(±0.08초)에 붙임. 모든 줄에 단어 시각.')
            with open(path, 'w', encoding='utf-8', newline='') as out:
                json.dump(data, out, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
