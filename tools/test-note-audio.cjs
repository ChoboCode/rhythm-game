/* 실제 audio.js 를 가짜 AudioContext 로 실행해 입력 시각과 곡별 음색을 확인한다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8').replace(/\r\n/g, '\n');
const audio = html.split('<script>\n').slice(1).map(x => x.split('\n</script>')[0])
  .find(x => x.slice(0, 180).includes('audio.js'));
assert.ok(audio, 'audio.js 스크립트를 찾을 수 있어야 한다');

const sources = [];
class AudioContextStub {
  constructor() { this.sampleRate = 44100; this.currentTime = 10; this.state = 'running'; this.destination = {}; }
  createGain() { return { gain: { value: 1,
      cancelScheduledValues() {},
      setValueAtTime(value) { this.value = value; },
      linearRampToValueAtTime(value) { this.value = value; }
    }, destination: null,
    connect(destination) { this.destination = destination; } }; }
  createDynamicsCompressor() {
    return { threshold: { value: 0 }, knee: { value: 0 }, ratio: { value: 0 },
      attack: { value: 0 }, release: { value: 0 }, destination: null,
      connect(destination) { this.destination = destination; } };
  }
  createChannelSplitter() { return { connect() {} }; }
  createAnalyser() { return { fftSize: 0, connect() {} }; }
  createBuffer(channels, length, sampleRate) {
    const data = Array.from({ length: channels }, () => new Float32Array(length));
    return { length, sampleRate, duration: length / sampleRate, getChannelData: i => data[i] };
  }
  createBufferSource() {
    const source = { buffer: null, when: null, stopped: false, destination: null,
      playbackRate: { value: 1 },
      connect(destination) { this.destination = destination; }, disconnect() {},
      start(when) { this.when = when; }, stop() { this.stopped = true; } };
    sources.push(source);
    return source;
  }
}
const scope = { window: { AudioContext: AudioContextStub }, Float32Array, Math, Promise, Set };
vm.createContext(scope);
vm.runInContext(audio, scope);
vm.runInContext('this.Sound = Snd;', scope);
const snd = scope.Sound;
const music = snd.context().createBuffer(1, 44100, 44100);
snd.start(music, 0, 2.2);
snd.setSongBass([5, 2]);
snd.hit('kick', .5);
snd.hit('kick', 2.5);
snd.hit('snare', .5);
snd.hit('hat', .5);
snd.hit('crash', .5);
snd.hit('tom', .5);
assert.equal(sources.length, 7);
/* 곡은 ctx 12.2초에 시작 → 곡 0.5초 = ctx 12.7. 일찍 친 노트의 소리는 누른 순간이 아니라 노트 박자에 난다 */
assert.ok(Math.abs(sources[1].when - 12.7) < 1e-9, '일찍 친 노트 소리는 노트 박자에 예약되어야 한다');
assert.ok(Math.abs(sources[2].when - 14.7) < 1e-9, '다음 구간 노트도 제 박자에');
assert.notEqual(sources[1].buffer, sources[2].buffer, '곡의 저음이 바뀌면 킥 음색도 바뀌어야 한다');
const musicBus = sources[0].destination;
const drumBus = sources[1].destination.destination;
assert.ok(drumBus.gain.value < musicBus.gain.value && drumBus.gain.value > .4,
  '타악기가 원곡을 덮지 않으면서 들려야 한다');
assert.ok(sources.slice(1).every(s => s.destination.gain.value * drumBus.gain.value > .35),
  '모든 드럼의 라우팅 음량이 들릴 정도는 되어야 한다');
assert.ok(drumBus.destination.destination.ratio.value > 1,
  '동시 타격 때 출력에 압축기가 있어야 한다');

function crossings(buffer) {
  const data = buffer.getChannelData(0);
  let count = 0;
  const start = Math.floor(.025 * buffer.sampleRate);
  const end = Math.min(data.length, Math.floor(.075 * buffer.sampleRate));
  for (let i = start + 1; i < end; i++) if (data[i - 1] <= 0 && data[i] > 0) count++;
  return count;
}
function tailPitch(buffer) {
  const samples = buffer.getChannelData(0);
  const sr = buffer.sampleRate;
  const start = Math.floor(.065 * sr), end = Math.floor(.175 * sr);
  let picked = 0, loudest = -1;
  for (let hz = 38; hz <= 82; hz += .5) {
    let real = 0, imaginary = 0;
    for (let i = start; i < end; i++) {
      const angle = 2 * Math.PI * hz * i / sr;
      real += samples[i] * Math.cos(angle);
      imaginary += samples[i] * Math.sin(angle);
    }
    const power = real * real + imaginary * imaginary;
    if (power > loudest) { loudest = power; picked = hz; }
  }
  return picked;
}
assert.ok(crossings(sources[1].buffer) < crossings(sources[3].buffer) / 3,
  '킥은 스네어보다 낮고 잡음 성분이 적어야 한다');
assert.ok(crossings(sources[1].buffer) < crossings(sources[2].buffer),
  'F에 맞춘 킥이 D에 맞춘 킥보다 낮아야 한다');
assert.ok(Math.abs(tailPitch(sources[1].buffer) - 43.65) < 7,
  'F 구간 킥의 들리는 꼬리는 F 음이어야 한다');
assert.ok(Math.abs(tailPitch(sources[2].buffer) - 73.42) < 7,
  'D 구간 킥의 들리는 꼬리는 D 음이어야 한다');
assert.ok(sources[4].buffer.duration < sources[3].buffer.duration,
  '하이햇은 스네어보다 짧아야 한다');
assert.ok(sources[5].buffer.duration > sources[3].buffer.duration,
  '크래시는 스네어보다 길게 울려야 한다');
assert.ok(sources[6].buffer.duration > sources[4].buffer.duration,
  '탐은 하이햇보다 길게 울려야 한다');
snd.setSongBass(null);
snd.hit('kick');
assert.notEqual(sources[7].buffer, sources[1].buffer,
  '곡 저음 정보가 없으면 고정 음정 대신 음정 없는 타격을 쓴다');
assert.equal(sources[7].when, 0, '노트 시각이 없는 소리(빈 건반)는 즉시 나야 한다');
snd.setSfx(false);
snd.hit('kick', .7);
assert.equal(sources.length, 8, '드럼음을 끄면 소리가 추가되지 않아야 한다');
snd.stop();
assert.ok(sources.every(s => s.stopped), '연주 중단 시 예약된 소리도 멈춰야 한다');
snd.setSfx(true);
snd.setSongBass([5, 5]);
snd.setSongFlow([[0, 3, 0], [3, 0, 3]]);
const beforeFlow = sources.length;
snd.hit('kick', 0);
snd.hit('kick', 2);
snd.hit('snare', 0);
snd.hit('snare', 2);
snd.hit('hat', 0);
snd.hit('hat', 2);
assert.equal(sources.length, beforeFlow + 6, 'all three drums play in both sections');
for (let pair = 0; pair < 3; pair++) {
  const first = sources[beforeFlow + pair * 2];
  const second = sources[beforeFlow + pair * 2 + 1];
  assert.notEqual(first.buffer, second.buffer, 'attack and tail follow the song section');
  assert.notEqual(first.destination.gain.value, second.destination.gain.value,
    'volume follows the song section');
}
snd.setSongFlow(null);
snd.hit('kick', 0);
assert.ok(sources.at(-1).buffer, 'unregistered files retain a working drum sound');
const start = html.indexOf('function soundDrum(');
const end = html.indexOf('\n  }', start);
assert.ok(start >= 0 && end > start);
const soundDrum = vm.runInNewContext('(' + html.slice(start, end + 4) + ')',
  { skinLane: lane => lane });
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../songs/songs.json'), 'utf8'));
const hard = JSON.parse(fs.readFileSync(path.join(__dirname, '../songs', manifest[0].charts.hard), 'utf8'));
const movedSnare = hard.notes.find(n => n.drum === 'snare' && ![1, 5].includes(n.lane));
assert.ok(movedSnare, '롱노트를 피하려고 옮긴 스네어 노트가 있어야 한다');
assert.equal(soundDrum(movedSnare), 'snare', '레인이 바뀌어도 원래 드럼 종류를 유지한다');
assert.equal(soundDrum({ lane: 3, hold: 0 }), 'kick', '드럼 정보가 없는 곡은 레인별 소리를 쓴다');

/* 음정이 없는 타악기(스네어·하이햇·크래시)도 곡의 저음 구간이 바뀌면
   재생 속도가 아주 살짝 달라져, 킥과 같은 화성 위에서 함께 움직이는 느낌을 준다. */
snd.setSongBass([0, 11]);
const beforeTilt = sources.length;
snd.hit('snare', 0);
snd.hit('snare', 2);
snd.hit('kick', 0);
assert.notEqual(sources[beforeTilt].playbackRate.value, sources[beforeTilt + 1].playbackRate.value,
  '음정 없는 타악기도 곡의 저음이 바뀌면 재생 속도가 달라져야 한다');
assert.equal(sources[beforeTilt + 2].playbackRate.value, 1,
  '킥처럼 음정이 있는 타악기는 샘플 자체로 음을 바꾸므로 재생 속도는 그대로여야 한다');

console.log('PASS: song-matched bass · section drum dynamics · non-pitched tilt · immediate hit · neutral fallback · mute · stop');
