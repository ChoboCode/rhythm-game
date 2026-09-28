"""곡마다 EASY/NORMAL/HARD 레벨(1~15)을 채보에서 계산해 songs.json에 "levels" 한 줄로 적는다.

곡 찾기의 난이도 숫자·정렬과 난이도 버튼이 채보 파일 99개를 매번 받지 않고 바로 쓰게 하려는 것이다.
식은 게임(index.html ratingFromChart)과 같다: 초당 노트 × 2.1 + 긴 노트 비율 × 3, 1~15.
attack-chart.py --write 뒤에 자동으로 돈다. test-song-library.cjs가 채보와 어긋나지 않았는지 확인한다.

사용: python tools/update-levels.py [--write]
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, 'songs', 'songs.json')


def rating(chart):
    notes = chart['notes']
    if not notes:
        return None
    dur = notes[-1]['t'] or 1
    hold = sum(1 for n in notes if (n.get('hold') or 0) > 0) / len(notes)
    return max(1, min(15, round(len(notes) / dur * 2.1 + hold * 3)))


def main():
    spec = importlib.util.spec_from_file_location('ms', os.path.join(ROOT, 'tools', 'make-stems.py'))
    ms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ms)
    songs = json.load(open(MANIFEST, encoding='utf-8'))
    text = open(MANIFEST, encoding='utf-8').read()
    for song in songs:
        levels = {}
        for level in ('easy', 'normal', 'hard'):
            f = (song.get('charts') or {}).get(level)
            if f and os.path.exists(os.path.join(ROOT, 'songs', f)):
                levels[level] = rating(json.load(open(os.path.join(ROOT, 'songs', f), encoding='utf-8')))
        text = ms.write_field(text, song['title'], 'levels', levels)
        print(f"{song['title']}: {levels.get('easy')} / {levels.get('normal')} / {levels.get('hard')}")
    json.loads(text)
    if '--write' in sys.argv:
        with open(MANIFEST, 'w', encoding='utf-8', newline='') as out:
            out.write(text)
        print('songs.json 갱신')


if __name__ == '__main__':
    main()
