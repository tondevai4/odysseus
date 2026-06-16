(function () {
  const brand = Object.freeze({
    name: 'YVES',
    wordmark: 'YVES',
    tagline: 'Powered by STRNOS',
    engine: 'STRNOS',
    engineExpanded: 'SaturnOS',
  });
  const homeTaglines = Object.freeze([
    'What needs sorting?',
    'What’s the move?',
    'Signal over noise.',
    'Receipts over speeches.',
    'Faith with action.',
    'Small win. Clean execution.',
    'Correction over self-hate.',
    'Action over rumination.',
    'SaturnOS online.',
  ]);

  window.VANTA_BRAND = brand;

  function localGreeting(date) {
    const hour = date.getHours();
    if (hour >= 5 && hour < 12) return 'Morning, Boss. Yves is online.';
    if (hour >= 12 && hour < 17) return 'Afternoon, Boss. Yves is online.';
    if (hour >= 17 && hour < 22) return 'Evening, Boss. Yves is online.';
    return 'Night, Boss. Yves is online.';
  }

  window.YVES_LOCAL_GREETING = localGreeting;
  window.VANTA_LOCAL_GREETING = localGreeting;

  function loadBrainTidyPatch() {
    if (document.getElementById('brain-tidy-patch-js')) return;
    const script = document.createElement('script');
    script.id = 'brain-tidy-patch-js';
    script.src = '/static/js/brainTidyPatch.js';
    script.defer = true;
    document.head.appendChild(script);
  }

  function applyBranding() {
    document.querySelectorAll('[data-brand-name]').forEach((node) => {
      node.textContent = brand.name;
    });
    document.querySelectorAll('[data-brand-wordmark]').forEach((node) => {
      node.textContent = brand.wordmark;
    });
    document.querySelectorAll('[data-brand-tagline]').forEach((node) => {
      node.textContent = brand.tagline;
    });
    document.querySelectorAll('[data-brand-greeting]').forEach((node) => {
      node.textContent = localGreeting(new Date());
    });
    const homeTagline = homeTaglines[Math.floor(Math.random() * homeTaglines.length)];
    document.querySelectorAll('[data-brand-home-tagline]').forEach((node) => {
      node.textContent = homeTagline;
    });
    const currentMeta = document.getElementById('current-meta');
    if (currentMeta && currentMeta.textContent.trim() === 'Odysseus Chat') {
      currentMeta.textContent = `${brand.name} Chat`;
    }
    loadBrainTidyPatch();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyBranding, { once: true });
  } else {
    applyBranding();
  }
})();