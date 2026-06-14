(function () {
  const brand = Object.freeze({
    name: 'Vanta',
    wordmark: 'VANTA',
    tagline: 'A better you every day',
    greeting: 'Morning, Boss. What are we handling today?',
  });

  window.VANTA_BRAND = brand;

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
      node.textContent = brand.greeting;
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
