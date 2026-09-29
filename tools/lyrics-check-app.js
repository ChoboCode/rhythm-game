(function () {
  'use strict';
  const core = window.LyricsCheckCore;
  const $ = (id) => document.getElementById(id);
  const DRAFT_PREFIX = 'seven-lane-lyrics-check-v1:';
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const fmt = (t) => Math.floor(Math.max(0, t) / 60) + ':' + (Math.max(0, t) % 60).toFixed(2).padStart(5, '0');
  const seconds = (t) => Number(t).toFixed(2) + '초';
  const pathFor = (file) => 'songs/' + file.split('/').map(encodeURIComponent).join('/');
  const state = { songs: [], song: null, original: null, working: null, baseHash: '',
    line: 0, unit: 0, feedback: {}, buffer: null, bufferKey: '', loadSeq: 0,
    ctx: null, source: null, raf: 0, playing: false, pos: 0, startedAt: 0,
    startOffset: 0, rate: 1, endAt: Infinity, mode: 'full', playSeq: 0,
    tapSession: null, compare: null };

  function setStatus(message, error) {
    $('status').textContent = message;
    $('status').classList.toggle('error', !!error);
  }
  function hash(raw) {
    let h = 2166136261;
    for (let i = 0; i < raw.length; i++) h = Math.imul(h ^ raw.charCodeAt(i), 16777619);
    return (h >>> 0).toString(16);
  }
  function draftKey() { return DRAFT_PREFIX + state.song.lyrics; }
  function saveDraft() {
    if (!state.song || !state.working) return;
    try { localStorage.setItem(draftKey(), JSON.stringify({ baseHash: state.baseHash,
      working: state.working, feedback: state.feedback })); }
    catch (err) { setStatus('브라우저 임시 저장에 실패했습니다. 수정된 가사 JSON을 내려받아 보관하세요.', true); }
  }
  function infoFor(index) {
    if (!state.feedback[index]) state.feedback[index] = { verdict: '', memo: '', unitIssues: {} };
    return state.feedback[index];
  }
  function changed(index) {
    return JSON.stringify(state.working.lines[index]) !== JSON.stringify(state.original.lines[index]);
  }
  function noted(index) {
    const info = state.feedback[index];
    return !!(info && (info.verdict || info.memo || Object.keys(info.unitIssues || {}).length));
  }

  function renderLineList() {
    if (!state.working) return;
    const box = $('lineList'), savedScroll = box.scrollTop;
    const query = $('searchLines').value.trim().toLowerCase();
    const only = $('onlyIssues').checked;
    box.replaceChildren();
    let found = 0, reviewed = 0;
    state.working.lines.forEach(function (line, index) {
      if (noted(index) || changed(index)) reviewed++;
      if (only && !(noted(index) || changed(index))) return;
      if (query && !line.text.toLowerCase().includes(query) && String(index + 1) !== query) return;
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'lineItem';
      button.classList.toggle('selected', index === state.line);
      button.setAttribute('aria-label', (index + 1) + '번 가사 ' + line.text);
      const no = document.createElement('span'); no.className = 'lineNo'; no.textContent = String(index + 1).padStart(2, '0');
      const label = document.createElement('span'); label.className = 'lyric'; label.textContent = line.text;
      const time = document.createElement('small'); time.textContent = fmt(line.t) + '–' + fmt(line.end);
      label.appendChild(time);
      const badge = document.createElement('span'); badge.className = 'badge';
      badge.textContent = changed(index) ? '수정' : (state.feedback[index] && state.feedback[index].verdict) || '';
      button.append(no, label, badge);
      button.addEventListener('click', function () { selectLine(index); });
      box.appendChild(button); found++;
    });
    if (!found) {
      const empty = document.createElement('p'); empty.className = 'hint'; empty.textContent = '조건에 맞는 가사가 없습니다.';
      box.appendChild(empty);
    }
    box.scrollTop = savedScroll;
    $('reviewCount').textContent = reviewed + ' / ' + state.working.lines.length + '줄 점검·수정';
  }

  function renderUnits() {
    if (!state.working) return;
    const line = state.working.lines[state.line];
    const parts = core.units(line) || [];
    if (state.unit >= parts.length) state.unit = Math.max(0, parts.length - 1);
    $('lineHeading').textContent = (state.line + 1) + ' / ' + state.working.lines.length + '줄 · ' + line.text;
    $('lineTimes').textContent = fmt(line.t) + '–' + fmt(line.end);
    $('unitHeading').textContent = line.segments && line.segments.length ? '(음절 단위)' : '(단어 단위)';
    $('splitSyllables').disabled = !!(line.segments && line.segments.length) || !/[가-힣]/u.test(line.text);
    const box = $('unitList'); box.replaceChildren();
    parts.forEach(function (piece, index) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'unit'; button.dataset.index = String(index);
      button.classList.toggle('selected', index === state.unit);
      button.classList.toggle('issue', !!(infoFor(state.line).unitIssues || {})[index]);
      const word = document.createElement('b'); word.textContent = piece.text;
      const time = document.createElement('small'); time.textContent = fmt(piece.t) + '–' + fmt(piece.end);
      button.append(word, time);
      button.addEventListener('click', function () {
        state.unit = index;
        const target = Math.max(0, piece.t - .6);
        if (state.playing) beginAt(target, Infinity, 'full');
        else { state.pos = target; renderAt(target); }
        renderUnits();
      });
      box.appendChild(button);
    });
    const selected = parts[state.unit];
    $('unitStart').value = selected ? selected.t.toFixed(3) : '';
    $('unitEnd').value = selected ? selected.end.toFixed(3) : '';
    $('unitIssue').setAttribute('aria-pressed', String(!!(infoFor(state.line).unitIssues || {})[state.unit]));
    $('unitIssue').textContent = (infoFor(state.line).unitIssues || {})[state.unit] ? '어긋남 표시 해제' : '이 구간 어긋남 표시';
    const verdict = infoFor(state.line).verdict;
    document.querySelectorAll('#verdicts button').forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.dataset.verdict === verdict));
    });
    $('memo').value = infoFor(state.line).memo || '';
    renderUnitPlayhead(state.pos);
  }

  function renderUnitPlayhead(t) {
    if (!state.working) return;
    const pieces = core.units(state.working.lines[state.line]) || [];
    $('unitList').querySelectorAll('.unit').forEach(function (button, i) {
      button.classList.toggle('current', t >= pieces[i].t && t < pieces[i].end);
    });
  }

  /* Same per-word/per-segment clip rule as setKaraokeLine in index.html. */
  function paintKaraoke(element, line, amount, t) {
    const base = element.querySelector('.karaokeBase'), fill = element.querySelector('.karaokeFill');
    const text = line ? line.text : '';
    const pieces = line && (line.segments || line.words);
    const key = text + '\u0000' + (pieces ? pieces.map((piece) => piece.text).join('\u0000') : '');
    if (element._lyricKey !== key) {
      const basePart = document.createDocumentFragment(), fillPart = document.createDocumentFragment();
      const timed = [];
      let cursor = 0, matched = !!(text && pieces && pieces.length);
      if (matched) pieces.forEach(function (piece) {
        const at = text.indexOf(piece.text, cursor);
        if (at < 0) { matched = false; return; }
        if (at > cursor) {
          const gap = text.slice(cursor, at);
          basePart.appendChild(document.createTextNode(gap));
          fillPart.appendChild(document.createTextNode(gap));
        }
        const plain = document.createElement('span'), colored = document.createElement('span');
        plain.className = colored.className = 'karaokePiece';
        plain.textContent = colored.textContent = piece.text;
        basePart.appendChild(plain); fillPart.appendChild(colored); timed.push(colored);
        cursor = at + piece.text.length;
      });
      if (matched && cursor < text.length) {
        const tail = text.slice(cursor);
        basePart.appendChild(document.createTextNode(tail));
        fillPart.appendChild(document.createTextNode(tail));
      }
      if (matched) { base.replaceChildren(basePart); fill.replaceChildren(fillPart); }
      else { base.textContent = fill.textContent = text; }
      fill.classList.toggle('timedWords', matched);
      element._words = matched ? timed : null;
      element._lyricKey = key;
    }
    if (element._words) pieces.forEach(function (piece, index) {
      const ratio = t === Infinity ? 1 : Math.max(0, Math.min(1,
        (t - piece.t) / Math.max(.08, piece.end - piece.t)));
      element._words[index].style.setProperty('--word-progress', Math.round(ratio * 100) + '%');
    });
    element.style.setProperty('--karaoke-progress', Math.round(Math.max(0, Math.min(1, amount)) * 100) + '%');
  }

  function renderAt(t) {
    if (!state.working) return;
    const lines = state.working.lines;
    const view = core.stateAt(lines, t);
    const index = view.displayIndex;
    const line = index >= 0 ? lines[index] : null;
    $('prevLyric').textContent = index > 0 ? lines[index - 1].text : '';
    $('nextLyric').textContent = index + 1 < lines.length ? lines[index + 1].text : '';
    paintKaraoke($('karaokeNow'), line, view.activeIndex >= 0 ? view.progress : 1,
      view.activeIndex >= 0 ? t : Infinity);
    $('gameState').textContent = view.activeIndex >= 0 ?
      '게임에서 지금 ' + (view.activeIndex + 1) + '번 줄의 황금빛이 진행 중입니다. · 선택한 줄 ' + (state.line + 1) + '번' :
      '게임에서 지금 부르는 줄은 없습니다. · 선택한 줄 ' + (state.line + 1) + '번';
    const duration = state.buffer ? state.buffer.duration : Number(state.song.duration) || lines[lines.length - 1].end;
    $('scrub').max = String(duration);
    $('scrub').value = String(Math.max(0, Math.min(duration, t)));
    $('clock').textContent = fmt(t) + ' / ' + fmt(duration);
    renderUnitPlayhead(t);
    renderCompareAt(t);
  }

  function tapParts(line, mode) {
    const template = core.tapTemplate(line, mode);
    return mode === 'syllables' ? template.segments : template.words;
  }

  function renderTapPanel() {
    if (!state.working) return;
    const mode = $('tapGranularity').value;
    const parts = tapParts(state.working.lines[state.line], mode);
    const session = state.tapSession && state.tapSession.lineIndex === state.line &&
      state.tapSession.mode === mode ? state.tapSession : null;
    const taps = session ? session.taps : [];
    const box = $('tapSequence'); box.replaceChildren();
    parts.concat([{ text: '줄 끝' }]).forEach(function (part, index) {
      const chip = document.createElement('span'); chip.className = 'tapChip';
      chip.classList.toggle('done', index < taps.length);
      chip.classList.toggle('next', !!session && index === taps.length);
      const label = document.createElement('b'); label.textContent = part.text;
      const time = document.createElement('small');
      time.textContent = index < taps.length ? fmt(taps[index]) : '대기';
      chip.append(label, time); box.appendChild(chip);
    });
    const next = parts[taps.length];
    $('tapTarget').textContent = !session ?
      (mode === 'syllables' ? '음절 ' : '어절 ') + parts.length + '개 · 처음부터 찍기를 누르세요.' :
      taps.length < parts.length ? '다음: 「' + next.text + '」 시작' :
      taps.length === parts.length ? '다음: 마지막 가사가 끝나는 순간' :
      session.candidate ? '시각을 모두 찍었습니다. 전후 비교 후 적용하세요.' : '마지막 탭을 취소하고 다시 찍어 주세요.';
    $('captureTap').disabled = !session || taps.length >= parts.length + 1;
    $('captureTap').textContent = session && taps.length < parts.length ?
      '지금 「' + next.text + '」 찍기 · Space' : '지금 들린 가사 찍기 · Space';
    $('undoTap').disabled = !session || !taps.length;
    $('applyTaps').disabled = !session || !session.candidate;
    $('tapHelp').textContent = session ?
      taps.length + ' / ' + (parts.length + 1) + '회 기록 · 느린 배속에서도 원래 음악 시각으로 저장됩니다.' :
      '마지막 줄 끝까지 한 번씩 찍습니다. 느린 배속에서도 원래 음악 시각으로 저장됩니다.';
  }

  function renderCompareAt(t) {
    if (!state.compare || state.compare.lineIndex !== state.line) return;
    const before = state.compare.before, after = state.compare.after;
    paintKaraoke($('compareBefore'), before, core.progress(before, t, before.end), t);
    paintKaraoke($('compareAfter'), after, core.progress(after, t, after.end), t);
  }

  function renderComparison() {
    const comparison = state.compare && state.compare.lineIndex === state.line ? state.compare : null;
    $('comparePanel').hidden = !comparison;
    if (!comparison) return;
    $('compareStatus').textContent = comparison.stage === 'pending' ? '적용 전 미리보기' : '적용 완료';
    $('undoApplied').disabled = comparison.stage !== 'applied';
    const beforeParts = tapParts(comparison.before, comparison.mode);
    const afterParts = tapParts(comparison.after, comparison.mode);
    const box = $('compareDiff'); box.replaceChildren();
    afterParts.forEach(function (part, i) {
      const item = document.createElement('button'); item.type = 'button'; item.className = 'timeDiff';
      const label = document.createElement('b'); label.textContent = part.text + ' ';
      const delta = core.round(part.t - beforeParts[i].t);
      item.append(label, document.createTextNode(fmt(beforeParts[i].t) + ' → ' + fmt(part.t) +
        ' (' + (delta >= 0 ? '+' : '') + delta.toFixed(2) + '초)'));
      item.addEventListener('click', () => seek(Math.min(beforeParts[i].t, part.t) - .35));
      box.appendChild(item);
    });
    const end = document.createElement('button'); end.type = 'button'; end.className = 'timeDiff';
    end.textContent = '줄 끝 ' + fmt(comparison.before.end) + ' → ' + fmt(comparison.after.end);
    end.addEventListener('click', () => seek(Math.min(comparison.before.end, comparison.after.end) - .35));
    box.appendChild(end);
    renderCompareAt(state.pos);
  }

  function startTapping() {
    if (!state.working) return;
    const mode = $('tapGranularity').value;
    try { tapParts(state.working.lines[state.line], mode); }
    catch (err) { setStatus(err.message, true); return; }
    state.tapSession = { lineIndex: state.line, mode: mode, taps: [], candidate: null };
    state.compare = null;
    renderComparison(); renderTapPanel();
    pauseAudio();
    beginAt(Math.max(0, state.working.lines[state.line].t - 2), Infinity, 'full');
    setStatus('노래를 들으며 표시된 가사가 시작할 때마다 Space 또는 큰 버튼을 누르세요.');
  }

  function captureTap() {
    const session = state.tapSession;
    if (!session || session.lineIndex !== state.line || session.candidate) return;
    try {
      const parts = tapParts(state.working.lines[state.line], session.mode);
      if (session.taps.length >= parts.length + 1) return;
      const t = tapTime();
      if (session.taps.length && t - session.taps[session.taps.length - 1] < .02)
        throw new Error('앞의 탭보다 늦은 순간에 눌러 주세요. 잘못 찍었다면 마지막 탭을 취소하세요.');
      session.taps.push(t);
      if (session.taps.length === parts.length + 1) {
        try {
          session.candidate = core.retimeByTaps(state.working.lines, state.line, session.mode, session.taps);
          state.compare = { lineIndex: state.line, before: clone(state.working.lines[state.line]),
            after: clone(session.candidate), mode: session.mode, stage: 'pending' };
          renderComparison();
          setStatus('탭을 모두 받았습니다. 전후 황금빛을 확인한 다음 「찍은 시각 적용」을 누르세요.');
        } catch (err) { setStatus(err.message, true); }
      }
      renderTapPanel();
    } catch (err) { setStatus(err.message, true); }
  }

  function undoTap() {
    if (!state.tapSession || !state.tapSession.taps.length) return;
    state.tapSession.taps.pop(); state.tapSession.candidate = null;
    if (state.compare && state.compare.stage === 'pending') state.compare = null;
    renderComparison(); renderTapPanel();
    setStatus('마지막 탭을 취소했습니다. 다시 들리는 순간에 찍어 주세요.');
  }

  function applyTaps() {
    const session = state.tapSession;
    if (!session || !session.candidate || session.lineIndex !== state.line) return;
    state.working.lines[state.line] = clone(session.candidate);
    state.compare.stage = 'applied';
    state.tapSession = null;
    afterEdit('찍은 시각을 적용했습니다. 전후 황금빛을 보며 다시 들을 수 있습니다.');
    renderTapPanel(); renderComparison();
    playLine();
  }

  function undoApplied() {
    if (!state.compare || state.compare.stage !== 'applied' || state.compare.lineIndex !== state.line) return;
    pauseAudio();
    state.working.lines[state.line] = clone(state.compare.before);
    state.compare = null; state.tapSession = null;
    afterEdit('방금 적용한 시각을 되돌렸습니다.');
    renderTapPanel(); renderComparison();
  }

  function reportObject() {
    const entries = [];
    state.working.lines.forEach(function (line, index) {
      if (!changed(index) && !noted(index)) return;
      entries.push({ lineNumber: index + 1, text: line.text, original: state.original.lines[index],
        corrected: line, verdict: (state.feedback[index] || {}).verdict || '',
        memo: (state.feedback[index] || {}).memo || '',
        unitIssues: Object.keys((state.feedback[index] || {}).unitIssues || {}).map(Number).map(function (i) {
          const part = core.units(line)[i];
          return part ? { index: i + 1, text: part.text, t: part.t, end: part.end } : null;
        }).filter(Boolean) });
    });
    return { format: 'seven-lane-lyrics-review-v1', song: state.song.title,
      songFile: state.song.file, lyricsFile: state.song.lyrics, entries: entries };
  }
  function renderReport() {
    if (!state.working) return;
    const report = reportObject();
    if (!report.entries.length) {
      $('report').value = '아직 표시하거나 수정한 가사 줄이 없습니다.';
      return;
    }
    const lines = ['곡: ' + report.song, '가사 파일: ' + report.lyricsFile,
      '점검/수정: ' + report.entries.length + '줄'];
    report.entries.forEach(function (entry) {
      lines.push('', '#' + entry.lineNumber + ' ' + entry.text,
        '  원래 ' + fmt(entry.original.t) + '–' + fmt(entry.original.end) +
        ' → 수정 ' + fmt(entry.corrected.t) + '–' + fmt(entry.corrected.end));
      if (entry.verdict) lines.push('  판정: ' + entry.verdict);
      if (entry.memo) lines.push('  메모: ' + entry.memo);
      if (entry.unitIssues.length) lines.push('  어긋난 구간: ' + entry.unitIssues.map((u) => u.text + '@' + fmt(u.t)).join(', '));
      if (JSON.stringify(entry.original) !== JSON.stringify(entry.corrected))
        lines.push('  수정 데이터: ' + JSON.stringify(entry.corrected));
    });
    $('report').value = lines.join('\n');
  }

  function afterEdit(message) {
    saveDraft(); renderLineList(); renderUnits(); renderAt(state.pos); renderReport();
    renderTapPanel(); renderComparison();
    setStatus(message || '이 브라우저에 임시 저장했습니다.');
  }
  function clearTimingPreview() {
    state.tapSession = null; state.compare = null;
  }
  function editBoundary(edge, value) {
    if (!state.working) return;
    try {
      core.setBoundary(state.working.lines, state.line, state.unit, edge, value);
      clearTimingPreview();
      afterEdit('구간 ' + (edge === 'start' ? '시작' : '끝') + ' 시각을 적용했습니다.');
    } catch (err) { setStatus(err.message, true); }
  }
  function editLineStart(value) {
    if (!state.working) return;
    try { core.shiftLine(state.working.lines, state.line, value); clearTimingPreview(); afterEdit('줄 전체 시각을 옮겼습니다.'); }
    catch (err) { setStatus(err.message, true); }
  }
  function tapTime() {
    if (!state.playing || !state.ctx) throw new Error('먼저 음악을 재생한 뒤 들리는 순간에 눌러 주세요.');
    const correction = Number($('tapOffset').value) / 1000;
    if (!Number.isFinite(correction) || Math.abs(correction) > .3) throw new Error('탭 보정은 −300~300ms로 입력하세요.');
    const latency = state.ctx.outputLatency || state.ctx.baseLatency || 0;
    return core.round(Math.max(0, currentTime() - (latency + correction) * state.rate));
  }
  function tap(action) {
    try { action(tapTime()); }
    catch (err) { setStatus(err.message, true); }
  }

  function selectLine(index) {
    if (!state.working || index < 0 || index >= state.working.lines.length) return;
    pauseAudio();
    state.line = index; state.unit = 0;
    clearTimingPreview();
    const line = state.working.lines[index];
    $('tapGranularity').querySelector('option[value="syllables"]').disabled =
      !(line.segments && line.segments.length) && !/[가-힣]/u.test(line.text);
    $('tapGranularity').value = line.segments && line.segments.length ? 'syllables' : 'words';
    state.mode = 'full'; state.endAt = Infinity;
    state.pos = Math.max(0, state.working.lines[index].t - 1.5);
    renderLineList(); renderUnits(); renderAt(state.pos); renderReport(); renderTapPanel(); renderComparison();
    const item = Array.from($('lineList').children).find((el) => el.classList.contains('selected'));
    if (item) item.scrollIntoView({ block: 'nearest' });
    const url = new URL(location.href);
    url.searchParams.set('song', state.song.title);
    url.searchParams.set('line', String(index + 1));
    history.replaceState(null, '', url);
  }

  async function selectSong(song, initialLine) {
    pauseAudio(); state.loadSeq++; state.playSeq++;
    clearTimingPreview();
    $('resetSong').dataset.armed = '';
    $('resetSong').textContent = '이 곡 수정 초기화';
    const seq = state.loadSeq;
    state.song = song; state.buffer = null; state.bufferKey = '';
    $('loadInfo').textContent = '가사 불러오는 중…';
    try {
      const response = await fetch(pathFor(song.lyrics), { cache: 'no-store' });
      if (!response.ok) throw new Error('가사 파일 HTTP ' + response.status);
      const raw = await response.text();
      if (seq !== state.loadSeq) return;
      state.baseHash = hash(raw);
      state.original = JSON.parse(raw);
      if (!Array.isArray(state.original.lines) || !state.original.lines.length) throw new Error('가사 줄이 없습니다.');
      state.working = clone(state.original); state.feedback = {};
      let saved = null;
      try { saved = JSON.parse(localStorage.getItem(draftKey()) || 'null'); } catch (err) { saved = null; }
      if (saved && saved.baseHash === state.baseHash && saved.working &&
          saved.working.lines && saved.working.lines.length === state.original.lines.length) {
        state.working = saved.working; state.feedback = saved.feedback || {};
        $('loadInfo').textContent = '임시 저장한 수정안을 불러왔습니다.';
      } else if (saved) $('loadInfo').textContent = '가사 원본이 바뀌어 이전 임시 저장을 적용하지 않았습니다.';
      else $('loadInfo').textContent = state.original.lines.length + '줄 · 원하는 줄을 선택하세요.';
      $('audioPart').querySelector('option[value="melody"]').disabled = !(song.stems && song.stems.melody);
      if ($('audioPart').value === 'melody' && !(song.stems && song.stems.melody)) $('audioPart').value = 'original';
      $('songSelect').value = song.title;
      $('searchLines').value = ''; $('onlyIssues').checked = false;
      state.line = 0;
      selectLine(Math.min(state.working.lines.length - 1, Math.max(0, initialLine || 0)));
      setStatus('줄을 선택하고 「이 줄 듣기」를 눌러 확인하세요.');
    } catch (err) {
      if (seq !== state.loadSeq) return;
      state.working = null;
      $('loadInfo').textContent = '가사를 불러오지 못했습니다.';
      setStatus(err.message + ' · rhythm-game 폴더를 웹 서버로 열어 주세요.', true);
    }
  }

  function currentTime() {
    if (!state.playing || !state.ctx) return state.pos;
    return Math.max(0, state.startOffset + (state.ctx.currentTime - state.startedAt) * state.rate);
  }
  function pauseAudio(invalidate) {
    if (invalidate !== false) state.playSeq++;
    if (state.playing) state.pos = currentTime();
    state.playing = false;
    if (state.source) {
      state.source.onended = null;
      try { state.source.stop(); } catch (err) { /* source already ended */ }
      state.source.disconnect(); state.source = null;
    }
    cancelAnimationFrame(state.raf); state.raf = 0;
    $('pause').textContent = '계속 재생';
    if (state.working) renderAt(state.pos);
  }
  async function loadBuffer() {
    const song = state.song;
    const part = $('audioPart').value;
    const file = part === 'melody' ? song.stems.melody : song.file;
    const key = song.file + '|' + part;
    if (state.buffer && state.bufferKey === key) return state.buffer;
    $('loadInfo').textContent = '음원 읽는 중…';
    const response = await fetch(pathFor(file));
    if (!response.ok) throw new Error('음원 HTTP ' + response.status);
    const bytes = await response.arrayBuffer();
    $('loadInfo').textContent = '음원 해독 중…';
    if (!state.ctx) state.ctx = new (window.AudioContext || window.webkitAudioContext)();
    const decoded = await state.ctx.decodeAudioData(bytes);
    if (song !== state.song || part !== $('audioPart').value) throw new Error('곡이 변경되었습니다.');
    state.buffer = decoded; state.bufferKey = key;
    $('loadInfo').textContent = '음원 준비 완료';
    return decoded;
  }
  function tick() {
    if (!state.playing) return;
    const t = currentTime(); state.pos = t;
    renderAt(t);
    if (t >= state.endAt || (state.buffer && t >= state.buffer.duration - .02)) {
      const loop = state.mode === 'line' && $('loop').getAttribute('aria-pressed') === 'true';
      pauseAudio();
      if (loop) playLine();
      return;
    }
    state.raf = requestAnimationFrame(tick);
  }
  async function beginAt(offset, endAt, mode) {
    if (!state.song || !state.working) return;
    const seq = ++state.playSeq;
    try {
      if (!state.ctx) state.ctx = new (window.AudioContext || window.webkitAudioContext)();
      await state.ctx.resume();
      const buffer = await loadBuffer();
      if (seq !== state.playSeq) return;
      pauseAudio(false);
      state.rate = Number($('speed').value) || 1;
      state.startOffset = Math.min(Math.max(0, offset), buffer.duration - .01);
      state.pos = state.startOffset;
      state.endAt = Math.min(endAt, buffer.duration);
      state.mode = mode;
      state.source = state.ctx.createBufferSource();
      state.source.buffer = buffer;
      state.source.playbackRate.value = state.rate;
      state.source.connect(state.ctx.destination);
      state.startedAt = state.ctx.currentTime;
      state.source.start(0, state.startOffset);
      state.playing = true;
      $('pause').textContent = '일시정지';
      state.source.onended = function () { if (state.playing) pauseAudio(); };
      tick();
    } catch (err) { if (seq === state.playSeq) setStatus('음원을 재생하지 못했습니다: ' + err.message, true); }
  }
  function playLine() {
    if (!state.working) return;
    const line = state.working.lines[state.line];
    const before = state.compare && state.compare.lineIndex === state.line ? state.compare.before : line;
    beginAt(Math.max(0, Math.min(line.t, before.t) - 1.5), Math.max(line.end, before.end) + 1.3, 'line');
  }
  function seek(t) {
    if (!state.working) return;
    const playing = state.playing;
    pauseAudio(); state.pos = Math.max(0, Number(t) || 0);
    renderAt(state.pos);
    if (playing) beginAt(state.pos, Infinity, 'full');
  }

  function download(name, object) {
    const blob = new Blob([JSON.stringify(object, null, 1) + '\n'], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = name;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    setStatus(name + ' 다운로드를 요청했습니다. 브라우저 다운로드 목록을 확인하세요.');
  }
  function basename(file) { return file.split('/').pop().replace(/\.json$/i, ''); }

  function wire() {
    $('songSelect').addEventListener('change', function () {
      const song = state.songs.find((s) => s.title === this.value);
      if (song) selectSong(song, 0);
    });
    $('audioPart').addEventListener('change', function () {
      pauseAudio(); state.buffer = null; state.bufferKey = '';
      $('loadInfo').textContent = '재생할 때 새 음원을 불러옵니다.';
    });
    $('speed').addEventListener('change', function () {
      if (state.playing) beginAt(currentTime(), state.endAt, state.mode);
    });
    $('tapGranularity').addEventListener('change', function () {
      clearTimingPreview(); renderTapPanel(); renderComparison();
      setStatus(this.value === 'syllables' ? '음절의 시작을 하나씩 찍습니다.' : '어절의 시작을 하나씩 찍습니다.');
    });
    $('startTaps').addEventListener('click', startTapping);
    $('captureTap').addEventListener('click', captureTap);
    $('undoTap').addEventListener('click', undoTap);
    $('applyTaps').addEventListener('click', applyTaps);
    $('undoApplied').addEventListener('click', undoApplied);
    $('searchLines').addEventListener('input', renderLineList);
    $('onlyIssues').addEventListener('change', renderLineList);
    $('prevLine').addEventListener('click', () => selectLine(state.line - 1));
    $('nextLine').addEventListener('click', () => selectLine(state.line + 1));
    $('playLine').addEventListener('click', playLine);
    $('playFull').addEventListener('click', () => beginAt(state.pos, Infinity, 'full'));
    $('focusCurrent').addEventListener('click', function () {
      if (!state.working) return;
      const index = core.stateAt(state.working.lines, currentTime()).activeIndex;
      if (index < 0) { setStatus('지금 부르는 가사 줄이 없습니다.'); return; }
      state.line = index; state.unit = 0;
      clearTimingPreview();
      const line = state.working.lines[index];
      $('tapGranularity').querySelector('option[value="syllables"]').disabled =
        !(line.segments && line.segments.length) && !/[가-힣]/u.test(line.text);
      $('tapGranularity').value = line.segments && line.segments.length ? 'syllables' : 'words';
      renderLineList(); renderUnits(); renderAt(currentTime()); renderReport(); renderTapPanel(); renderComparison();
      const item = Array.from($('lineList').children).find((el) => el.classList.contains('selected'));
      if (item) item.scrollIntoView({ block: 'nearest' });
      setStatus((index + 1) + '번 줄을 선택했습니다. 판정과 메모가 이 줄에 기록됩니다.');
    });
    $('pause').addEventListener('click', function () {
      if (state.playing) pauseAudio();
      else if (state.working) beginAt(state.pos, state.endAt, state.mode);
    });
    $('loop').addEventListener('click', function () {
      const on = this.getAttribute('aria-pressed') !== 'true';
      this.setAttribute('aria-pressed', String(on));
      this.textContent = on ? '한 줄 반복 켬' : '한 줄 반복 끔';
    });
    $('scrub').addEventListener('input', function () { seek(this.value); });
    $('back5').addEventListener('click', () => seek(currentTime() - 5));
    $('forward5').addEventListener('click', () => seek(currentTime() + 5));
    $('shiftEarlier').addEventListener('click', () => state.working && editLineStart(state.working.lines[state.line].t - .1));
    $('shiftLater').addEventListener('click', () => state.working && editLineStart(state.working.lines[state.line].t + .1));
    $('tapLineStart').addEventListener('click', () => tap(editLineStart));
    $('tapLineEnd').addEventListener('click', () => tap((t) => {
      if (state.working) core.setBoundary(state.working.lines, state.line,
        core.units(state.working.lines[state.line]).length - 1, 'end', t);
      clearTimingPreview();
      afterEdit('줄 끝 시각을 적용했습니다.');
    }));
    $('applyStart').addEventListener('click', () => editBoundary('start', $('unitStart').value));
    $('applyEnd').addEventListener('click', () => editBoundary('end', $('unitEnd').value));
    $('tapUnitStart').addEventListener('click', () => tap((t) => editBoundary('start', t)));
    $('tapUnitEnd').addEventListener('click', () => tap((t) => editBoundary('end', t)));
    $('splitSyllables').addEventListener('click', function () {
      if (!state.working) return;
      try {
        if (!core.splitKorean(state.working.lines[state.line])) {
          setStatus('나눌 한글 음절이 없거나 이미 음절 구간이 있습니다.'); return;
        }
        clearTimingPreview(); $('tapGranularity').value = 'syllables';
        state.unit = 0; infoFor(state.line).unitIssues = {};
        afterEdit('음절 구간을 만들었습니다. 현재 시각은 임시 균등 배치이므로 들으며 수정하세요.');
      } catch (err) { setStatus(err.message, true); }
    });
    $('unitIssue').addEventListener('click', function () {
      if (!state.working) return;
      const issues = infoFor(state.line).unitIssues;
      if (issues[state.unit]) delete issues[state.unit]; else issues[state.unit] = true;
      afterEdit('구간 표시를 저장했습니다.');
    });
    $('verdicts').addEventListener('click', function (event) {
      const button = event.target.closest('button[data-verdict]');
      if (!button || !state.working) return;
      const info = infoFor(state.line);
      info.verdict = info.verdict === button.dataset.verdict ? '' : button.dataset.verdict;
      afterEdit('줄 판정을 저장했습니다.');
    });
    $('memo').addEventListener('input', function () {
      if (!state.working) return;
      infoFor(state.line).memo = this.value;
      saveDraft(); renderLineList(); renderReport();
    });
    $('copyReport').addEventListener('click', async function () {
      if (!state.working) return;
      try { await navigator.clipboard.writeText($('report').value); setStatus('보고서를 복사했습니다. 대화에 붙여 주세요.'); }
      catch (err) { $('report').focus(); $('report').select(); setStatus('보고서를 선택했습니다. Ctrl+C로 복사하세요.'); }
    });
    $('downloadFeedback').addEventListener('click', function () {
      if (state.working) download(basename(state.song.lyrics) + '.review.json', reportObject());
    });
    $('downloadLyrics').addEventListener('click', function () {
      if (state.working) download(state.song.lyrics, state.working);
    });
    $('resetSong').addEventListener('click', function () {
      if (!state.working) return;
      const key = draftKey();
      if (this.dataset.armed !== key) {
        this.dataset.armed = key;
        this.textContent = '다시 눌러 초기화';
        setStatus('이 곡의 임시 수정과 점검 기록을 지우려면 버튼을 다시 누르세요.');
        setTimeout(() => {
          if (this.dataset.armed === key) { this.dataset.armed = ''; this.textContent = '이 곡 수정 초기화'; }
        }, 6000);
        return;
      }
      this.dataset.armed = '';
      this.textContent = '이 곡 수정 초기화';
      state.working = clone(state.original); state.feedback = {}; clearTimingPreview();
      try { localStorage.removeItem(draftKey()); } catch (err) { /* private mode */ }
      state.unit = 0; renderLineList(); renderUnits(); renderAt(state.pos); renderReport(); renderTapPanel(); renderComparison();
      setStatus('이 곡의 임시 수정을 지웠습니다.');
    });
    document.addEventListener('keydown', function (event) {
      if (event.code === 'Space' && state.tapSession &&
          !event.target.closest('input,textarea,select') &&
          !state.tapSession.candidate &&
          state.tapSession.taps.length < tapParts(state.working.lines[state.line], state.tapSession.mode).length + 1) {
        event.preventDefault(); captureTap(); return;
      }
      if (event.target.closest('input,textarea,select,button')) return;
      if (event.code === 'Space') { event.preventDefault(); $('pause').click(); }
      if (event.code === 'ArrowLeft') { event.preventDefault(); $('prevLine').click(); }
      if (event.code === 'ArrowRight') { event.preventDefault(); $('nextLine').click(); }
    });
    document.addEventListener('visibilitychange', function () { if (document.hidden) pauseAudio(); });
  }

  async function init() {
    wire();
    try {
      const response = await fetch('songs/songs.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('곡 목록 HTTP ' + response.status);
      state.songs = (await response.json()).filter((song) => !!song.lyrics);
      const select = $('songSelect'); select.replaceChildren();
      state.songs.forEach(function (song) {
        const option = document.createElement('option'); option.value = song.title; option.textContent = song.title;
        select.appendChild(option);
      });
      const params = new URL(location.href).searchParams;
      const selected = state.songs.find((song) => song.title === params.get('song')) || state.songs[0];
      if (!selected) throw new Error('가사가 있는 곡이 없습니다.');
      const line = Math.max(0, (Number(params.get('line')) || 1) - 1);
      await selectSong(selected, line);
    } catch (err) {
      $('loadInfo').textContent = '곡 목록을 불러오지 못했습니다.';
      setStatus(err.message + ' · rhythm-game 폴더를 웹 서버로 열어 주세요.', true);
    }
  }
  init();
})();
