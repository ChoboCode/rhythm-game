/* ffmpeg 로 음원을 읽고 index.html 의 실제 채보 생성기로 난이도별 채보를 만든다.
   사용: node tools/build-song-charts.cjs "songs/곡.mp3" [--write] */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');

const input = process.argv[2];
if (!input) throw new Error('음악 파일 경로를 입력하세요.');
const source = path.resolve(input);
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8').replace(/\r\n/g, '\n');
const blocks = html.split('<script>\n').slice(1).map(x => x.split('\n</script>')[0]);
function script(label) {
  const result = blocks.find(x => x.slice(0, 180).includes(label));
  if (!result) throw new Error(label + ' 스크립트를 찾지 못했습니다.');
  return result;
}
const scope = { Math, Date, console, Float32Array, Uint32Array, Int32Array, Error };
vm.createContext(scope);
vm.runInContext(script('fft.js'), scope);
vm.runInContext(script('chart.js'), scope);
vm.runInContext('this.Chart = ChartGen;', scope);

const decoded = spawnSync('ffmpeg', [
  '-v', 'error', '-i', source, '-f', 'f32le', '-acodec', 'pcm_f32le',
  '-ac', '1', '-ar', '22050', 'pipe:1'
], { maxBuffer: 96 * 1024 * 1024 });
if (decoded.error || decoded.status !== 0) throw new Error(String(decoded.error || decoded.stderr));
const bytes = decoded.stdout;
const samples = new Float32Array(bytes.length / 4);
for (let i = 0; i < samples.length; i++) samples[i] = bytes.readFloatLE(i * 4);
const title = path.basename(source, path.extname(source));
const stem = path.join(path.dirname(source), title);
const manifestPath = path.join(__dirname, '../songs/songs.json');
const manifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')) : [];
const song = manifest.find(item => item.file === path.basename(source));

for (const difficulty of ['easy', 'normal', 'hard']) {
  const job = scope.Chart.createJob(samples, 22050, { difficulty });
  while (!job.done) job.step(1000);
  const chart = job.chart;
  chart.title = song && song.title || title;
  if (song && song.key) chart.key = song.key;
  console.log(difficulty, 'BPM', chart.bpm, '확신도', chart.confidence,
    '첫 박', chart.beatOffset, '노트', chart.notes.length,
    '첫 노트', chart.notes[0] && chart.notes[0].t,
    '마지막 노트', chart.notes.at(-1) && chart.notes.at(-1).t);
  if (process.argv.includes('--write')) {
    const target = stem + '.' + difficulty + '.json';
    fs.writeFileSync(target, JSON.stringify(chart));
    console.log('저장', target);
  }
}
