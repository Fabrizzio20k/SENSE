(() => {
  'use strict';
  const key = 'sense-motion';
  const root = document.documentElement;
  const preference = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  let userChoice;
  try { userChoice = window.localStorage.getItem(key); } catch (_) { userChoice = null; }
  function update() {
    const enabled = userChoice !== 'off' && !preference?.matches;
    root.dataset.motion = enabled ? 'on' : 'off';
    const button = document.getElementById('motion-toggle');
    if (button) {
      button.disabled = !!preference?.matches;
      button.textContent = preference?.matches ? 'Movimiento reducido' : enabled ? 'Detener animaciones' : 'Activar animaciones';
      button.setAttribute('aria-pressed', String(!enabled));
    }
  }
  document.addEventListener('DOMContentLoaded', () => {
    update();
    document.getElementById('motion-toggle')?.addEventListener('click', () => {
      userChoice = root.dataset.motion === 'on' ? 'off' : 'on';
      try { window.localStorage.setItem(key, userChoice); } catch (_) { /* La preferencia sigue en esta pestaña. */ }
      update();
    });
  });
  preference?.addEventListener?.('change', () => { if (userChoice == null) update(); });
})();
