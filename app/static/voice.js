// Voice-input scoring for i-quit-scorer.
// Uses the browser Web Speech API. Parses utterances like
//   "Ali 10, Aziz 20, Sara minus 5"
//   "Bob twenty five and Alice negative fifteen"
// and fills the existing per-player score inputs. The scorer then
// reviews the values and clicks the normal "Add All Scores" button.
//
// Zero backend changes: this is purely a client-side enhancement over
// the existing batch scoring form.

(function () {
  'use strict';

  // Word -> number table. Enough for card-game scores (0-999 covers it).
  const NUM_WORDS = {
    zero: 0, oh: 0, o: 0,
    one: 1, two: 2, three: 3, four: 4, five: 5,
    six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
    eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15,
    sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19,
    twenty: 20, thirty: 30, forty: 40, fifty: 50,
    sixty: 60, seventy: 70, eighty: 80, ninety: 90,
    hundred: 100, thousand: 1000,
    // Common Web Speech misrecognitions of small numbers
    to: 2, too: 2, for: 4, ate: 8
  };
  const NEG_WORDS = new Set(['minus', 'negative', 'take', 'less', 'subtract', 'deduct']);

  // Voice commands the scorer can say mid-session to correct mistakes.
  // Each entry is a regex applied to the cleaned lowercase segment.
  const COMMAND_PATTERNS = {
    // "clear all", "reset all", "make all zero", "make all of them zero",
    // "zero all", "everyone zero", "start over", "scratch that", "mistake"
    clearAll: new RegExp(
      '\\b(clear|reset|zero|erase|delete|remove)\\s+(all|every ?one|scores|everything)\\b' +
      '|\\b(all|every ?one|everything)(?:\\s+of\\s+them)?\\s+(zero|clear|reset)\\b' +
      '|\\bmake\\s+(all|every ?one|everything)(?:\\s+of\\s+them)?\\s+(zero|clear|blank)\\b' +
      '|\\b(start over|start again|scratch that|mistake|do over)\\b'
    ),
    // "clear ali", "reset hatim" — captured name in group 2
    clearOne: /\b(clear|reset|zero|erase|delete|remove)\s+([a-z][a-z\s]{0,30}?)\s*$/,
    // "undo" / "undo last" / "take back"
    undo: /\b(undo|undo last|take back|revert)\b/
  };

  // Parse a token slice into a number ("twenty", "twenty five",
  // "one hundred and ten", "42"). Returns null if unparseable.
  function parseNumberWords(tokens) {
    if (tokens.length === 0) return null;
    let total = 0;
    let current = 0;
    let sawAny = false;
    for (const t of tokens) {
      if (t === 'and') continue;
      if (/^-?\d+$/.test(t)) { current += parseInt(t, 10); sawAny = true; continue; }
      const v = NUM_WORDS[t];
      if (v === undefined) return null;
      sawAny = true;
      if (v === 100 || v === 1000) {
        current = Math.max(1, current) * v;
      } else {
        current += v;
      }
    }
    return sawAny ? total + current : null;
  }

  // Dice bigram similarity — robust to short spoken misrecognitions
  // ("Aleee" ~ "Ali"). Returns 0..1.
  function diceCoefficient(a, b) {
    a = String(a).toLowerCase(); b = String(b).toLowerCase();
    if (a === b) return 1;
    if (a.length < 2 || b.length < 2) return a === b ? 1 : 0;
    const bigrams = (s) => {
      const arr = [];
      for (let i = 0; i < s.length - 1; i++) arr.push(s.slice(i, i + 2));
      return arr;
    };
    const A = bigrams(a);
    const B = bigrams(b);
    const bMap = new Map();
    for (const bg of B) bMap.set(bg, (bMap.get(bg) || 0) + 1);
    let inter = 0;
    for (const bg of A) {
      const c = bMap.get(bg);
      if (c > 0) { inter++; bMap.set(bg, c - 1); }
    }
    return (2 * inter) / (A.length + B.length);
  }

  function bestNameMatch(spokenName, players) {
    let best = { player: null, score: 0 };
    for (const p of players) {
      const s = diceCoefficient(spokenName, p);
      if (s > best.score) best = { player: p, score: s };
    }
    return best;
  }

  // Split an utterance into (player, delta, confidence) tuples.
  //
  // Strategy: walk tokens left-to-right. At each position, try to match
  // a known player as a 1-3 token window (longest first). If a name
  // matches with confidence >= 0.6, consume optional "minus"/"negative"
  // and then the longest number that parses (1-4 tokens). Emit the
  // tuple and continue from just past the number. If no name matches
  // at the current position, advance by one token.
  //
  // This handles unpunctuated speech like
  //   "MK 10 Aziz 10 Ali 25 Hatim"    -> 3 tuples (Hatim has no score)
  //   "Sara minus five and Bob twenty" -> 2 tuples
  //   "Ali one hundred and ten"        -> Ali +110
  function parseUtterance(text, players) {
    const cleaned = String(text)
      .toLowerCase()
      .replace(/[.!?,;:()]/g, ' ')
      .replace(/\bplus\b/g, ' ')
      // Split glued alphanumerics: "mk10" -> "mk 10", "10ali" -> "10 ali"
      .replace(/([a-z])(\d)/g, '$1 $2')
      .replace(/(\d)([a-z])/g, '$1 $2')
      .replace(/\s+/g, ' ')
      .trim();
    const tokens = cleaned.split(' ').filter(Boolean);
    const out = [];
    const NAME_CONF = 0.6;
    let i = 0;
    while (i < tokens.length) {
      // Longest-first name match at this position.
      let matched = null;
      const maxName = Math.min(3, tokens.length - i);
      for (let nameLen = maxName; nameLen >= 1; nameLen--) {
        const candidateTokens = tokens.slice(i, i + nameLen);
        // A player name never contains a digit / number-word / negative
        // marker. Reject candidates like "aziz 10" or "twenty ali" which
        // would otherwise fuzzy-match a real name and swallow the number.
        const bad = candidateTokens.some(t =>
          /^-?\d+$/.test(t) || NUM_WORDS[t] !== undefined || NEG_WORDS.has(t));
        if (bad) continue;
        const candidate = candidateTokens.join(' ');
        const m = bestNameMatch(candidate, players);
        if (m.player && m.score >= NAME_CONF) {
          matched = { name: m.player, score: m.score, nameLen, spoken: candidate };
          break;
        }
      }
      if (!matched) { i++; continue; }

      // Optional negative marker between name and number.
      let j = i + matched.nameLen;
      let negative = false;
      if (j < tokens.length && NEG_WORDS.has(tokens[j])) {
        negative = true;
        j++;
      }

      // Longest-first number match starting at j.
      let num = null;
      let numLen = 0;
      const maxNum = Math.min(4, tokens.length - j);
      for (let take = maxNum; take >= 1; take--) {
        const slice = tokens.slice(j, j + take);
        const n = parseNumberWords(slice);
        if (n !== null) { num = n; numLen = take; break; }
      }
      if (num === null) {
        // Name matched but no score followed — record as unmatched-name
        // so the scorer sees it in the preview, then move on.
        out.push({
          player: null,
          delta: 0,
          confidence: 0,
          spoken: matched.spoken + ' (no score)'
        });
        i = j;
        continue;
      }

      out.push({
        player: matched.name,
        delta: negative ? -num : num,
        confidence: matched.score,
        spoken: matched.spoken
      });
      i = j + numLen;
    }
    return out;
  }

  // Expose for future testing / debugging.
  window.IQuitVoice = { parseUtterance, diceCoefficient, parseNumberWords };

  let recognition = null;
  let listening = false;

  function initVoice() {
    const btn = document.getElementById('voice-mic-btn');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';

    const label = document.getElementById('voice-mic-label');
    const transcriptEl = document.getElementById('voice-transcript');
    const previewEl = document.getElementById('voice-preview');

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      btn.disabled = true;
      btn.title = 'Voice input not supported in this browser';
      if (label) label.textContent = '🚫 Voice not supported';
      return;
    }

    // Collect known players + whether the round is locked from the DOM.
    const playerInputs = document.querySelectorAll('.score-input[data-player]');
    const players = Array.from(playerInputs).map(el => el.dataset.player);
    const anyDisabled = Array.from(playerInputs).some(el => el.disabled);
    if (players.length === 0 || anyDisabled) {
      btn.disabled = true;
      btn.title = anyDisabled ? 'Round is locked' : 'No active players';
      if (label) label.textContent = anyDisabled ? '🔒 Round locked' : '🎙️ No players';
      return;
    }

    const setTranscript = (text) => {
      if (!transcriptEl) return;
      transcriptEl.classList.remove('hidden');
      transcriptEl.textContent = text;
    };

    const renderPreview = (results) => {
      if (!previewEl) return;
      previewEl.classList.remove('hidden');
      if (results.length === 0) {
        previewEl.innerHTML = '<div class="text-rose-700">❌ Couldn\'t detect any player + score pairs. Try again.</div>';
        return;
      }
      const lines = results.map(r => {
        const sign = r.delta > 0 ? '+' : '';
        if (r.player === null && r.confidence === 0 && r.delta === 0 && / \(no score\)$/.test(r.spoken)) {
          const name = r.spoken.replace(/ \(no score\)$/, '');
          return `<div class="text-amber-800">⚠️ Heard <b>${name}</b> but no score followed — skipped.</div>`;
        }
        if (!r.player) {
          return `<div class="text-rose-700">❓ "${r.spoken}" → no player matched (${sign}${r.delta} ignored)</div>`;
        }
        const conf = Math.round(r.confidence * 100);
        const cls = conf >= 80 ? 'text-emerald-800' : 'text-amber-800';
        const confCls = conf >= 80 ? 'text-emerald-600' : 'text-amber-600';
        return `<div class="${cls}">✅ <b>${r.player}</b> ${sign}${r.delta} <span class="${confCls}">(${conf}% match)</span></div>`;
      });
      previewEl.innerHTML = lines.join('');

      // Fill the existing inputs. User still reviews and clicks Save.
      for (const r of results) {
        if (!r.player) continue;
        const inp = document.querySelector(`.score-input[data-player="${CSS.escape(r.player)}"]`);
        if (inp && !inp.disabled) {
          inp.value = String(r.delta);
          inp.dispatchEvent(new Event('input', { bubbles: true }));
          // brief flash
          inp.classList.add('ring-4', 'ring-purple-300');
          setTimeout(() => inp.classList.remove('ring-4', 'ring-purple-300'), 900);
        }
      }
    };

    // Accumulated results across a single "listening" session, keyed
    // by player. Later utterances for the same player overwrite.
    let accumulated = new Map(); // player -> {delta, confidence, spoken}
    let unmatched = [];          // {spoken, delta}
    let finalTranscript = '';

    const rebuildPreview = () => {
      const results = [];
      for (const [player, r] of accumulated) {
        results.push({ player, delta: r.delta, confidence: r.confidence, spoken: r.spoken });
      }
      results.push(...unmatched);
      renderPreview(results);
    };

    const applySegment = (segText) => {
      // Voice commands first — they short-circuit normal parsing.
      const norm = segText.toLowerCase().replace(/[.!?,;:()]/g, ' ').replace(/\s+/g, ' ').trim();

      if (COMMAND_PATTERNS.clearAll.test(norm)) {
        // Wipe every score input and every accumulated entry.
        for (const inp of document.querySelectorAll('.score-input[data-player]')) {
          if (inp.disabled) continue;
          inp.value = '';
          inp.dispatchEvent(new Event('input', { bubbles: true }));
          inp.classList.add('ring-4', 'ring-rose-300');
          setTimeout(() => inp.classList.remove('ring-4', 'ring-rose-300'), 900);
        }
        accumulated = new Map();
        unmatched = [];
        if (previewEl) {
          previewEl.classList.remove('hidden');
          previewEl.innerHTML = '<div class="text-rose-700">🧹 Cleared all scores — start over.</div>';
        }
        return;
      }

      if (COMMAND_PATTERNS.undo.test(norm)) {
        // Drop the most recently added accumulated entry.
        const last = Array.from(accumulated.keys()).pop();
        if (last) {
          const inp = document.querySelector(`.score-input[data-player="${CSS.escape(last)}"]`);
          if (inp) { inp.value = ''; inp.dispatchEvent(new Event('input', { bubbles: true })); }
          accumulated.delete(last);
          rebuildPreview();
          if (previewEl) previewEl.insertAdjacentHTML('afterbegin',
            `<div class="text-amber-800">↩️ Undid last: <b>${last}</b></div>`);
        }
        return;
      }

      const clearOneMatch = norm.match(COMMAND_PATTERNS.clearOne);
      if (clearOneMatch) {
        const spokenName = clearOneMatch[2].trim();
        const m = bestNameMatch(spokenName, players);
        if (m.player && m.score >= 0.6) {
          const inp = document.querySelector(`.score-input[data-player="${CSS.escape(m.player)}"]`);
          if (inp && !inp.disabled) {
            inp.value = '';
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.classList.add('ring-4', 'ring-rose-300');
            setTimeout(() => inp.classList.remove('ring-4', 'ring-rose-300'), 900);
          }
          accumulated.delete(m.player);
          rebuildPreview();
          if (previewEl) previewEl.insertAdjacentHTML('afterbegin',
            `<div class="text-rose-700">🧹 Cleared <b>${m.player}</b>.</div>`);
          return;
        }
      }

      // Normal name+score parsing.
      const results = parseUtterance(segText, players);
      for (const r of results) {
        if (r.player) {
          accumulated.set(r.player, { delta: r.delta, confidence: r.confidence, spoken: r.spoken });
        } else {
          unmatched.push(r);
        }
      }
      rebuildPreview();
    };

    recognition = new SR();
    recognition.lang = navigator.language || 'en-US';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    let userWantsListening = false;

    recognition.onstart = () => {
      listening = true;
      btn.classList.add('animate-pulse', 'ring-4', 'ring-purple-300');
      if (label) label.textContent = '🔴 Listening… (tap to stop)';
      if (finalTranscript === '') setTranscript('Say a player and score, pause, then the next…');
    };

    recognition.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const seg = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          const trimmed = seg.trim();
          if (trimmed) {
            finalTranscript = (finalTranscript ? finalTranscript + ' • ' : '') + trimmed;
            applySegment(trimmed);
          }
        } else {
          interim += seg;
        }
      }
      const display = (finalTranscript + (interim ? '  |  ' + interim.trim() : '')).trim();
      setTranscript(display || '…');
    };

    recognition.onerror = (event) => {
      // "no-speech" fires often in continuous mode; just restart silently.
      if (event.error === 'no-speech' && userWantsListening) {
        try { recognition.stop(); } catch (e) {}
        return;
      }
      listening = false;
      userWantsListening = false;
      btn.classList.remove('animate-pulse', 'ring-4', 'ring-purple-300');
      if (label) label.textContent = '🎙️ Speak scores';
      const errMsg = event.error === 'not-allowed'
        ? 'Microphone permission denied. Enable it in the browser and try again.'
        : `Error: ${event.error}`;
      setTranscript(errMsg);
    };

    recognition.onend = () => {
      listening = false;
      btn.classList.remove('animate-pulse', 'ring-4', 'ring-purple-300');
      // Auto-restart if the user hasn't manually stopped — some browsers
      // end the session after a short silence even in continuous mode.
      if (userWantsListening) {
        try { recognition.start(); return; } catch (e) { /* fallthrough */ }
      }
      if (label) label.textContent = '🎙️ Speak scores';
    };

    btn.addEventListener('click', () => {
      if (listening || userWantsListening) {
        userWantsListening = false;
        try { recognition.stop(); } catch (e) { /* noop */ }
        return;
      }
      // Fresh listening session — reset accumulator so previous take doesn't
      // stack on top of the new one.
      accumulated = new Map();
      unmatched = [];
      finalTranscript = '';
      if (previewEl) previewEl.classList.add('hidden');
      userWantsListening = true;
      try { recognition.start(); }
      catch (e) { /* "already started" */ }
    });
  }

  document.addEventListener('DOMContentLoaded', initVoice);
  document.body.addEventListener('htmx:afterSwap', initVoice);
})();
