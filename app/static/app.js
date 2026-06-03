if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js', { scope: '/' });
}

// Multi-select player search
const _selectedPlayers = {}; // { userId: username }

function _renderSelected() {
  const tags = document.getElementById('selected-players-tags');
  const form = document.getElementById('add-players-batch-form');
  const inputs = document.getElementById('batch-player-inputs');
  if (!tags || !form || !inputs) return;
  const entries = Object.entries(_selectedPlayers);
  if (entries.length === 0) {
    tags.classList.add('hidden');
    form.classList.add('hidden');
    return;
  }
  tags.classList.remove('hidden');
  form.classList.remove('hidden');
  tags.innerHTML = entries.map(([uid, name]) =>
    `<span class="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-blue-100 border border-blue-300 text-blue-800 text-sm font-medium">
      ${name}
      <button type="button" onclick="deselectPlayer('${uid}')" class="ml-1 text-blue-500 hover:text-red-500 font-bold leading-none">&times;</button>
    </span>`
  ).join('');
  inputs.innerHTML = entries.map(([uid]) =>
    `<input type="hidden" name="player_user_ids" value="${uid}">`
  ).join('');
}

window.searchPlayers = async function(query) {
  const resultsDiv = document.getElementById('player-search-results');
  if (!resultsDiv) return;
  if (query.length < 2) {
    resultsDiv.classList.add('hidden');
    return;
  }
  const existingUids = [...document.querySelectorAll('[data-player-uid]')]
    .map(el => el.dataset.playerUid).filter(Boolean).join(',');
  try {
    const resp = await fetch(`/users/search?q=${encodeURIComponent(query)}&exclude=${existingUids}`);
    const users = await resp.json();
    if (users.length === 0) {
      resultsDiv.innerHTML = '<div class="px-4 py-3 text-sm text-slate-500">No users found</div>';
    } else {
      resultsDiv.innerHTML = users.map(u => {
        const checked = !!_selectedPlayers[u.user_id];
        return `<label class="flex items-center gap-3 px-4 py-3 hover:bg-blue-50 cursor-pointer border-b border-blue-100 last:border-0">
          <input type="checkbox" class="w-4 h-4 accent-blue-600" ${checked ? 'checked' : ''}
            onchange="togglePlayer('${u.user_id}', '${u.username}', this.checked)">
          <span class="text-blue-900 font-medium">${u.username}</span>
        </label>`;
      }).join('');
    }
    resultsDiv.classList.remove('hidden');
  } catch(e) { console.error('Player search failed', e); }
};

window.togglePlayer = function(userId, username, checked) {
  if (checked) {
    _selectedPlayers[userId] = username;
  } else {
    delete _selectedPlayers[userId];
  }
  _renderSelected();
};

window.deselectPlayer = function(userId) {
  delete _selectedPlayers[userId];
  _renderSelected();
  // uncheck in results if visible
  const resultsDiv = document.getElementById('player-search-results');
  if (resultsDiv) {
    const cb = resultsDiv.querySelector(`input[onchange*="'${userId}'"]`);
    if (cb) cb.checked = false;
  }
};

// Keep for backward compat (Add Me button still uses single-player form)
window.selectPlayer = function(userId, username) {
  togglePlayer(userId, username, true);
};

// Hide search results when clicking outside
document.addEventListener('click', function(e) {
  const results = document.getElementById('player-search-results');
  const input = document.getElementById('player-search-input');
  if (results && input && !input.contains(e.target) && !results.contains(e.target)) {
    results.classList.add('hidden');
  }
});

// Pull-to-refresh
(function () {
  let startY = 0;
  let pulling = false;
  let indicator = null;
  const THRESHOLD = 80; // px to pull before triggering refresh

  function createIndicator() {
    const el = document.createElement('div');
    el.id = 'ptr-indicator';
    el.style.cssText = [
      'position:fixed', 'top:0', 'left:0', 'right:0',
      'display:flex', 'align-items:center', 'justify-content:center',
      'height:0', 'overflow:hidden',
      'background:linear-gradient(to right,#7c3aed,#db2777)',
      'color:#fff', 'font-weight:700', 'font-size:14px',
      'transition:height 0.1s', 'z-index:9999',
    ].join(';');
    el.textContent = '↓ Pull to refresh';
    document.body.prepend(el);
    return el;
  }

  document.addEventListener('touchstart', e => {
    if (window.scrollY === 0) {
      startY = e.touches[0].clientY;
      pulling = true;
      if (!indicator) indicator = createIndicator();
    }
  }, { passive: true });

  document.addEventListener('touchmove', e => {
    if (!pulling) return;
    const dist = Math.max(0, e.touches[0].clientY - startY);
    const height = Math.min(dist * 0.4, THRESHOLD * 0.6);
    indicator.style.height = height + 'px';
    indicator.textContent = dist >= THRESHOLD ? '↑ Release to refresh' : '↓ Pull to refresh';
  }, { passive: true });

  document.addEventListener('touchend', e => {
    if (!pulling) return;
    pulling = false;
    const dist = e.changedTouches[0].clientY - startY;
    if (dist >= THRESHOLD) {
      indicator.style.height = '44px';
      indicator.textContent = '⟳ Refreshing…';
      setTimeout(() => window.location.reload(), 300);
    } else {
      indicator.style.height = '0';
    }
  }, { passive: true });
}());

window.clearScoreInput = function(formEl) {
  const input = formEl.querySelector('input[name="delta"]');
  if (input) input.value = "";
};

window.clearBatchScoreInputs = function() {
  const inputs = document.querySelectorAll('.score-input');
  inputs.forEach(input => input.value = "");
};

window.incrementScore = function(button, amount) {
  const container = button.closest('.flex');
  if (!container) return;
  
  const input = container.querySelector('input[type="number"]');
  if (!input) return;
  
  const currentValue = parseInt(input.value) || 0;
  input.value = currentValue + amount;
  
  // Trigger change event
  input.dispatchEvent(new Event('change', { bubbles: true }));
};
