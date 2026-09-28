/* songs 폴더에 넣은 음원이 선택 화면과 실제 채보에 모두 연결됐는지 확인한다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const dir = path.join(__dirname, '../songs');
const songs = JSON.parse(fs.readFileSync(path.join(dir, 'songs.json'), 'utf8'));
/* This source is used solely to render the short result-screen outro. */
const audio = fs.readdirSync(dir).filter(name =>
  /\.(mp3|wav|ogg|m4a|flac)$/i.test(name) && name !== 'Sweet_Victory_Rush.mp3').sort();
const registered = songs.map(song => song.file).sort();
assert.deepEqual(registered, audio, '모든 음원은 songs.json에 정확히 한 번 등록돼야 한다');
assert.equal(new Set(songs.map(song => song.title)).size, songs.length, '곡 제목은 중복되지 않아야 한다');

for (const song of songs) {
  if (song.lyrics) {
    const lyricsPath = path.join(dir, song.lyrics);
    assert.ok(fs.existsSync(lyricsPath), song.file + ': lyric file is missing');
    const lyrics = JSON.parse(fs.readFileSync(lyricsPath, 'utf8'));
    assert.equal(lyrics.title, song.title, song.lyrics + ': title does not match');
    assert.ok(Array.isArray(lyrics.lines) && lyrics.lines.length, song.lyrics + ': no lyric lines');
    let previousStart = -1;
    for (const line of lyrics.lines) {
      assert.ok(typeof line.text === 'string' && line.text.trim(), song.lyrics + ': empty lyric line');
      assert.ok(Number.isFinite(line.t) && Number.isFinite(line.end) &&
        line.t >= previousStart && line.end > line.t && line.end <= song.duration + .2,
        song.lyrics + ': invalid lyric timing');
      if (line.words) {
        assert.ok(Array.isArray(line.words) && line.words.length &&
          line.words.map(word => word.text).join(' ') === line.text,
          song.lyrics + ': words do not match the line');
        for (const word of line.words) {
          assert.ok(Number.isFinite(word.t) && Number.isFinite(word.end) &&
            word.t >= line.t && word.end > word.t && word.end <= line.end,
            song.lyrics + ': invalid word timing');
        }
      }
      previousStart = line.t;
    }
  }
  assert.ok(song.title && song.duration > 0, song.file + ': 제목과 재생 시간이 필요하다');
  const time = song.file.match(/_(\d+)_(\d{2})\.(mp3|wav|ogg|m4a|flac)$/i);
  assert.ok(time && Number(time[2]) < 60 &&
    Number(time[1]) * 60 + Number(time[2]) === Math.floor(song.duration),
    song.file + ': 파일명 끝의 분_초가 곡 길이와 다르다');
  assert.ok(!song.description || !/\?{2,}/.test(song.description), song.file + ': 설명 글자가 손상됐다');
  assert.ok(Array.isArray(song.soundBass) && song.soundBass.length === Math.ceil(song.duration / 2) &&
    song.soundBass.every(pc => Number.isInteger(pc) && pc >= 0 && pc < 12),
    song.file + ': 곡별 타격음 저음 정보가 누락되거나 잘못됐다');
  assert.ok(Array.isArray(song.soundFlow) && song.soundFlow.length === Math.ceil(song.duration / 2) &&
    song.soundFlow.every(row => Array.isArray(row) && row.length === 3 &&
      row.every(level => Number.isInteger(level) && level >= 0 && level <= 3)),
    song.file + ': 킥·스네어·심벌 구간 정보가 누락되거나 잘못됐다');
  if (song.cover) assert.ok(fs.existsSync(path.join(dir, song.cover)), song.file + ': 표지가 없다');
  assert.ok(song.charts, song.file + ': 등록 곡에 저장 채보 목록이 없다');
  const counts = [];
  for (const level of ['easy', 'normal', 'hard']) {
    const name = song.charts[level];
    assert.ok(name && fs.existsSync(path.join(dir, name)), song.file + ': ' + level + ' 채보가 없다');
    const chart = JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'));
    assert.equal(chart.difficulty, level, name + ': 난이도가 다르다');
    assert.equal(chart.title, song.title, name + ': 곡 제목이 목록과 다르다');
    assert.equal(chart.lanes, 7, name + ': 7레인 채보여야 한다');
    assert.ok(chart.notes.length, name + ': 노트가 없다');
    assert.ok(Math.abs(chart.duration - song.duration) < 1, name + ': 곡 길이가 다르다');
    if (level === 'normal') assert.equal(song.bpm, chart.bpm, name + ': 목록 BPM이 다르다');
    const laneEnd = Array(7).fill(-1);
    let lastTime = -1;
    for (const note of chart.notes) {
      assert.ok(Number.isFinite(note.t) && note.t >= lastTime && note.t <= song.duration + .2,
        name + ': 노트 시간이 잘못됐다');
      assert.ok(Number.isInteger(note.lane) && note.lane >= 0 && note.lane < 7,
        name + ': 레인 범위가 잘못됐다');
      assert.ok(note.hold >= 0 && note.t >= laneEnd[note.lane] + .06,
        name + ': 같은 레인에 노트가 겹친다');
      laneEnd[note.lane] = note.t + note.hold;
      lastTime = note.t;
    }
    counts.push(chart.notes.length);
  }
  assert.ok(counts[0] < counts[1] && counts[1] < counts[2], song.file + ': 난이도별 밀도가 역전됐다');
}

console.log('PASS: ' + songs.length + '곡 등록 · 지정된 표지 · 난이도별 채보 · 노트 범위 · 가사 싱크 · 파일명 시간');
