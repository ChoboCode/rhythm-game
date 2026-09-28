"""정해 둔 순간들에 손 모양 화음 노트를 넣는다(그 사이의 기존 노트는 비운다).

강렬한 연타("둥둥둥둥땃")를 양손 3키 화음으로 치게 하려고 만든 도구다. 시각은 스템 분석으로 잰 값을 준다.
  L  = 왼손 3키  S·D·F (7레인 0,1,2)
  R  = 오른손 3키 J·K·L (7레인 4,5,6)
  LR = 양손 6키
EASY는 같은 리듬을 한 손가락씩(L→D, R→K, LR→D+K)으로 친다. 가운데(스페이스) 레인은 쓰지 않는다.

사용: python tools/chord-hits.py "곡 제목" 69.608:L 70.002:R 70.397:L 70.792:R 71.187:LR [--write]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDS = {'L': [0, 1, 2], 'R': [4, 5, 6], 'LR': [0, 1, 2, 4, 5, 6]}
EASY = {'L': [1], 'R': [5], 'LR': [1, 5]}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    title, hits = args[0], [(float(a.split(':')[0]), a.split(':')[1]) for a in args[1:]]
    songs = json.load(open(os.path.join(ROOT, 'songs', 'songs.json'), encoding='utf-8'))
    song = next(s for s in songs if s['title'] == title)
    half = 30 / song['bpm']                                     # 반 박
    t0, t1 = hits[0][0] - half, hits[-1][0] + half
    for level in ('easy', 'normal', 'hard'):
        path = os.path.join(ROOT, 'songs', song['charts'][level])
        chart = json.load(open(path, encoding='utf-8'))
        kept = [n for n in chart['notes'] if not (n['t'] < t1 and n['t'] + (n.get('hold') or 0) > t0)]
        table = EASY if level == 'easy' else HANDS
        new = [{'t': t, 'lane': lane, 'hold': 0, 'drum': 'kick' if hand != 'LR' else 'snare', 'source': 'chord-hits-v1'}
               for t, hand in hits for lane in table[hand]]
        print(f'{level}: {t0:.2f}~{t1:.2f}s 기존 {len(chart["notes"]) - len(kept)}개 → 화음 {len(new)}개')
        chart['notes'] = sorted(kept + new, key=lambda n: (n['t'], n['lane']))
        chart['noteCount'] = len(chart['notes'])
        if '--write' in sys.argv:
            with open(path, 'w', encoding='utf-8', newline='') as out:
                json.dump(chart, out, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main()
