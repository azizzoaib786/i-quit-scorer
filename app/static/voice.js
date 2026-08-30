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
  function parseUtterance(text, players) {
    const cleaned = text
      .toLowerCase()
      .replace(/[.!?]/g, '')
      .replace(/\bplus\b/g, '')
      .replace(/\s+and\s+/g, ',')
      .replace(/;|\n/g, ',');
    const entries = cleaned.split(',').map(s => s.trim()).filter(Boolean);
    const out = [];
    for (const entry of entries) {
      const tokens = entry.split(/\s+/).filter(Boolean);
      if (tokens.length < 2) continue;

      // Grab the tail as the number (try 1..4 tokens).
      let numTokens = [];
      let nameTokens = tokens.slice();
      for (let take = 1; take <= 4 && take < tokens.length; take++) {
        const slice = tokens.slice(tokens.length - take);
        const n = parseNumberWords(slice);
        if (n !== null) {
          numTokens = slice;
          nameTokens = tokens.slice(0, tokens.length - take);
        }
      }
      if (numTokens.length === 0) continue;

      // Negative word can appear immediately before the number.
      let negative = false;
      if (nameTokens.length && NEG_WORDS.has(nameTokens[nameTokens.length - 1])) {
        negative = true;
        nameTokens = nameTokens.slice(0, -1);
      }
      if (nameTokens.length === 0) continue;

      const num = parseNumberWords(numTokens);
      if (num === null) continue;

      const spokenName = nameTokens.join(' ');
      const match = bestNameMatch(spokenName, players);
      const delta = negative ? -num : num;

      if (!match.player || match.score < 0.5) {
        out.push({ player: null, delta, confidence: 0, spoken: spokenName });
      } else {
        out.push({ player: match.player, delta, confidence: match.score, spoken: spokenName });
      }
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
        if (!r.player) {
          return `<div class="text-rose-700">❓ "${r.spoken}" → no player matched (${sign}${r.delta} ignored)</div>`;
        }
        const conf = Math.round(r.confidence * 100);
        const cls = conf >= 80
          ? 'text-emerald-800'
          : 'text-amber-800';
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

    recognition = new SR();
    recognition.lang = navigator.language || 'en-US';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      listening = true;
      btn.classList.add('animate-pulse', 'ring-4', 'ring-purple-300');
      if (label) label.textContent = '🔴 Listening… (tap to stop)';
      setTranscript('…');
      if (previewEl) previewEl.classList.add('hidden');
    };

    recognition.onresult = (event) => {
      let interim = '', final = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) final += t;
        else interim += t;
      }
      setTranscript((final || interim || '').trim() || '…');
    };

    recognition.onerror = (event) => {
      listening = false;
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
      if (label) label.textContent = '🎙️ Speak scores';
      const text = (transcriptEl && transcriptEl.textContent || '').trim();
      if (!text || text === '…') return;
      const results = parseUtterance(text, players);
      renderPreview(results);
    };

    btn.addEventListener('click', () => {
      if (listening) {
        try { recognition.stop(); } catch (e) { /* noop */ }
        return;
      }
      try {
        recognition.start();
      } catch (e) {
        // "already started" — safe to ignore
      }
    });
  }

  document.addEventListener('DOMContentLoaded', initVoice);
  document.body.addEventListener('htmx:afterSwap', initVoice);
})();
