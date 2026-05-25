if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js', { scope: '/' });
}

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
