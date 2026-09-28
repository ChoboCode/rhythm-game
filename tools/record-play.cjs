/* 게임이 실제로 내는 소리를 녹음한다(사람 귀 대신 파형으로 "들어" 보기). 오디오 경로의 MediaRecorder(PCM)로 받아
   ffmpeg으로 WAV로 바꾼다(ScriptProcessor는 메인 스레드가 바쁘면 조각이 빠져 원곡만 틀어도 어긋났다).
   사람처럼 친다: 노트마다 고정된 난수로 평균 +15ms, 표준편차 25ms(±0.1초 안). 결과는 WAV.

   준비(저장소 루트 rhythm-game에서):
     1) 게임 상태를 내보내는 임시 사본:  sed 's/^  const PREVIEW_CACHE_MAX = 2;/&\r\n  window.__dbg = { get P() { return P; } };/' index.html > _dbg-rec.html
     2) python -m http.server 8971   /   chrome --headless=new --remote-debugging-port=9237 --autoplay-policy=no-user-gesture-required
     3) NODE_PATH=<ws 모듈 경로> node tools/record-play.cjs _dbg-rec.html "곡 제목" out.wav 35
     4) python tools/analyze-record.py out.wav "songs/원곡.mp3"   → 뚝 빠지는 순간 수·길이, 원곡과의 상관
   끝나면 _dbg-rec.html은 지운다. */
const WebSocket = require('ws');
const fs = require('fs');
const [PAGE, SONG, OUT, SECS] = [process.argv[2], process.argv[3], process.argv[4], +(process.argv[5] || 30)];
(async () => {
  const list = await fetch('http://localhost:' + (process.env.CDP_PORT || 9237) + '/json/list').then(r => r.json());
  const ws = new WebSocket(list.find(t => t.type === 'page').webSocketDebuggerUrl, { maxPayload: 512 * 1024 * 1024 });
  let id = 0; const pend = new Map(); const logs = [];
  const send = (m, p) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
  ws.on('message', d => { const m = JSON.parse(d); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } else if (m.method === 'Runtime.exceptionThrown') logs.push(JSON.stringify(m.params.exceptionDetails.exception && m.params.exceptionDetails.exception.description)); });
  await new Promise(r => ws.once('open', r));
  await send('Runtime.enable'); await send('Page.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `
    window.__rec = { on: false, chunks: [], mr: null };
    const _conn = AudioNode.prototype.connect;
    AudioNode.prototype.connect = function (to) {
      const r = _conn.apply(this, arguments);
      if (to && to === this.context.destination && !this.context.__dest) {
        /* 오디오 경로에서 그대로 녹음(MediaRecorder, PCM) — 메인 스레드가 바빠도 빠지지 않는다 */
        this.context.__dest = this.context.createMediaStreamDestination();
        _conn.call(this, this.context.__dest);
      }
      return r;
    };` });
  await send('Page.navigate', { url: 'http://localhost:8971/' + PAGE });
  await new Promise(r => setTimeout(r, 6000));
  const ev = async e => { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true }); return r.exceptionDetails ? 'ERR ' + r.exceptionDetails.exception.description : r.result.value; };
  await ev(`[...document.querySelectorAll('#songList [aria-pressed]')].find(b=>b.textContent.includes(${JSON.stringify(SONG)})).click()`);
  await new Promise(r => setTimeout(r, 2500));
  await ev(`(function(){ const b=[...document.querySelectorAll('button')].find(b=>/HARD/i.test(b.textContent)); if(b) b.click(); const f=document.getElementById('btnFail'); if (f && f.getAttribute('aria-pressed')==='true') f.click(); document.getElementById('btnStart').click(); return 1; })()`);
  await new Promise(r => setTimeout(r, 1500));
  await ev(`(function(){ const P=__dbg.P; const codes=['KeyS','KeyD','KeyF','KeyJ','KeyK','KeyL'];
    function human(i){ let x = Math.sin(i * 12.9898) * 43758.5453; x -= Math.floor(x); let y = Math.sin(i * 78.233) * 12543.123; y -= Math.floor(y);
      const g = Math.sqrt(-2 * Math.log(x + 1e-9)) * Math.cos(2 * Math.PI * y); return Math.max(-.1, Math.min(.1, .015 + .025 * g)); }
    const c0 = Snd.context(); const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=pcm') ? 'audio/webm;codecs=pcm' : 'audio/webm'; window.__rec.mr = new MediaRecorder(c0.__dest.stream, { mimeType: mime }); window.__rec.mr.ondataavailable = e => window.__rec.chunks.push(e.data); window.__rec.mr.start(); window.__recStart = Snd.time();
    P.notes.forEach((n, i) => { n.__i = i; });
    window.__bot = setInterval(() => { const t = Snd.time(); for (const n of P.notes) { if (n.__b || n.state !== 'wait') continue; const at = n.t + human(n.__i); if (at - t > .3) break; n.__b = 1;
      setTimeout(() => { const c = codes[n.lane] || codes[0]; document.dispatchEvent(new KeyboardEvent('keydown',{code:c,bubbles:true})); setTimeout(() => document.dispatchEvent(new KeyboardEvent('keyup',{code:c,bubbles:true})), n.hold > 0 ? n.hold * 1000 : 40); }, Math.max(0, (at - Snd.time()) * 1000)); } }, 20);
    return 1; })()`);
  await new Promise(r => setTimeout(r, SECS * 1000));
  const meta = await ev(`(function(){ clearInterval(window.__bot); return { start: window.__recStart, end: Snd.time(), sr: Snd.context().sampleRate }; })()`);
  const b64 = await ev(`new Promise(res => { const mr = window.__rec.mr; mr.onstop = async () => { const buf = new Uint8Array(await new Blob(window.__rec.chunks).arrayBuffer());
    let s = ''; for (let i = 0; i < buf.length; i += 32768) s += String.fromCharCode.apply(null, buf.subarray(i, i + 32768)); res(btoa(s)); }; mr.stop(); })`);
  const tmp = OUT + '.webm';
  fs.writeFileSync(tmp, Buffer.from(b64, 'base64'));
  const FF = fs.existsSync('C:/ffmpeg/bin/ffmpeg.exe') ? 'C:/ffmpeg/bin/ffmpeg.exe' : 'ffmpeg';
  require('child_process').execFileSync(FF, ['-y', '-v', 'error', '-i', tmp, '-ac', '2', '-ar', String(meta.sr), '-c:a', 'pcm_s16le', OUT]);
  fs.unlinkSync(tmp);
  console.log(JSON.stringify(meta), 'logs', logs.join(' | ') || '(none)');
  ws.close(); process.exit(0);
})();
