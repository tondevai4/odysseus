(function () {
  const brand = Object.freeze({
    name: 'Vanta',
    wordmark: 'VANTA',
    tagline: 'A better you every day',
  });
  const homeTaglines = Object.freeze([
    'What are we handling?',
    'What needs sorting?',
    'What\u2019s the move?',
    'Let\u2019s get one thing done.',
    'A better you every day.',
    'No speeches. Evidence.',
    'Small win. Clean execution.',
    'Correction over self-hate.',
    'Action over rumination.',
  ]);

  window.VANTA_BRAND = brand;

  function localGreeting(date) {
    const hour = date.getHours();
    if (hour >= 5 && hour < 12) return 'Morning, Boss.';
    if (hour >= 12 && hour < 17) return 'Afternoon, Boss.';
    if (hour >= 17 && hour < 22) return 'Evening, Boss.';
    return 'Night, Boss.';
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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyBranding, { once: true });
  } else {
    applyBranding();
  }
})();
