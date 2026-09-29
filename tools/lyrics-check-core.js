/* Shared, dependency-free timing helpers for the lyric review page and its tests. */
(function (root, factory) {
  const core = factory();
  if (typeof module === 'object' && module.exports) module.exports = core;
  else root.LyricsCheckCore = core;
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';
  const MIN_PIECE = .02;
  const round = (n) => Math.round(n * 1000) / 1000;
  const clamp = (n, lower, upper) => Math.max(lower, Math.min(upper, n));

  /* A compact peak envelope keeps full-song audio out of the canvas paint loop. */
  function waveEnvelope(buffer, binsPerSecond) {
    if (!buffer || !Number.isFinite(buffer.sampleRate) || buffer.sampleRate <= 0 ||
        !Number.isInteger(buffer.length) || buffer.length < 1 ||
        !Number.isInteger(buffer.numberOfChannels) || buffer.numberOfChannels < 1)
      throw new Error('파형을 만들 음원 데이터가 없습니다.');
    const binSamples = Math.max(1, Math.floor(buffer.sampleRate / (binsPerSecond || 320)));
    const count = Math.ceil(buffer.length / binSamples);
    const low = new Float32Array(count), high = new Float32Array(count);
    const channels = Array.from({ length: buffer.numberOfChannels }, (_, i) => buffer.getChannelData(i));
    for (let i = 0; i < count; i++) {
      let min = 0, max = 0;
      const from = i * binSamples, to = Math.min(buffer.length, from + binSamples);
      for (let sample = from; sample < to; sample++) {
        for (let channel = 0; channel < channels.length; channel++) {
          const value = channels[channel][sample];
          if (value < min) min = value;
          if (value > max) max = value;
        }
      }
      low[i] = min; high[i] = max;
    }
    return { low, high, binSeconds: binSamples / buffer.sampleRate, duration: buffer.length / buffer.sampleRate };
  }

  function waveWindow(line, other, duration, zoom, pan) {
    const first = Math.min(line.t, other ? other.t : line.t);
    const last = Math.max(line.end, other ? other.end : line.end);
    const total = Number.isFinite(duration) && duration > 0 ? duration : last + 1.5;
    const fullStart = clamp(first - 1.5, 0, total);
    const fullEnd = clamp(last + 1.5, fullStart + .1, Math.max(total, fullStart + .1));
    const span = (fullEnd - fullStart) / clamp(Number(zoom) || 1, 1, 8);
    const start = fullStart + (fullEnd - fullStart - span) * clamp(Number(pan) || 0, 0, 1);
    return { start, end: start + span, fullStart, fullEnd };
  }

  function waveTimeAt(window, x, width) {
    return window.start + clamp(Number(x) / Math.max(1, Number(width)), 0, 1) * (window.end - window.start);
  }

  function waveXAt(window, time, width) {
    return (time - window.start) / (window.end - window.start) * width;
  }

  function progress(line, t, endT) {
    if (!Array.isArray(line.words) || !line.words.length) {
      return (t - line.t) / Math.max(.12, endT - line.t);
    }
    let total = 0, filled = 0;
    line.words.forEach(function (word, i) {
      const width = (word.text || '').length + (i + 1 < line.words.length ? .5 : 0);
      const span = Math.max(.12, word.end - word.t);
      total += width;
      filled += width * Math.max(0, Math.min(1, (t - word.t) / span));
    });
    return total ? filled / total : 0;
  }

  /* Mirrors index.html/updateLyricCaption: a completed line waits at most 1.2 s. */
  function stateAt(lines, t) {
    let nextIdx = 0;
    while (nextIdx < lines.length && lines[nextIdx].t <= t) nextIdx++;
    let idx = nextIdx - 1, amount = 0;
    if (idx >= 0) {
      const line = lines[idx];
      const nextT = nextIdx < lines.length ? lines[nextIdx].t : Infinity;
      const endT = Number.isFinite(line.end) && line.end > line.t ?
        Math.min(line.end, nextT) : (nextT < Infinity ? nextT : line.t + 5);
      const holdT = nextT - endT <= 1.2 ? nextT : endT;
      if (t >= holdT) idx = -1;
      else amount = progress(line, t, endT);
    }
    return { activeIndex: idx, displayIndex: idx >= 0 ? idx : nextIdx - 1,
             nextIndex: nextIdx, progress: amount };
  }

  function units(line) {
    return Array.isArray(line.segments) && line.segments.length ? line.segments : line.words;
  }

  function spans(line, parts) {
    let cursor = 0;
    return parts.map(function (part) {
      const start = line.text.indexOf(part.text, cursor);
      if (start < 0) throw new Error('가사 글자와 구간의 순서가 다릅니다: ' + line.text);
      cursor = start + part.text.length;
      return { start: start, end: cursor };
    });
  }

  function syncWords(line) {
    if (!Array.isArray(line.segments) || !line.segments.length) return;
    const wordSpans = spans(line, line.words);
    const segmentSpans = spans(line, line.segments);
    wordSpans.forEach(function (span, i) {
      const contained = line.segments.filter(function (_, j) {
        return segmentSpans[j].start >= span.start && segmentSpans[j].end <= span.end;
      });
      if (!contained.length) throw new Error('단어에 속하는 음절이 없습니다.');
      line.words[i].t = contained[0].t;
      line.words[i].end = contained[contained.length - 1].end;
    });
    line.t = line.segments[0].t;
    line.end = line.segments[line.segments.length - 1].end;
  }

  function splitKorean(line) {
    if (Array.isArray(line.segments) && line.segments.length) return false;
    if (!Array.isArray(line.words) || !line.words.length) return false;
    let changed = false;
    const result = [];
    line.words.forEach(function (word) {
      const pieces = [];
      for (const char of word.text) {
        if (/[가-힣]/u.test(char)) pieces.push(char);
        else if (pieces.length) pieces[pieces.length - 1] += char;
        else pieces.push(char);
      }
      if (pieces.length > 1) changed = true;
      pieces.forEach(function (text, i) {
        const duration = word.end - word.t;
        result.push({ text: text, t: round(word.t + duration * i / pieces.length),
                      end: i + 1 === pieces.length ? word.end : round(word.t + duration * (i + 1) / pieces.length) });
      });
    });
    if (!changed) return false;
    line.segments = result;
    syncWords(line);
    return true;
  }

  function syllablePieces(text) {
    const pieces = [];
    for (const char of text) {
      if (/[가-힣]/u.test(char)) pieces.push(char);
      else if (pieces.length) pieces[pieces.length - 1] += char;
      else pieces.push(char);
    }
    return pieces;
  }

  function tapTemplate(line, mode) {
    if (!['words', 'syllables'].includes(mode)) throw new Error('어절 또는 음절을 선택하세요.');
    const copy = JSON.parse(JSON.stringify(line));
    if (mode === 'syllables') {
      if (copy.segments && copy.segments.length) {
        const expanded = [];
        copy.segments.forEach(function (segment) {
          const pieces = syllablePieces(segment.text);
          pieces.forEach(function (text, i) {
            const duration = segment.end - segment.t;
            expanded.push({ text: text, t: round(segment.t + duration * i / pieces.length),
              end: i + 1 === pieces.length ? segment.end : round(segment.t + duration * (i + 1) / pieces.length) });
          });
        });
        copy.segments = expanded;
        syncWords(copy);
      } else if (!splitKorean(copy)) {
        if (!/[가-힣]/u.test(copy.text))
          throw new Error('이 줄에는 나눌 한글 음절이 없습니다. 어절 단위로 찍어 주세요.');
        copy.segments = copy.words.map((word) => ({ text: word.text, t: word.t, end: word.end }));
      }
    }
    if (!Array.isArray(copy.words) || !copy.words.length) throw new Error('시각을 찍을 가사 구간이 없습니다.');
    return copy;
  }

  /* A tap marks each unit's start; the final tap marks the line's end.
     Produce a candidate without touching saved lyrics, so the user can compare first. */
  function retimeByTaps(lines, lineIndex, mode, taps) {
    if (!Array.isArray(lines) || !lines[lineIndex]) throw new Error('가사 줄을 먼저 선택하세요.');
    const line = tapTemplate(lines[lineIndex], mode);
    const parts = mode === 'syllables' ? line.segments : line.words;
    if (!Array.isArray(taps) || taps.length !== parts.length + 1)
      throw new Error('모든 가사 구간의 시작과 마지막 끝을 찍어 주세요.');
    const times = taps.map((value) => round(Number(value)));
    if (times.some((value) => !Number.isFinite(value) || value < 0))
      throw new Error('탭 시각은 0초 이상의 숫자여야 합니다.');
    for (let i = 1; i < times.length; i++) {
      if (times[i] - times[i - 1] < MIN_PIECE - 1e-6)
        throw new Error('탭 시각은 가사 순서대로 0.02초 이상 떨어져야 합니다. 마지막 탭을 취소하고 다시 찍어 주세요.');
    }
    if (lineIndex > 0 && times[0] <= lines[lineIndex - 1].t)
      throw new Error('이전 줄보다 먼저 시작할 수 없습니다.');
    if (lineIndex + 1 < lines.length && times[0] >= lines[lineIndex + 1].t)
      throw new Error('다음 줄보다 늦게 시작할 수 없습니다.');

    if (mode === 'words' && line.segments && line.segments.length) {
      const wordSpans = spans(line, line.words), segmentSpans = spans(line, line.segments);
      const oldWords = line.words.map((word) => ({ t: word.t, end: word.end }));
      line.segments.forEach(function (segment, j) {
        const wordIndex = wordSpans.findIndex((span) =>
          segmentSpans[j].start >= span.start && segmentSpans[j].end <= span.end);
        if (wordIndex < 0) throw new Error('음절과 어절의 글자 순서가 맞지 않습니다.');
        const old = oldWords[wordIndex], duration = Math.max(MIN_PIECE, old.end - old.t);
        const newStart = times[wordIndex], newDuration = times[wordIndex + 1] - newStart;
        segment.t = round(newStart + newDuration * (segment.t - old.t) / duration);
        segment.end = round(newStart + newDuration * (segment.end - old.t) / duration);
      });
      if (line.segments.some((segment) => segment.end - segment.t < MIN_PIECE - 1e-6))
        throw new Error('어절 길이가 기존 음절 수에 비해 너무 짧습니다. 음절 단위로 다시 찍어 주세요.');
      syncWords(line);
    } else {
      parts.forEach(function (part, i) { part.t = times[i]; part.end = times[i + 1]; });
      if (mode === 'syllables') syncWords(line);
      else { line.t = times[0]; line.end = times[times.length - 1]; }
    }
    return line;
  }

  /* Edit a boundary, keeping adjacent pieces joined and word/line bounds in sync. */
  function setBoundary(lines, lineIndex, unitIndex, edge, value) {
    const line = lines[lineIndex];
    const parts = units(line);
    if (!line || !parts || !parts.length || !Number.isInteger(unitIndex) ||
        unitIndex < 0 || unitIndex >= parts.length || !['start', 'end'].includes(edge))
      throw new Error('가사 구간을 먼저 선택하세요.');
    const boundary = unitIndex + (edge === 'end' ? 1 : 0);
    const t = round(Number(value));
    if (!Number.isFinite(t)) throw new Error('올바른 초 단위 시각을 입력하세요.');
    const lower = boundary === 0 ? 0 : parts[boundary - 1].t + MIN_PIECE;
    const upper = boundary === parts.length ? Infinity : parts[boundary].end - MIN_PIECE;
    if (t < lower - 1e-6 || t > upper + 1e-6)
      throw new Error('이웃한 가사 구간과 겹칩니다. ' + lower.toFixed(2) + '초 이후로 지정하세요.');
    if (boundary === 0 && lineIndex > 0 && t <= lines[lineIndex - 1].t)
      throw new Error('이전 줄보다 먼저 시작할 수 없습니다.');
    if (boundary === 0 && lineIndex + 1 < lines.length && t >= lines[lineIndex + 1].t)
      throw new Error('다음 줄보다 늦게 시작할 수 없습니다.');
    if (boundary === 0) {
      parts[0].t = t;
      line.t = t;
    } else if (boundary === parts.length) {
      parts[parts.length - 1].end = t;
      line.end = t;
    } else {
      parts[boundary - 1].end = t;
      parts[boundary].t = t;
    }
    if (line.segments && line.segments.length) syncWords(line);
    else {
      line.t = line.words[0].t;
      line.end = line.words[line.words.length - 1].end;
    }
    return t;
  }

  function shiftLine(lines, lineIndex, newStart) {
    const line = lines[lineIndex];
    const t = round(Number(newStart));
    if (!line || !Number.isFinite(t) || t < 0) throw new Error('올바른 시작 시각을 입력하세요.');
    if (lineIndex > 0 && t <= lines[lineIndex - 1].t)
      throw new Error('이전 줄보다 먼저 시작할 수 없습니다.');
    if (lineIndex + 1 < lines.length && t >= lines[lineIndex + 1].t)
      throw new Error('다음 줄보다 늦게 시작할 수 없습니다.');
    const delta = t - line.t;
    const shift = (part) => { part.t = round(part.t + delta); part.end = round(part.end + delta); };
    line.words.forEach(shift);
    if (line.segments) line.segments.forEach(shift);
    line.t = round(line.t + delta);
    line.end = round(line.end + delta);
    return delta;
  }

  return { progress, stateAt, units, spans, splitKorean, tapTemplate, retimeByTaps,
           waveEnvelope, waveWindow, waveTimeAt, waveXAt,
           setBoundary, shiftLine, round };
});
