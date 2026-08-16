// static/js/modules/sdui_renderer.js
/**
 * Server-Driven UI (SDUI) Dynamic Component Renderer for YVES.
 * Renders feeds, metric cards, SVG charts, data tables, and forms driven entirely by backend schemas.
 */

const SDUI = {
  activeTab: null,
  pollInterval: null,

  async init() {
    console.log('[SDUI] Initializing dynamic UI engine...');
    await this.syncToolbar();
    this.startPolling();
    this.bindPullToRefresh();
  },

  startPolling() {
    if (this.pollInterval) clearInterval(this.pollInterval);
    // Poll every 30 seconds for dynamic tools/widgets updates
    this.pollInterval = setInterval(() => this.syncToolbar(), 30000);
  },

  async syncToolbar() {
    try {
      const res = await fetch('/api/ui/toolbar');
      if (!res.ok) return;
      const data = await res.json();
      this.renderSidebarTools(data.items || []);
    } catch (e) {
      console.debug('[SDUI] Toolbar sync notice:', e);
    }
  },

  renderSidebarTools(items) {
    // Remove the legacy bottom section if it was previously created
    const oldSection = document.getElementById('sidebar-dynamic-section');
    if (oldSection) oldSection.remove();

    // Update the first-class Tool Creator badge in the Tools sidebar
    const badge = document.getElementById('tool-creator-badge');
    if (badge) {
      badge.textContent = String(items.length || 0);
      badge.style.display = items.length > 0 ? 'inline-block' : 'none';
    }
  },

  async openTab(toolId) {
    this.activeTab = toolId;
    let container = document.getElementById('sdui-view-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'sdui-view-container';
      container.className = 'sdui-view-overlay modal-overlay';
      document.body.appendChild(container);
    }

    container.innerHTML = `
      <div class="sdui-modal-card">
        <div class="sdui-header">
          <div class="sdui-header-title">
            <h2 id="sdui-modal-title">Loading Tool...</h2>
            <span class="sdui-badge" id="sdui-modal-tag">SDUI</span>
          </div>
          <div class="sdui-header-actions">
            <button class="sdui-btn sdui-btn-danger" id="sdui-delete-btn" title="Disable Tool">🗑️</button>
            <button class="sdui-btn sdui-close-btn" id="sdui-modal-close">✕</button>
          </div>
        </div>
        <div class="sdui-body" id="sdui-modal-body">
          <div class="sdui-loading-spinner">Loading dynamic components...</div>
        </div>
      </div>
    `;

    container.style.display = 'flex';
    document.getElementById('sdui-modal-close').addEventListener('click', () => {
      container.style.display = 'none';
    });

    document.getElementById('sdui-delete-btn').addEventListener('click', async () => {
      if (confirm(`Disable dynamic tool '${toolId}'?`)) {
        await fetch(`/api/ui/tool/${toolId}`, { method: 'DELETE' });
        container.style.display = 'none';
        await this.syncToolbar();
      }
    });

    try {
      const res = await fetch(`/api/ui/tab/${toolId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const schema = await res.json();
      this.renderTabSchema(schema);
    } catch (e) {
      document.getElementById('sdui-modal-body').innerHTML = `
        <div class="sdui-error">Failed to load dynamic tab: ${this.escapeHtml(e.message)}</div>
      `;
    }
  },

  renderTabSchema(schema) {
    const titleEl = document.getElementById('sdui-modal-title');
    const bodyEl = document.getElementById('sdui-modal-body');
    if (titleEl) titleEl.textContent = schema.title || schema.name;
    if (!bodyEl) return;

    bodyEl.innerHTML = '';
    if (schema.description) {
      const desc = document.createElement('p');
      desc.className = 'sdui-description';
      desc.textContent = schema.description;
      bodyEl.appendChild(desc);
    }

    const grid = document.createElement('div');
    grid.className = 'sdui-grid';

    (schema.components || []).forEach(comp => {
      let card;
      if (comp.type === 'feed') {
        card = this.renderFeedCard(comp);
      } else if (comp.type === 'metric_card') {
        card = this.renderMetricCard(comp);
      } else if (comp.type === 'chart') {
        card = this.renderChartWidget(comp);
      } else if (comp.type === 'table') {
        card = this.renderDataTable(comp);
      } else {
        card = this.renderFormWidget(comp, schema.name);
      }
      grid.appendChild(card);
    });

    bodyEl.appendChild(grid);
  },

  renderFeedCard(comp) {
    const card = document.createElement('div');
    card.className = 'sdui-card sdui-feed-card';
    card.innerHTML = `
      <div class="sdui-card-header">
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Feed')}</span>
        <span class="sdui-live-dot"></span>
      </div>
      <div class="sdui-feed-list">
        ${(comp.config?.items || [
          { title: 'Feed active', time: 'Just now', desc: 'Awaiting updates...' }
        ]).map(item => `
          <div class="sdui-feed-item">
            <div class="sdui-feed-meta">
              <strong>${this.escapeHtml(item.title)}</strong>
              <small>${this.escapeHtml(item.time || '')}</small>
            </div>
            <p>${this.escapeHtml(item.desc || '')}</p>
          </div>
        `).join('')}
      </div>
    `;
    return card;
  },

  renderMetricCard(comp) {
    const card = document.createElement('div');
    card.className = 'sdui-card sdui-metric-card';
    const val = comp.config?.value !== undefined ? comp.config.value : '—';
    const sub = comp.config?.subtitle || 'Active Metric';
    card.innerHTML = `
      <div class="sdui-card-header">
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Metric')}</span>
        <span class="sdui-icon">${this.escapeHtml(comp.icon || '📊')}</span>
      </div>
      <div class="sdui-metric-val">${this.escapeHtml(String(val))}</div>
      <div class="sdui-metric-sub">${this.escapeHtml(sub)}</div>
    `;
    return card;
  },

  renderChartWidget(comp) {
    const card = document.createElement('div');
    card.className = 'sdui-card sdui-chart-card';
    const points = comp.config?.points || [10, 25, 18, 42, 35, 60];
    const maxVal = Math.max(...points, 1);
    const svgPoints = points.map((p, i) => `${(i / (points.length - 1)) * 260 + 20},${100 - (p / maxVal) * 80}`).join(' ');

    card.innerHTML = `
      <div class="sdui-card-header">
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Trend Chart')}</span>
      </div>
      <div class="sdui-chart-wrap">
        <svg viewBox="0 0 300 120" class="sdui-svg-chart">
          <polyline fill="none" stroke="var(--brand-color, #c1122f)" stroke-width="3" stroke-linecap="round" points="${svgPoints}" />
          ${points.map((p, i) => `
            <circle cx="${(i / (points.length - 1)) * 260 + 20}" cy="${100 - (p / maxVal) * 80}" r="4" fill="#fff" stroke="var(--brand-color, #c1122f)" stroke-width="2" />
          `).join('')}
        </svg>
      </div>
    `;
    return card;
  },

  renderDataTable(comp) {
    const card = document.createElement('div');
    card.className = 'sdui-card sdui-table-card';
    const cols = comp.config?.columns || ['Key', 'Value'];
    const rows = comp.config?.rows || [['Status', 'Ready'], ['Engine', 'SDUI v1']];

    card.innerHTML = `
      <div class="sdui-card-header">
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Data Table')}</span>
      </div>
      <div class="sdui-table-wrap">
        <table class="sdui-table">
          <thead>
            <tr>${cols.map(c => `<th>${this.escapeHtml(c)}</th>`).join('')}</tr>
          </thead>
          <tbody>
            ${rows.map(r => `<tr>${r.map(cell => `<td>${this.escapeHtml(String(cell))}</td>`).join('')}</tr>`).join('')}
          </tbody>
        </table>
      </div>
    `;
    return card;
  },

  renderFormWidget(comp, toolName) {
    const card = document.createElement('div');
    card.className = 'sdui-card sdui-form-card';
    card.innerHTML = `
      <div class="sdui-card-header">
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Execute Tool')}</span>
      </div>
      <form class="sdui-form" id="sdui-form-${this.escapeHtml(toolName)}">
        <div class="sdui-form-group">
          <label>Parameters (JSON or Input):</label>
          <input type="text" name="input" class="sdui-input" placeholder="e.g. 10 or {'n': 10}" />
        </div>
        <button type="submit" class="sdui-btn sdui-btn-primary">Execute</button>
        <div class="sdui-form-output" style="display:none;"></div>
      </form>
    `;

    const form = card.querySelector('form');
    const outDiv = card.querySelector('.sdui-form-output');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const val = form.input.value.trim();
      let payload = { params: {} };
      if (val.startsWith('{') && val.endsWith('}')) {
        try { payload.params = JSON.parse(val); } catch { payload.params = { input: val }; }
      } else if (val) {
        payload.params = { input: val, n: Number(val) || val };
      }

      outDiv.style.display = 'block';
      outDiv.innerHTML = '<em>Running...</em>';
      try {
        const res = await fetch(`/api/ui/execute-tool/${toolName}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const resJson = await res.json();
        outDiv.innerHTML = `<strong>Result:</strong> <pre>${JSON.stringify(resJson.result ?? resJson, null, 2)}</pre>`;
      } catch (err) {
        outDiv.innerHTML = `<span class="sdui-error">Error: ${this.escapeHtml(err.message)}</span>`;
      }
    });

    return card;
  },

  bindPullToRefresh() {
    let startY = 0;
    document.addEventListener('touchstart', e => {
      if (window.scrollY === 0) startY = e.touches[0].pageY;
    }, { passive: true });

    document.addEventListener('touchend', e => {
      const endY = e.changedTouches[0].pageY;
      if (window.scrollY === 0 && endY - startY > 120) {
        console.log('[SDUI] Pull-to-refresh triggered');
        this.syncToolbar();
      }
    }, { passive: true });
  },

  escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  },
};

export default SDUI;
