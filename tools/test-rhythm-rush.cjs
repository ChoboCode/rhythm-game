const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const start = html.indexOf('function buildRhythmRushes(');
const end = html.indexOf('const meterLevel =', start);
assert(start >= 0 && end > start, 'rhythm motion functions found in the game');
const source = html.slice(start, end);
function motion(reduceMotion) {
  return new Function('reduceMotion', 'P', source +
    'return { buildRhythmRushes, rhythmScrollTimeAt, addDropAccents, impactAt, restAt, ensurePlayable };')(reduceMotion, { rushes: [] });
}
const strong = motion(false);

function checkMotion(rushes, label) {
  const scroll = t => strong.rhythmScrollTimeAt(t, rushes);
  const velocity = t => (scroll(t + .0005) - scroll(t - .0005)) / .001;
  for (const r of rushes) {
    assert(Math.abs(velocity(r.start - .01) - 1) < .01, label + ': ordinary speed before');
    assert(Math.abs(velocity(r.end + .01) - 1) < .01, label + ': ordinary speed afterwards');
    assert(Math.abs((r.start - scroll(r.start)) - r.offset) < 1e-6, label + ': carries the earlier lag in');
    assert(Math.abs((r.end - scroll(r.end)) - (r.offset + r.net)) < 1e-6, label + ': leaves with its own lag added');
    if (r.kind === 'drop') {
      assert(velocity(r.land) > 2.2, label + ': notes explode onto the landing hit');
      assert(velocity(r.land - .2) < 1.3, label + ': ...and not before it (steep burst)');
      if (!r.noSlow) assert(velocity(r.start + .15) < .75, label + ': sinks right away (steep drop)');
    } else {
      assert(r.net > 0, label + ': a rest leaves the notes a little behind instead of rushing');
    }
    let prev = velocity(r.start);
    const pulsed = r.kind === 'drop' && r.hits.length > 1;
    for (let t = r.start; t <= r.end; t += .002) {
      const v = velocity(t);
      assert(v > .25, label + ': notes never stall at ' + t.toFixed(3));
      assert(Math.abs(v - prev) < (pulsed ? .16 : .06), label + ': speed changes steeply but never jumps at ' + t.toFixed(3));
      assert(Math.abs(scroll(t + .002) - scroll(t) - v * .002) < .0003, label + ': notes move continuously at ' + t.toFixed(3));
      if (r.kind === 'rest') assert(v <= 1 + 1e-9, label + ': a rest never speeds up to catch up');
      prev = v;
    }
  }
}

const note = (t, drum) => ({ t, drum: drum || null, hold: 0 });
const notes = [];
for (let t = 5; t < 90; t += .5) notes.push(note(+t.toFixed(3), 'hat'));
notes.push(note(29.9, 'crash'), note(60, 'crash'), note(60, 'kick'));
notes.sort((a, b) => a.t - b.t);
const before = notes.map(n => n.t);

/* 몰아치기: 음원에서 잰 "빡!" 순간(drops)에만, 가장 가까운 실제 노트에 착지 */
const song = { duration: 100, drops: [29.95, 60.04] };
const rushes = strong.buildRhythmRushes(notes, song, 'hard', 120);
assert.deepEqual(rushes.map(r => r.kind + '@' + r.land), ['drop@29.95', 'drop@60.04'], 'the landing is the measured attack itself');
assert.deepEqual(notes.map(n => n.t), before, 'chart times stay untouched');
{
  /* 앞 노트를 다 친 뒤에야 느려진다(노트가 0.5초마다 있으면 필요한 만큼만 비운다) — 사용자 확인 */
  const r0 = rushes[0], approach = .75 + .25 + .15;
  const lastBefore = Math.max(...notes.filter(n => n.t < r0.land - .225).map(n => n.t));
  assert(r0.start >= Math.min(lastBefore + .05, r0.land - approach) - 1e-9, 'slowing waits until the notes before it are hit (or clears just enough room)');
  assert(r0.land - r0.start >= approach - 1e-9 && r0.land - r0.start <= 2 + 1e-9, 'the sink is still long enough to feel, never longer than a bar');
  const kept = strong.addDropAccents(notes, rushes, 120, 6);
  for (const r of rushes) assert(!kept.some(n => !n.accent && n.t + n.hold > r.start && n.t < r.land), 'no ordinary note is on its way while the notes slow down');
}
checkMotion(rushes, 'drop');
assert.deepEqual(strong.buildRhythmRushes(notes, { duration: 100, drops: [70.62] }, 'hard', 120).map(r => r.land), [70.62],
  'a note within 0.15s is enough to have something to hit');
{
  const empty = strong.buildRhythmRushes(notes, { duration: 100, drops: [70.25] }, 'hard', 120);
  assert.equal(empty.length, 1, 'a measured moment always plays');
  assert(strong.addDropAccents(notes, empty, 120, 6).some(n => n.accent && n.t === 70.25),
    '...and its S+K hit gives the player something to hit exactly there');
}

/* 브레이크 → 몰아치기: 브레이크 시작부터 살살 쭉 느리게, 착지에서 한꺼번에 */
const breakSong = { duration: 100, drops: [{ t: 60.04, from: 54, hits: [60.04, 60.4, 60.76] }] };
const inBreak = notes.filter(n => !(n.t >= 54 && n.t < 60.04));      /* 브레이크 동안은 노트가 없다 */
const bd = strong.buildRhythmRushes(inBreak, breakSong, 'hard', 120);
assert.equal(bd.length, 1);
assert.equal(bd[0].start, 58.04, 'inside a long break the slow-down starts only one bar before the landing');
assert(bd[0].fromBreak);
const shortBreak = strong.buildRhythmRushes(inBreak, { duration: 100, drops: [{ t: 60.04, from: 58.4, hits: [60.04] }] }, 'hard', 120);
assert.equal(shortBreak[0].start, 58.4, 'a break shorter than a bar slows from its start');
checkMotion(bd, 'break-drop');
{
  const sc = t => strong.rhythmScrollTimeAt(t, bd);
  const vel = t => (sc(t + .0005) - sc(t - .0005)) / .001;
  assert(Math.abs(vel(57) - 1) < .01, 'still normal speed earlier in the break');
  for (let x = 58.4; x < 59.2; x += .1) assert(Math.abs(vel(x) - .45) < .01, 'held slow just before the landing');
  assert(vel(60.04) > 2.2, 'bursts at the landing');
  for (const h of [60.4, 60.76]) assert(vel(h) > 2.2, 'bursts again on every hit ' + h);
  for (const m of [60.2, 60.56]) assert(vel(m) < .8, 'sinks between hits ' + m);
  assert(Math.abs(vel(61.6) - 1) < .02, 'back to normal after the last hit');
}

/* 타격마다 S·K — 음악이 3번 치면 3번 */
const acc = strong.addDropAccents(notes, bd, 120, 6).filter(n => n.accent);
assert.deepEqual(acc.map(n => n.t + '@' + n.lane),
  ['60.04@0', '60.04@4', '60.4@0', '60.4@4', '60.76@0', '60.76@4'], 'one S+K chord per measured hit');
const withAcc = strong.addDropAccents(notes, bd, 120, 6);
for (const a of acc) assert(!withAcc.some(n => !n.accent && Math.abs(n.t - a.t) < .225), 'hits stand alone');
assert(!withAcc.some(n => !n.accent && n.t > 60.04 - .225 && n.t < 60.76 + .225), 'nothing but the S+K hits from the first to the last hit');
assert(withAcc.some(n => !n.accent && n.t > 61.2), 'the chart resumes after the hits');
assert.deepEqual(strong.addDropAccents(notes, rushes, 120, 7).filter(n => n.accent).map(n => n.lane).slice(0, 2), [0, 5],
  '7-key: S and K lanes');
assert.equal(strong.addDropAccents(notes, rushes, 120, 6).filter(n => n.accent).length, 4, 'a single-hit drop gets one chord');
assert.deepEqual(notes.map(n => n.t), before, 'the chart itself is not modified');
assert(withAcc.every((n, i) => !i || withAcc[i - 1].t <= n.t), 'notes stay in time order');
const heldOver = [{ t: 59, lane: 2, hold: 2, drum: null }].concat(notes.filter(n => n.t > 70));
assert(!strong.addDropAccents(heldOver, bd, 120, 6).some(n => n.hold > 0 && n.t === 59), 'a long note across the hits is cleared');
{
  /* 느려지기 전에 시작한 긴 노트는 꼬리만 느려지기 앞에서 끝낸다 */
  const early = [{ t: 56, lane: 2, hold: 3, drum: null }];
  const trimmed = strong.addDropAccents(early, bd, 120, 6).find(n => n.t === 56);
  assert(trimmed && Math.abs(trimmed.t + trimmed.hold - (bd[0].start - .05)) < 1e-3, 'a long note that began before the slow-down just ends before it');
}

/* 타격 순간 화면 "쿵" */
assert.equal(strong.impactAt(60.4, bd), 1, 'full punch on a hit');
assert(strong.impactAt(60.5, bd) > 0 && strong.impactAt(60.5, bd) < 1, 'fades right after');
assert.equal(strong.impactAt(60.3, bd), 0, 'nothing between hits');

/* 쉬어가기: 잰 순간(rests)에서 느려졌다가 따라잡지 않고 돌아온다 */
const restSong = { duration: 100, rests: [{ from: 29.95, to: 35 }, { from: 60.04, to: 64 }] };
const rests = strong.buildRhythmRushes(notes, restSong, 'hard', 120);
{
  /* 여려지는 첫 노트를 친 바로 뒤에 느려지고, 느려지는 동안엔 새 노트가 오지 않는다 */
  const kept = strong.addDropAccents(notes, rests, 120, 6);
  for (const r of rests) {
    assert(notes.some(n => Math.abs(n.t + .03 - r.start) < 1e-9), 'a rest starts slowing right after a note is hit');
    assert(!kept.some(n => n.t > r.quiet[0] && n.t < r.quiet[1]), 'no note arrives while it slows down');
    assert(Math.abs(r.quiet[1] - r.quiet[0] - r.phases[0].len) < 1e-9, 'the quiet stretch is exactly the slow-down');
  }
}
assert.deepEqual(rests.map(r => r.kind + '@' + r.land), ['rest@29.95', 'rest@60.04'], 'breathers start on the measured moment');
assert(Math.abs(rests[1].offset - rests[0].net) < 1e-9, 'the second breather starts from the first one’s lag');
checkMotion(rests, 'rest');
{
  const sc = t => strong.rhythmScrollTimeAt(t, rests);
  const vel = t => (sc(t + .0005) - sc(t - .0005)) / .001;
  assert(Math.abs(vel(32) - .3) < .01, 'deeply slow through the rest');
  assert.equal(strong.restAt(32, rests), 1, 'the board fully settles while resting');
  assert.equal(strong.restAt(28, rests), 0, 'no dimming outside a rest');
  assert(strong.restAt(34.9, rests) < .2 && strong.restAt(35.1, rests) === 0, 'the board brightens as the rhythm returns');
  assert(Math.abs(vel(35) - 1) < .02, 'exactly back to normal speed when the rhythm returns');
}
const restScroll = t => strong.rhythmScrollTimeAt(t, rests);
for (let t = 0; t < 99; t += .01) assert(restScroll(t + .01) > restScroll(t), 'scroll always moves forward');

/* 겹치면 몰아치기가 우선 */
const both = strong.buildRhythmRushes(notes, { duration: 100, drops: [60.04], rests: [{ from: 57, to: 60 }] }, 'hard', 120);
assert.deepEqual(both.map(r => r.kind), ['drop'], 'an overlapping breather yields to the drop');
assert.equal(strong.addDropAccents(notes, rests, 120, 6).filter(n => n.accent).length, 0, 'breathers get no accents');
const apart = strong.buildRhythmRushes(notes, { duration: 100, drops: [60.04], rests: [{ from: 40, to: 44 }] }, 'hard', 120);
assert.deepEqual(apart.map(r => r.kind), ['rest', 'drop'], 'separate moments both play');
checkMotion(apart, 'rest+drop');

/* 분석 결과가 없으면 아무것도 추측하지 않는다 */
assert.equal(strong.buildRhythmRushes(notes, { duration: 100, soundFlow: Array(50).fill([3, 3, 3]) }, 'hard', 120).length, 0,
  'no measured moments → steady');
assert.equal(strong.buildRhythmRushes(notes, song, 'easy', 120).length, 0, 'easy stays steady');
assert.equal(motion(true).buildRhythmRushes(notes, song, 'hard', 120).length, 0, 'reduced motion stays steady');

/* 칠 수 있게 다듬기: 롱노트 끝 → 같은 레인 다음 노트 0.22초 이상, 불가능한 연타 제거 */
{
  const n = (t, lane, hold) => ({ t, lane, hold: hold || 0 });
  const out = strong.ensurePlayable([n(10, 1, 2), n(12.05, 1), n(13, 2, .3), n(13.25, 2), n(20, 3), n(20.05, 3), n(21, 4, 1), n(22.5, 4)]);
  const find = (t, lane) => out.find(x => x.t === t && x.lane === lane);
  assert(Math.abs(find(10, 1).hold - (12.05 - .22 - 10)) < 1e-6, 'a hold ending right before the next note is trimmed');
  assert.equal(find(13, 2).hold, 0, 'a hold too short after trimming becomes a single note');
  assert(!find(20.05, 3), 'an impossible 50ms jack loses its second note');
  assert.equal(find(21, 4).hold, 1, 'a hold with enough room is untouched');
  assert.equal(out.length, 7);
}

/* 곡 목록을 불러올 때 분석 결과가 곡 정보에 실려야 실제 게임에서 연출이 켜진다 */
const start2 = html.slice(html.indexOf('async function startPlay('), html.indexOf('async function startPlay(') + 2500);
assert(/P\.notes = ensurePlayable\(addDropAccents\(P\.notes, P\.rushes/.test(start2),
  'the game adds the accents, then makes every lane playable, when play starts');
const loader = html.slice(html.indexOf('function loadManifest('), html.indexOf('function loadManifest(') + 3000);
assert(/drops:\s*Array\.isArray\(s\.drops\)/.test(loader) && /rests:\s*Array\.isArray\(s\.rests\)/.test(loader),
  'loadManifest passes drops/rests into the song the game plays');

const songs = JSON.parse(fs.readFileSync(path.join(root, 'songs', 'songs.json'), 'utf8'));
const byTitle = t => songs.find(s => s.title === t);
assert.equal(byTitle('입시 스트레스').drops.length + byTitle('입시 스트레스').rests.length, 0, '입시 스트레스: no effects (user choice)');
assert.equal(byTitle('My Cocktail').drops.length, 0, 'My Cocktail: no drops (user choice)');
assert.equal(byTitle('말하지 못한 진심').drops.length, 0, '말하지 못한 진심: no drops (user choice)');
assert.equal(byTitle('폴라로이드 사진').drops.length, 0, '폴라로이드: no drops (user choice)');
/* 쉬어가기는 시티팝(My Cocktail·깊은 밤·폴라로이드 사진)과 발라드(두 사람의 행복을 빌어·말하지 못한 진심)의 여려지는 곳에 — 사용자 선택 */
for (const t of ['My Cocktail', '깊은 밤', '폴라로이드 사진', '두 사람의 행복을 빌어', '말하지 못한 진심']) {
  const song = byTitle(t);
  assert(song.rests.length >= 1 && song.rests.length <= 2, t + ': one or two rests where it goes soft');
  const chart = JSON.parse(fs.readFileSync(path.join(root, 'songs', song.charts.hard), 'utf8'));
  const built = strong.buildRhythmRushes(chart.notes, song, 'hard', chart.bpm).filter(r => r.kind === 'rest');
  assert.equal(built.length, song.rests.length, t + ': every rest actually plays');
  const kept = strong.addDropAccents(chart.notes, built, chart.bpm, 7);
  for (const r of built) assert(!kept.some(n => n.t > r.quiet[0] && n.t < r.quiet[1]), t + ': no note arrives while it slows down');
}
{
  /* Bass Control: 쉬어가기 없음 — 몰아치기 앞에서도 느려지지 않는다(사용자 확인) */
  const b = byTitle('Bass Control');
  assert.equal(b.rests.length, 0, 'Bass Control: no rests (user choice)');
  assert(b.drops.length && b.drops.every(d => d.slow === false && d.from === undefined), 'Bass Control: drops never slow down first');
  const chart = JSON.parse(fs.readFileSync(path.join(root, 'songs', b.charts.hard), 'utf8'));
  const r = strong.buildRhythmRushes(chart.notes, b, 'hard', chart.bpm);
  assert(r.length > 0, 'Bass Control still has its drop');
  for (const x of r) assert(x.phases.every(p => p.a >= 1 && p.b >= 1), 'Bass Control: scroll never goes below normal speed');
}
assert.deepEqual(byTitle('Break It Down').drops[1].hits, [167.85, 168.202, 168.584], 'Break It Down 2:47.8: three hits on the user taps / real drum attacks');
assert.deepEqual(byTitle('G_Force').drops[0].hits, [66.427, 66.842, 67.301, 67.727], 'G_Force: "3, 2, 1, Ho!" four hits');
{
  /* 3=6키, 2=4키(각 손 바깥·안쪽), 1·Ho=2키(각 손 가운데) — 손가락 자리 a s d / j k l */
  const g = byTitle('G_Force');
  const chart = JSON.parse(fs.readFileSync(path.join(root, 'songs', g.charts.hard), 'utf8'));
  const r = strong.buildRhythmRushes(chart.notes, g, 'hard', chart.bpm);
  for (const [lanes, labels] of [[6, 'SDFJKL'], [7, 'SDF JKL']]) {
    const acc = strong.addDropAccents(chart.notes, r, chart.bpm, lanes).filter(n => n.accent);
    const shape = [66.427, 66.842, 67.301, 67.727].map(h => acc.filter(n => n.t === h).map(n => labels[n.lane]).join(''));
    assert.deepEqual(shape, ['SDFJKL', 'SFJL', 'DK', 'DK'], lanes + '-key countdown chord shapes');
  }
}
assert.deepEqual(byTitle('거침없이 가자 (NC 다이노스)').drops.map(d => d.hits.length), [4, 4, 4],
  '거침없이 가자: "Dinos, Go!" twice per section → Go · Hey · Go · Hey');
assert.equal(byTitle('두 사람의 행복을 빌어').drops.length, 0, 'ballad: no drops (user choice)');
{
  const stay = byTitle('Stay with me_ make me real');
  assert.deepEqual(stay.rests, [], 'Stay with me: user removed every rest so the vocal melody keeps flowing');
}
let withEffect = 0;
for (const librarySong of songs) {
  assert(Array.isArray(librarySong.drops) && Array.isArray(librarySong.rests), librarySong.title + ': analysed');
  for (const diff of ['normal', 'hard']) {
    const chart = JSON.parse(fs.readFileSync(path.join(root, 'songs', librarySong.charts[diff]), 'utf8'));
    const actual = strong.buildRhythmRushes(chart.notes, librarySong, diff, chart.bpm);
        actual.forEach((r, i) => {
      const source = r.kind === 'drop' ? librarySong.drops.map(d => d.t) : librarySong.rests.map(x => x.from);
      assert(source.includes(r.land), librarySong.title + ': only at a measured moment');

      if (i) assert(actual[i - 1].end < r.start, librarySong.title + ': windows do not overlap');
    });
    checkMotion(actual, librarySong.title + ' ' + diff);
    if (diff === 'hard' && actual.length) {
      withEffect++;
      console.log('  ' + librarySong.title.padEnd(26), actual.map(r => (r.kind === 'drop' ? '몰아치기 ' : '쉬어가기 ') + r.land.toFixed(1)).join(' · '));
    }
  }
}
assert(withEffect > 0 && withEffect < songs.length, 'the effect is kept for songs where it fits, not every song');
console.log('PASS: waveform-measured drops/rests (' + withEffect + '/' + songs.length +
  ' songs), real landing hits, smooth motion, unchanged judgement timing');
