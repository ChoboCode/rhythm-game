/* 곡 찾기: 정렬(기본·제목·레벨 높은/낮은 순·길이)과 곡 목록의 레벨이 채보와 맞는지 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const a = html.indexOf('  const DIFFS = [');
const b = html.indexOf('  function renderSongFinder()', a);
assert(a > 0 && b > a, 'sort code found');
const sortSongsForFinder = new Function(html.slice(a, b) + 'return sortSongsForFinder;')();

const s = (title, e, n, h, duration) => ({ title, duration, levels: e ? { easy: e, normal: n, hard: h } : null });
const songs = [s('다', 3, 8, 13, 200), s('가', 4, 8, 15, 180), s('나', 3, 7, 11, 240), s('없음', 0, 0, 0, 100), s('라', 3, 8, 13, 150)];
const names = mode => sortSongsForFinder(songs, mode).map(x => x.title).join('');
assert.equal(names('default'), '다가나없음라', 'default keeps the library order');
assert.equal(names('title'), '가나다라없음', 'title sorts in Korean order');
assert.equal(names('hard-desc'), '가다라나없음', 'HARD high → low; ties keep library order; unknown last');
assert.equal(names('hard-asc'), '나다라가없음', 'HARD low → high; unknown still last');
assert.equal(names('normal-desc'), '다가라나없음', 'NORMAL high → low');
assert.equal(names('easy-asc'), '다나라가없음', 'EASY low → high');
assert.equal(names('length'), '없음라가다나', 'shortest first');
assert.equal(songs.map(x => x.title).join(''), '다가나없음라', 'the library list itself is not reordered');

/* 게임 연결: 정렬 선택이 설정에 남고, 목록에 E·N·H 레벨이 보이고, 난이도 버튼은 곡 목록의 레벨을 바로 쓴다 */
assert(/<select id="songFinderSort">/.test(html) && /<label class="songFinderSortLabel" for="songFinderSort">정렬<\/label>/.test(html), 'labelled sort select');
assert(/prefs\.finderSort = e\.target\.value;\s*savePrefs\(\);/.test(html), 'the chosen sort is remembered');
assert(/chip\.textContent = diff\[0\]\.toUpperCase\(\) \+ \(lv \? lv : '–'\);/.test(html), 'E/N/H level chips in each row');
assert(/levels: s\.levels && typeof s\.levels === 'object' \? s\.levels : null/.test(html), 'the manifest passes levels');
assert(/if \(song\.levels && song\.levels\[diff\]\) \{\s*showDifficultyLevel\(button, diff, song\.levels\[diff\], false\);/.test(html),
  'difficulty buttons use the listed level without downloading the chart');

/* 곡 목록의 레벨 = 채보로 계산한 레벨(게임과 같은 식) */
const r0 = html.indexOf('  function ratingFromChart(chart) {');
const r1 = html.indexOf('\n  }', r0) + 4;
const ratingFromChart = new Function(html.slice(r0, r1) + 'return ratingFromChart;')();
const library = JSON.parse(fs.readFileSync(path.join(root, 'songs', 'songs.json'), 'utf8'));
for (const song of library) {
  for (const diff of ['easy', 'normal', 'hard']) {
    const chart = JSON.parse(fs.readFileSync(path.join(root, 'songs', song.charts[diff]), 'utf8'));
    assert.equal(song.levels && song.levels[diff], ratingFromChart(chart),
      song.title + ' ' + diff + ': songs.json levels is out of date — run python tools/update-levels.py --write');
  }
}
const hard = new Set(library.map(x => x.levels.hard));
for (const lv of [12, 13, 14, 15]) assert(hard.has(lv), 'some song has HARD level ' + lv);
console.log('PASS: song finder sort (default/title/level/length, ties stable, unknown last), level chips, levels match charts');
