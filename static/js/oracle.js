/* STRNOS Oracle - Phase 3 Logic (Modal Version) */

const API_BASE = '/api/oracle';
let _initialized = false;
let _modal = null;
let oracleData = null;
let _activeTab = 'dashboard';

function ensureStyles() {
  if (document.getElementById('oracle-css')) return;
  const link = document.createElement('link');
  link.id = 'oracle-css';
  link.rel = 'stylesheet';
  link.href = '/static/css/oracle.css';
  document.head.appendChild(link);
}

async function fetchOracleData() {
  try {
    const res = await fetch(API_BASE);
    if (!res.ok) throw new Error('Failed to load Oracle data');
    oracleData = await res.json();
    return oracleData;
  } catch (err) {
    console.error(err);
    return null;
  }
}

function build() {
  ensureStyles();
  if (document.getElementById('oracle-modal')) return;

  _modal = document.createElement('div');
  _modal.className = 'oracle-modal';
  _modal.id = 'oracle-modal';
  _modal.hidden = true;
  
  _modal.innerHTML = `
    <!-- Ambient Background -->
    <div class="strnos-canvas-bg">
      <div class="strnos-nebula"></div>
      <div class="strnos-cyan-glow"></div>
    </div>

    <main class="strnos-dashboard" id="oracle-root" style="border-radius: 24px; box-shadow: 0 12px 40px rgba(0,0,0,0.8);">
      <button class="strnos-close-btn" id="oracle-close-btn"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button>
      
      <!-- Sidebar -->
      <aside class="strnos-sidebar">
        <div class="strnos-brand">
          <h1>STRNOS</h1>
          <p>Phase 3 Oracle</p>
        </div>

        <nav class="strnos-nav" id="oracle-nav">
          <button class="strnos-nav-btn active" data-view="dashboard">
            <span style="font-size: 18px; margin-right: 8px;">⎈</span> Cosmic Dashboard
          </button>
          <button class="strnos-nav-btn" data-view="chart">
            <span style="font-size: 18px; margin-right: 8px;">✧</span> Natal Chart
          </button>
          <button class="strnos-nav-btn" data-view="transits">
            <span style="font-size: 18px; margin-right: 8px;">◷</span> Current Transits
          </button>
          <button class="strnos-nav-btn" data-view="manifest">
            <span style="font-size: 18px; margin-right: 8px;">✦</span> Manifestations
          </button>
          <button class="strnos-nav-btn" data-view="signs">
            <span style="font-size: 18px; margin-right: 8px;">⌾</span> Synchronicities
          </button>
        </nav>

        <div class="strnos-user-card">
          <div class="strnos-avatar">T</div>
          <div class="strnos-user-info">
            <h4 id="oracle-user-name">TJ</h4>
            <p id="oracle-user-sun-sign">Loading sign...</p>
          </div>
        </div>
      </aside>

      <!-- Main Content -->
      <section class="strnos-main" id="oracle-app">
        <!-- Loading State -->
        <div class="strnos-loader" id="oracle-loader">
          <div class="strnos-spinner"></div>
          <p>Aligning the stars...</p>
        </div>
      </section>
    </main>
  `;

  document.body.appendChild(_modal);

  // Bind close
  _modal.querySelector('#oracle-close-btn').addEventListener('click', close);
  
  // Bind Nav
  const navBtns = _modal.querySelectorAll('.strnos-nav-btn');
  navBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      navBtns.forEach(b => b.classList.remove('active'));
      e.currentTarget.classList.add('active');
      renderView(e.currentTarget.dataset.view);
    });
  });
}

function renderView(viewName) {
  _activeTab = viewName;
  const elRoot = _modal.querySelector('#oracle-app');
  if (!oracleData) return;
  
  elRoot.innerHTML = ''; // Clear
  
  switch(viewName) {
    case 'dashboard':
      elRoot.innerHTML = renderDashboard();
      drawChart();
      break;
    case 'chart':
      elRoot.innerHTML = renderFullChart();
      drawChart(true);
      break;
    case 'transits':
      elRoot.innerHTML = renderTransits();
      break;
    case 'manifest':
      elRoot.innerHTML = renderList('Manifestations', oracleData.manifestations || []);
      break;
    case 'signs':
      elRoot.innerHTML = renderList('Synchronicities', oracleData.synchronicities || []);
      break;
    default:
      elRoot.innerHTML = renderDashboard();
  }
}

function renderDashboard() {
  const p = oracleData.birth_profile || {};
  return \`
    <div class="strnos-header">
      <h2>Cosmic Dashboard</h2>
      <div class="strnos-date-badge">
        \${new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
      </div>
    </div>
    
    <div class="strnos-grid">
      <!-- Insights Column -->
      <div class="strnos-panel">
        <h3>Celestial Insights</h3>
        <div class="strnos-insight-list">
          <div class="strnos-insight-item">
            <div class="strnos-insight-icon">☉</div>
            <div class="strnos-insight-content">
              <h4>Sun Sign</h4>
              <p>\${p.sun_sign || 'Unknown'} — Core identity, ego, and life path focus.</p>
            </div>
          </div>
          <div class="strnos-insight-item">
            <div class="strnos-insight-icon">☽</div>
            <div class="strnos-insight-content">
              <h4>Moon Sign</h4>
              <p>\${p.moon_sign || 'Unknown'} — Emotional landscape, intuition, and inner world.</p>
            </div>
          </div>
          <div class="strnos-insight-item">
            <div class="strnos-insight-icon">↑</div>
            <div class="strnos-insight-content">
              <h4>Ascendant</h4>
              <p>\${p.ascendant_sign || 'Unknown'} — The mask you wear, how the world perceives you.</p>
            </div>
          </div>
        </div>
      </div>
      
      <!-- Chart Column -->
      <div class="strnos-panel">
        <h3>Natal Geometry</h3>
        <div class="strnos-chart-container">
          <canvas id="strnos-chart-canvas"></canvas>
          <div class="strnos-chart-overlay"></div>
        </div>
        <p style="text-align:center; color:var(--strnos-text-muted); font-size:12px; margin-top:24px;">
          Calculated via Swiss Ephemeris
        </p>
      </div>
    </div>
  \`;
}

function renderFullChart() {
  return \`
    <div class="strnos-header">
      <h2>Natal Chart Visualization</h2>
    </div>
    <div class="strnos-panel" style="display:flex; justify-content:center; align-items:center; min-height: 500px;">
        <div class="strnos-chart-container" style="width: 80%; max-width: 600px;">
          <canvas id="strnos-chart-canvas"></canvas>
          <div class="strnos-chart-overlay"></div>
        </div>
    </div>
  \`;
}

function renderTransits() {
  return \`
    <div class="strnos-header">
      <h2>Current Transits</h2>
    </div>
    <div class="strnos-panel">
      <h3>Real-time Planetary Aspects</h3>
      <p style="color:var(--strnos-text-muted)">The cosmos are currently aligning to bring you specific energetic frequencies. Check back later as we connect to the real-time Swiss Ephemeris data stream.</p>
    </div>
  \`;
}

function renderList(title, items) {
  const listHtml = items.length === 0 
    ? \`<p style="color:var(--strnos-text-muted); text-align:center; padding: 40px 0;">No entries found. The universe awaits your input.</p>\`
    : \`<div class="strnos-insight-list">\` + items.map(i => \`
        <div class="strnos-insight-item">
          <div class="strnos-insight-icon">★</div>
          <div class="strnos-insight-content">
            <h4>\${i.date ? new Date(i.date).toLocaleDateString() : 'Entry'}</h4>
            <p>\${i.content || i.description || i.value || JSON.stringify(i)}</p>
          </div>
        </div>
      \`).join('') + \`</div>\`;

  return \`
    <div class="strnos-header">
      <h2>\${title}</h2>
    </div>
    <div class="strnos-panel">
      \${listHtml}
    </div>
  \`;
}

function drawChart(large = false) {
  const canvas = document.getElementById('strnos-chart-canvas');
  if (!canvas) return;
  
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  
  const cx = rect.width / 2;
  const cy = rect.height / 2;
  const radius = Math.min(cx, cy) - 20;

  ctx.clearRect(0, 0, rect.width, rect.height);

  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(0, 229, 255, 0.3)';
  ctx.lineWidth = 1;
  ctx.stroke();
  
  ctx.beginPath();
  ctx.arc(cx, cy, radius - 15, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(212, 175, 55, 0.15)';
  ctx.lineWidth = 1;
  ctx.stroke();

  for(let i=0; i<12; i++) {
    const angle = (i * Math.PI) / 6;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(angle)*(radius-15), cy + Math.sin(angle)*(radius-15));
    ctx.lineTo(cx + Math.cos(angle)*radius, cy + Math.sin(angle)*radius);
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.5)';
    ctx.stroke();
  }

  const nodes = [];
  const numNodes = 7;
  for(let i=0; i<numNodes; i++) {
    const angle = ((i * 137.5) * Math.PI) / 180; 
    const r = radius * 0.4 + (Math.sin(i) * radius * 0.4);
    nodes.push({ x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r });
  }

  ctx.beginPath();
  nodes.forEach((n, i) => {
    nodes.forEach((n2, j) => {
      if(i < j && (i+j)%3 !== 0) {
        ctx.moveTo(n.x, n.y);
        ctx.lineTo(n2.x, n2.y);
      }
    });
  });
  ctx.strokeStyle = 'rgba(0, 229, 255, 0.15)';
  ctx.lineWidth = 1;
  ctx.stroke();

  nodes.forEach(n => {
    ctx.beginPath();
    ctx.arc(n.x, n.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#d4af37';
    ctx.fill();
  });
}

function init() {
  if (_initialized) return;
  build();
  _initialized = true;
}

async function open(tab = 'dashboard') {
  if (!_initialized) init();
  _modal.hidden = false;
  document.body.classList.add('modal-open');
  
  // Show loader
  const elRoot = _modal.querySelector('#oracle-app');
  elRoot.innerHTML = \`<div class="strnos-loader" id="oracle-loader"><div class="strnos-spinner"></div><p>Aligning the stars...</p></div>\`;
  
  const data = await fetchOracleData();
  if (data) {
    const p = data.birth_profile || {};
    if(p.sun_sign) {
      const sunSignEl = document.getElementById('oracle-user-sun-sign');
      if (sunSignEl) sunSignEl.textContent = \`Sun in \${p.sun_sign}\`;
    }
    renderView(tab);
  } else {
    elRoot.innerHTML = \`<div style="text-align:center; margin-top: 100px; color: #ff5555;">Failed to connect to Oracle database.</div>\`;
  }
}

function close() {
  if (!_modal) return;
  _modal.hidden = true;
  document.body.classList.remove('modal-open');
  window.dispatchEvent(new CustomEvent('strnos:oracle-updated'));
}

window.addEventListener('resize', () => {
  if (_modal && !_modal.hidden) {
    if (_activeTab === 'dashboard' || _activeTab === 'chart') {
      drawChart(_activeTab === 'chart');
    }
  }
});

export { init, open, close };
export default { init, open, close };
