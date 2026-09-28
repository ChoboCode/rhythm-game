/* 점검용 짧은 wav 생성 (8초, 140 BPM 드럼 패턴) */
const fs = require('fs');
const SR = 44100, SEC = 8, BPM = 140, BEAT = 60 / BPM;
const n = SR * SEC;
const f = new Float32Array(n);
function add(at, dur, gen) {
  const s = Math.floor(at * SR), c = Math.floor(dur * SR);
  for (let i = 0; i < c; i++) { const k = s + i; if (k < n) f[k] += gen(i / SR, i / c); }
}
for (let b = 0; b * BEAT < SEC; b++) {
  const t = b * BEAT;
  add(t, .22, (x, e) => Math.sin(2 * Math.PI * (115 - 72 * e) * x) * Math.pow(1 - e, 2.2) * .9);
  if (b % 2 === 1) add(t, .17, (x, e) => ((Math.random() * 2 - 1) * .6 + Math.sin(2 * Math.PI * 210 * x) * .3) * Math.pow(1 - e, 4) * .7);
  add(t + BEAT / 2, .06, (x, e) => (Math.random() * 2 - 1) * Math.pow(1 - e, 9) * .3);
  add(t + BEAT / 4, .05, (x, e) => (Math.random() * 2 - 1) * Math.pow(1 - e, 11) * .18);
}
const buf = Buffer.alloc(44 + n * 2);
buf.write('RIFF', 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write('WAVE', 8);
buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
buf.writeUInt32LE(SR, 24); buf.writeUInt32LE(SR * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
buf.write('data', 36); buf.writeUInt32LE(n * 2, 40);
for (let i = 0; i < n; i++) buf.writeInt16LE(Math.max(-1, Math.min(1, f[i])) * 32000, 44 + i * 2);
fs.writeFileSync(process.argv[2], buf);
console.log('wav 생성:', process.argv[2], (buf.length / 1024).toFixed(0) + 'KB');
