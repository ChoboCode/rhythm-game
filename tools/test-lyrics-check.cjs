const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const core = require('./lyrics-check-core.js');

const root = path.resolve(__dirname, '..');
const songs = JSON.parse(fs.readFileSync(path.join(root, 'songs', 'songs.json'), 'utf8'));
let mapped = 0;
for (const song of songs.filter((s) => s.lyrics)) {
  const data = JSON.parse(fs.readFileSync(path.join(root, 'songs', song.lyrics), 'utf8'));
  for (const line of data.lines) {
    assert.equal(core.spans(line, line.words).length, line.words.length, song.title);
    if (line.segments) assert.equal(core.spans(line, line.segments).length, line.segments.length, song.title);
    mapped++;
  }
}

const lines = [
  { t: 1, end: 2, text: '우리 마을', words: [
    { t: 1, end: 1.5, text: '우리' }, { t: 1.5, end: 2, text: '마을' }] },
  { t: 3, end: 4, text: '다음 줄', words: [
    { t: 3, end: 3.5, text: '다음' }, { t: 3.5, end: 4, text: '줄' }] },
];
assert.equal(core.stateAt(lines, .5).activeIndex, -1);
assert.equal(core.stateAt(lines, 1.25).activeIndex, 0);
assert.equal(core.stateAt(lines, 1.25).displayIndex, 0);
assert.equal(core.stateAt(lines, 2.5).activeIndex, 0, 'completed line stays gold until next line when gap <=1.2s');
assert.equal(core.stateAt(lines, 3).activeIndex, 1);
assert.equal(core.splitKorean(lines[0]), true);
assert.deepEqual(lines[0].segments.map((s) => s.text), ['우', '리', '마', '을']);
assert.equal(lines[0].segments[0].t, 1);
assert.equal(lines[0].segments[3].end, 2);
core.setBoundary(lines, 0, 1, 'start', 1.31);
assert.equal(lines[0].segments[0].end, 1.31);
assert.equal(lines[0].segments[1].t, 1.31);
assert.equal(lines[0].words[0].t, 1);
core.setBoundary(lines, 0, 2, 'start', 1.62);
assert.equal(lines[0].words[0].end, 1.62, 'word end follows last syllable');
assert.equal(lines[0].words[1].t, 1.62, 'next word follows first syllable');
const before = JSON.stringify(lines[0]);
assert.throws(() => core.setBoundary(lines, 0, 2, 'start', 99), /겹칩니다/);
assert.equal(JSON.stringify(lines[0]), before, 'invalid edit does not change data');
core.shiftLine(lines, 0, .9);
assert.equal(lines[0].t, .9);
assert.equal(lines[0].words[0].t, .9);
assert.equal(lines[0].segments[0].t, .9);
assert.equal(core.splitKorean(lines[0]), false, 'existing syllables are kept');

const source = [
  { t: 1, end: 2, text: '우리 마을', words: [
    { t: 1, end: 1.5, text: '우리' }, { t: 1.5, end: 2, text: '마을' }] },
  { t: 3, end: 4, text: '다음 줄', words: [
    { t: 3, end: 3.5, text: '다음' }, { t: 3.5, end: 4, text: '줄' }] },
];
const untouched = JSON.stringify(source);
const syllables = core.tapTemplate(source[0], 'syllables');
assert.deepEqual(syllables.segments.map((part) => part.text), ['우', '리', '마', '을']);
assert.equal(JSON.stringify(source), untouched, 'syllable template does not alter saved lyrics');
const proposal = core.retimeByTaps(source, 0, 'syllables', [1.10, 1.25, 1.55, 1.70, 1.94]);
assert.deepEqual(proposal.segments.map((part) => part.t), [1.10, 1.25, 1.55, 1.70]);
assert.equal(proposal.words[0].end, 1.55);
assert.equal(proposal.words[1].t, 1.55);
assert.equal(proposal.end, 1.94);
assert.equal(JSON.stringify(source), untouched, 'preview does not commit before Apply');
const wordProposal = core.retimeByTaps(source, 0, 'words', [1.15, 1.64, 2.10]);
assert.deepEqual(wordProposal.words.map((part) => part.t), [1.15, 1.64]);
assert.equal(wordProposal.end, 2.10);
const withSegments = [proposal, source[1]];
const expanded = core.tapTemplate(proposal, 'syllables');
assert.deepEqual(expanded.segments.map((part) => part.text), ['우', '리', '마', '을']);
const partlySplit = { t: 1, end: 2, text: '나는 우리', words: [
  { t: 1, end: 1.5, text: '나는' }, { t: 1.5, end: 2, text: '우리' } ], segments: [
  { t: 1, end: 1.5, text: '나는' }, { t: 1.5, end: 1.75, text: '우' },
  { t: 1.75, end: 2, text: '리' } ] };
assert.deepEqual(core.tapTemplate(partlySplit, 'syllables').segments.map((part) => part.text),
  ['나', '는', '우', '리'], 'partly segmented lines still expose every Korean syllable');
const grouped = core.retimeByTaps(withSegments, 0, 'words', [1.20, 1.70, 2.20]);
assert.equal(grouped.segments.length, proposal.segments.length, 'word tapping preserves existing syllables');
assert.equal(grouped.segments[0].t, 1.20);
assert.equal(grouped.segments[2].t, 1.70);
assert.equal(grouped.words[1].t, 1.70);
assert.equal(proposal.t, 1.10, 're-timing a draft also leaves its input untouched');
assert.throws(() => core.retimeByTaps(source, 0, 'words', [1.1, 1.6]), /마지막 끝/);
assert.throws(() => core.retimeByTaps(source, 0, 'words', [1.1, 1.1, 2]), /순서대로/);
assert.throws(() => core.retimeByTaps(source, 0, 'words', [3.1, 3.4, 4]), /다음 줄/);
assert.equal(JSON.stringify(source), untouched, 'invalid taps are atomic');

const samples = new Float32Array([-.8, -.1, .2, .6, -.4, .1, .3, .7]);
const envelope = core.waveEnvelope({ sampleRate: 8, length: 8, numberOfChannels: 1,
  getChannelData: () => samples }, 2);
assert.equal(envelope.binSeconds, .5);
assert.deepEqual(Array.from(envelope.low).map((n) => +n.toFixed(2)), [-.8, -.4]);
assert.deepEqual(Array.from(envelope.high).map((n) => +n.toFixed(2)), [.6, .7]);
const window = core.waveWindow({ t: 10, end: 14 }, { t: 9.5, end: 14.5 }, 30, 2, .5);
assert(window.start < 10 && window.end > 14);
assert.equal(core.waveTimeAt(window, 0, 800), window.start);
assert.equal(core.waveTimeAt(window, 800, 800), window.end);
assert(Math.abs(core.waveTimeAt(window, core.waveXAt(window, 11.23, 800), 800) - 11.23) < 1e-9);
assert.equal(core.waveTimeAt(window, -50, 800), window.start, 'wave click stays inside window');

const html = fs.readFileSync(path.join(root, 'lyrics-check.html'), 'utf8');
const game = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
assert.match(html, /tools\/lyrics-check-core\.js/);
assert.match(html, /tools\/lyrics-check-app\.js/);
assert.match(html, /id="tapGranularity"/);
assert.match(html, /id="applyTaps"/);
assert.match(html, /id="compareBefore"/);
assert.match(html, /id="compareAfter"/);
assert.match(html, /id="waveCanvas"/);
assert.match(game, /btnLyricsCheck/);
console.log(`PASS: lyric review page maps ${mapped} saved lines, previews tap-based word/syllable timing without mutation, preserves syllables and rejects invalid taps`);
