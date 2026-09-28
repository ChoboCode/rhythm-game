"""O2Jam식 키음용 음원 세 개를 만든다: 드럼(모노) + 멜로디(보컬+기타 악기, 스테레오) + 반주(원곡 − 드럼 − 멜로디).

게임은 드럼 노트를 치면 그 순간의 실제 드럼을, 멜로디 노트(드럼 없는 곳 — 보컬 30%·기타/피아노/신스 34%)를 치면
그 순간의 노래와 선율을 들려준다(발라드는 노래방처럼 — 사용자 요청). 놓치면 빠진다.
멜로디는 기타·신스가 좌우로 넓게 퍼져 있어 모노로 빼면 반주에 반대 위상 잔향이 남으므로 스테레오로 둔다.

게임은 드럼을 노트를 칠 때만 그 순간의 실제 드럼 소리로 들려 주고(놓치면 빠진다), 나머지는 반주로 흘린다.
반주를 "보컬+베이스+기타 스템의 합"으로 만들면 분리가 놓친 소리가 빠져 원곡과 19dB밖에 안 맞았다.
그래서 반주 = 원곡 − 드럼(두 채널 모두에서 모노 드럼을 뺌)으로 만든다 → 반주 + 드럼 = 원곡(남는 차이는 MP3 압축뿐,
Bass Control 기준 23.9dB). 드럼을 모노로 두는 것은 약한 기기의 메모리(원곡의 약 1.5배) 때문이다.

  songs/stems/<원래 파일 이름>.backing.mp3  스테레오 192kbps (원곡 − 드럼 − 멜로디: 베이스·잔향)
  songs/stems/<원래 파일 이름>.drums.mp3    모노 128kbps
  songs/stems/<원래 파일 이름>.melody.mp3   스테레오 192kbps (보컬 + 기타 악기)
반주 + 드럼 + 멜로디 = 원곡(MP3 압축 차이만). songs.json 각 곡에 "stems": {"backing", "drums", "melody"} 한 줄(--write).

사용: python tools/make-stems.py                    # 전체
      python tools/make-stems.py "Bass Control" ...  # 일부
      ... --write                                    # songs.json 갱신
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, 'songs', 'songs.json')
OUT = os.path.join(ROOT, 'songs', 'stems')
KEEP = os.path.join(tempfile.gettempdir(), 'rhythm-game-stems', 'keep')
FFMPEG = 'ffmpeg'
for cand in (r'C:\ffmpeg\bin\ffmpeg.exe',):
    if os.path.exists(cand):
        FFMPEG = cand


def separate(song_file):
    name = os.path.splitext(song_file)[0]
    folder = os.path.join(KEEP, 'htdemucs', name)
    if not all(os.path.exists(os.path.join(folder, s + '.wav')) for s in ('drums', 'bass', 'other', 'vocals')):
        subprocess.run([sys.executable, '-m', 'demucs', '-n', 'htdemucs', '-o', KEEP,
                        os.path.join(ROOT, 'songs', song_file)], check=True)
    return folder


def encode(folder, song_file):
    import librosa
    import numpy as np
    import soundfile as sf
    name = os.path.splitext(song_file)[0]
    os.makedirs(OUT, exist_ok=True)
    backing = os.path.join(OUT, name + '.backing.mp3')
    drums = os.path.join(OUT, name + '.drums.mp3')
    melody = os.path.join(OUT, name + '.melody.mp3')
    orig, sr = librosa.load(os.path.join(ROOT, 'songs', song_file), sr=44100, mono=False)
    orig = np.atleast_2d(orig)
    n = orig.shape[1]

    def stem(part):
        x, _ = librosa.load(os.path.join(folder, part + '.wav'), sr=44100, mono=False)
        x = np.atleast_2d(x)
        x = x[:, :n] if x.shape[1] >= n else np.pad(x, ((0, 0), (0, n - x.shape[1])))
        return x if x.shape[0] == orig.shape[0] else np.repeat(x[:1], orig.shape[0], axis=0)
    mono = stem('drums').mean(axis=0)
    mel = stem('vocals') + stem('other')
    back = orig - mono[None, :] - mel
    tmp = tempfile.mkdtemp()
    for arr, wav, mp3, rate in ((back, 'b.wav', backing, '192k'), (mono[None, :], 'd.wav', drums, '128k'),
                                (mel, 'm.wav', melody, '192k')):
        sf.write(os.path.join(tmp, wav), arr.T, sr, subtype='FLOAT')
        subprocess.run([FFMPEG, '-y', '-v', 'error', '-i', os.path.join(tmp, wav),
                        '-c:a', 'libmp3lame', '-b:a', rate, mp3], check=True)
    return os.path.basename(backing), os.path.basename(drums), os.path.basename(melody)


def write_field(text, title, key, value):
    start = text.index('"title": ' + json.dumps(title, ensure_ascii=False))
    end = text.find('"title": ', start + 1)
    end = len(text) if end < 0 else end
    block = text[start:end]
    field = '"' + key + '": '
    line = field + json.dumps(value, ensure_ascii=False) + ','
    if field in block:
        head, rest = block.split(field, 1)
        block = head + line + '\n' + rest.split('\n', 1)[1]
    else:
        bpm = block.index('"bpm": ')
        eol = block.index('\n', bpm)
        indent = block[block.rindex('\n', 0, bpm) + 1:bpm]
        block = block[:eol + 1] + indent + line + '\n' + block[eol + 1:]
    return text[:start] + block + text[end:]


def main():
    songs = json.load(open(MANIFEST, encoding='utf-8'))
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    if only:
        songs = [s for s in songs if s['title'] in only]
    text = open(MANIFEST, encoding='utf-8').read()
    for song in songs:
        name = os.path.splitext(song['file'])[0]
        backing, drums, melody = encode(separate(song['file']), song['file'])
        size = sum(os.path.getsize(os.path.join(OUT, f)) for f in (backing, drums, melody)) / 1e6
        print(f"{song['title']}: {backing} + {drums} + {melody} ({size:.1f}MB)", flush=True)
        text = write_field(text, song['title'], 'stems', {'backing': 'stems/' + backing, 'drums': 'stems/' + drums,
                                                          'melody': 'stems/' + melody})
    json.loads(text)
    if '--write' in sys.argv:
        with open(MANIFEST, 'w', encoding='utf-8', newline='') as out:
            out.write(text)
        print('songs.json 갱신')


if __name__ == '__main__':
    main()
