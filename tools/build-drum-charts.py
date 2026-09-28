"""Build drum-led charts from real percussive attacks in a local song.

Usage: python tools/build-drum-charts.py "songs/곡.mp3" [--write]
Requires ffmpeg, numpy and scipy. Times are kept at detected attacks; they are
not forced onto a single BPM grid, which would move a live or shifting beat.
"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter, uniform_filter1d
from scipy.signal import find_peaks, stft


SR, HOP, FFT = 22050, 256, 2048
BANDS = {'kick': (35, 160), 'snare': (160, 2600), 'hat': (2600, 9500)}
PRESET = {
    'easy':   {'threshold': {'kick': .70, 'snare': .68, 'hat': 1.1}, 'gap': .27, 'nps': 2.6, 'crash_gap': 8.0},
    'normal': {'threshold': {'kick': .53, 'snare': .53, 'hat': .65}, 'gap': .145, 'nps': 4.6, 'crash_gap': 4.8},
    'hard':   {'threshold': {'kick': .39, 'snare': .38, 'hat': .39}, 'gap': .088, 'nps': 7.2, 'crash_gap': 3.5},
}
HOLD_LANE_GUARD = .18
TAP_LANE_GAP = .115


def hand(lane):
    return -1 if lane < 3 else 1 if lane > 3 else 0


def arrange_around_holds(notes):
    """Reserve every long note, then move nearby taps to playable fingers."""
    holds = [note for note in notes if note['hold'] > 0]
    placed = holds.copy()
    taps = sorted((note for note in notes if note['hold'] == 0), key=lambda n: n['t'])

    for note in taps:
        t = note['t']
        preferred = note['lane']
        nearby_holds = [hold for hold in holds
                        if hold['t'] - HOLD_LANE_GUARD <= t <=
                        hold['t'] + hold['hold'] + HOLD_LANE_GUARD]
        occupied_hands = {hand(hold['lane']) for hold in nearby_holds}
        blocked_lanes = {hold['lane'] for hold in nearby_holds}

        def lane_free(lane, gap):
            if lane in blocked_lanes:
                return False
            for other in placed:
                if other['lane'] != lane:
                    continue
                if other['hold']:
                    if other['t'] - HOLD_LANE_GUARD <= t <= other['t'] + other['hold'] + HOLD_LANE_GUARD:
                        return False
                elif abs(other['t'] - t) < gap:
                    return False
            return True

        def candidates(gap):
            return [lane for lane in range(7) if lane_free(lane, gap)]

        available = candidates(TAP_LANE_GAP)
        if not available:
            available = candidates(.001)
        # A held F/J finger leaves the other hand and thumb available. Use
        # that set for surrounding notes, including the hold head and tail.
        free_hand = [lane for lane in available if hand(lane) not in occupied_hands]
        if free_hand:
            available = free_hand
        if not available:
            raise ValueError(f'No playable lane for attack at {t:.4f}s')

        def cost(lane):
            mirror = 6 - preferred
            preference = 0 if lane == preferred else .45 if lane == mirror else 1 + .18 * abs(lane - preferred)
            voice = note['drum']
            shape = {
                'kick': (1.5, 1, .35, 0, .35, 1, 1.5),
                'snare': (.8, 0, .4, 1.2, .4, 0, .8),
                'hat': (0, .3, .85, 1.3, .85, .3, 0),
            }[voice][lane]
            chord = sum(1.4 for other in placed
                        if not other['hold'] and abs(other['t'] - t) < .001
                        and hand(other['lane']) == hand(lane) != 0)
            recent = sum(.3 for other in placed
                         if not other['hold'] and other['lane'] == lane
                         and 0 < t - other['t'] < .22)
            return preference + shape + chord + recent

        note['lane'] = min(available, key=lambda lane: (cost(lane), lane))
        placed.append(note)
    return sorted(placed, key=lambda note: (note['t'], note['lane']))


def frames_for(seconds):
    return max(1, round(seconds * SR / HOP))


def decode(source):
    pcm = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', str(source), '-f', 'f32le', '-ac', '1',
         '-ar', str(SR), 'pipe:1'], capture_output=True, check=True,
    ).stdout
    return np.frombuffer(pcm, dtype='<f4').astype(np.float32)


def drum_features(audio):
    freq, times, spectrum = stft(audio, SR, window='hann', nperseg=FFT,
                                 noverlap=FFT-HOP, boundary='zeros', padded=True)
    magnitude = np.abs(spectrum).astype(np.float32)
    harmonic = median_filter(magnitude, size=(1, 17))
    percussive = median_filter(magnitude, size=(17, 1))
    mask = percussive**2 / (percussive**2 + harmonic**2 + 1e-12)
    drum = magnitude * mask
    rise = np.maximum(0, np.diff(np.log1p(drum * 150), axis=1, prepend=0))
    features = {}
    for name, (lo, hi) in BANDS.items():
        band = (freq >= lo) & (freq < hi)
        features[name] = gaussian_filter1d(np.mean(rise[band], axis=0), 1)
    return times, features


def detect_events(times, features):
    scale = {name: float(np.quantile(x, .99)) for name, x in features.items()}
    activity = uniform_filter1d(
        sum(x / scale[name] for name, x in features.items()), size=frames_for(4))
    low, high = np.quantile(activity, [.15, .85])
    raw = []
    for name, x in features.items():
        peaks, props = find_peaks(x, distance=frames_for(.07),
                                  prominence=scale[name] * .30)
        for frame, prom in zip(peaks, props['prominences']):
            raw.append((float(times[frame]), name, float(prom / scale[name]), frame))
    raw.sort()
    merged = []
    for t, name, strength, frame in raw:
        if merged and t - merged[-1]['t'] <= .04:
            merged[-1]['voices'][name] = strength
            merged[-1]['frames'][name] = frame
        else:
            merged.append({'t': t, 'voices': {name: strength}, 'frames': {name: frame}})
    for event in merged:
        frame = min(event['frames'].values())
        event['activity'] = float(np.clip((activity[frame] - low) / (high - low + 1e-9), 0, 1))
    return merged


def select_events(events, difficulty):
    preset = PRESET[difficulty]
    candidates = []
    for event in events:
        # A louder four-second drum passage admits quieter subdivisions.
        factor = 1.12 - .30 * event['activity']
        active = {name: power for name, power in event['voices'].items()
                  if power >= preset['threshold'][name] * factor}
        if difficulty == 'easy':
            active.pop('hat', None)
        if not active:
            continue
        score = max(power * {'kick': 1.08, 'snare': 1, 'hat': .87}[name]
                    for name, power in active.items())
        score += .08 * sum(active.values()) + .13 * event['activity']
        candidates.append({**event, 'active': active, 'score': score})

    # Keep strong attacks when two very close candidates compete. This avoids
    # discarding an accented drum just because a weak hat occurred first.
    chosen = []
    for event in sorted(candidates, key=lambda e: (-e['score'], e['t'])):
        gap = preset['gap'] * (1 - .18 * event['activity'])
        if any(abs(event['t'] - other['t']) < gap for other in chosen):
            continue
        if sum(abs(event['t'] - other['t']) < .5 for other in chosen) >= preset['nps']:
            continue
        chosen.append(event)
    return sorted(chosen, key=lambda e: e['t'])


def chart_notes(events, difficulty, duration, bpm):
    notes = []
    counters = Counter()
    last_crash = -100.0
    beat = 60 / bpm
    for event in events:
        voices = event['active']
        primary = max(voices, key=lambda name: voices[name] *
                      {'kick': 1.08, 'snare': 1, 'hat': .87}[name])
        t = round(event['t'], 4)

        def put(voice):
            count = counters[voice]
            lane = {'kick': (3, 3, 2, 4), 'snare': (1, 5), 'hat': (0, 6)}[voice][count % (4 if voice == 'kick' else 2)]
            counters[voice] += 1
            notes.append({'t': t, 'lane': lane, 'hold': 0, 'drum': voice})

        put(primary)
        # A combined kick + backbeat becomes a chord at stronger attacks.
        if primary != 'kick' and 'kick' in voices and voices['kick'] >= (.78 if difficulty == 'hard' else .94):
            if difficulty != 'easy':
                put('kick')
        elif primary == 'kick' and 'snare' in voices and voices['snare'] >= (.78 if difficulty == 'hard' else .94):
            if difficulty != 'easy':
                put('snare')

        # Rare crash accents use the two otherwise spare lanes as sustained
        # notes. They start on the detected attack and last about two beats.
        if (event['t'] - last_crash >= PRESET[difficulty]['crash_gap']
                and event['voices'].get('kick', 0) >= .78
                and event['voices'].get('hat', 0) >= .80):
            lane = 2 if counters['crash'] % 2 == 0 else 4
            # Base length tracks the beat, but each crash still varies with
            # how busy that moment actually is (event['activity'], 0-1) —
            # otherwise every crash in a song ends up exactly the same
            # length, which reads as mechanical rather than following the
            # music.
            base = beat * (2.5 if difficulty == 'hard' else 2)
            swing = .65 + .5 * event['activity']
            cap = 1.35 if difficulty == 'hard' else 1.25
            length = min(cap, base * swing, duration - t - .2)
            if length >= .55:
                if difficulty == 'easy':
                    notes[-1].update({'lane': lane, 'hold': round(length, 4), 'drum': 'crash'})
                else:
                    notes.append({'t': t, 'lane': lane, 'hold': round(length, 4), 'drum': 'crash'})
                counters['crash'] += 1
                last_crash = event['t']

    return arrange_around_holds(notes)


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python tools/build-drum-charts.py "songs/곡.mp3" [--write]')
    source = Path(sys.argv[1])
    write = '--write' in sys.argv[2:]
    manifest = json.loads((source.parent / 'songs.json').read_text(encoding='utf8'))
    song = next((item for item in manifest if item['file'] == source.name), {})
    duration = len(audio := decode(source)) / SR
    times, features = drum_features(audio)
    events = detect_events(times, features)
    bpm = song.get('bpm', 120)
    for difficulty in PRESET:
        chosen = select_events(events, difficulty)
        notes = chart_notes(chosen, difficulty, duration, bpm)
        chart = {
            'version': 3, 'lanes': 7, 'difficulty': difficulty,
            'bpm': bpm, 'beatOffset': .0697, 'duration': duration,
            'title': song.get('title', source.stem), 'key': song.get('key'),
            'analysis': 'percussive-hpss-v1', 'noteCount': len(notes), 'notes': notes,
        }
        print(difficulty, 'attacks', len(chosen), 'notes', len(notes),
              'holds', sum(n['hold'] > 0 for n in notes),
              '20s sections', [sum(a <= n['t'] < a+20 for n in notes)
                               for a in [0, 20, 40, 60, 80, 100, 120]])
        if write:
            target = source.with_name(f'{source.stem}.{difficulty}.json')
            target.write_text(json.dumps(chart, ensure_ascii=False, separators=(',', ':')),
                              encoding='utf8')
            print('saved', target)


if __name__ == '__main__':
    main()
