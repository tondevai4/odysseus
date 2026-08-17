// static/js/modules/sdui_renderer.js
/**
 * Server-Driven UI (SDUI) Dynamic Component Renderer for YVES.
 * Autonomously registers dynamic tools into the native Sidebar and Command Center grid,
 * and renders feeds, metric cards, SVG trend charts, data tables, and interactive forms.
 */

const SDUI = {
  activeTab: null,
  pollInterval: null,

  async init() {
    console.log('[SDUI] Initializing dynamic native UI engine...');
    await this.syncToolbar();
    this.startPolling();
    this.bindPullToRefresh();
  },

  startPolling() {
    if (this.pollInterval) clearInterval(this.pollInterval);
    // Poll every 20 seconds for dynamic tools/widgets updates
    this.pollInterval = setInterval(() => this.syncToolbar(), 20000);
  },

  async syncToolbar() {
    try {
      const res = await fetch('/api/ui/toolbar');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.items || [];
      this.renderSidebarTools(items);
      this.renderCommandCenterWidgets(items);
    } catch (e) {
      console.debug('[SDUI] Toolbar sync notice:', e);
    }
  },

  renderSidebarTools(items) {
    // Clean up any legacy bottom section
    const oldSection = document.getElementById('sidebar-dynamic-section');
    if (oldSection) oldSection.remove();

    const toolsSection = document.getElementById('tools-section');
    if (!toolsSection) return;

    // Remove previously injected dynamic tool items
    toolsSection.querySelectorAll('.sdui-dynamic-tool-item').forEach(el => el.remove());

    if (!items || items.length === 0) return;

    items.forEach(item => {
      const toolItem = document.createElement('div');
      toolItem.className = 'list-item sdui-dynamic-tool-item';
      toolItem.setAttribute('data-tool-id', item.tool_id || item.tool_name);
      toolItem.setAttribute('title', item.title || item.tool_name);
      toolItem.style.borderLeft = '2px solid var(--brand-color, #c1122f)';
      toolItem.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.7;color:var(--brand-color,#c1122f);">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
        </svg>
        <span class="grow" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500;">${this.escapeHtml(item.title || item.tool_name)}</span>
        <span class="badge" style="font-size:9px;background:rgba(255,255,255,0.06);padding:1px 5px;border-radius:4px;opacity:0.6;">dynamic</span>
      `;
      toolItem.addEventListener('click', () => {
        this.openTab(item.tool_id || item.tool_name);
      });
      toolsSection.appendChild(toolItem);
    });
  },

  renderCommandCenterWidgets(items) {
    const grid = document.querySelector('.command-center-grid');
    if (!grid) return;

    // Remove previously injected dynamic cards
    grid.querySelectorAll('.sdui-dynamic-command-card').forEach(el => el.remove());

    if (!items || items.length === 0) return;

    items.forEach(item => {
      const card = document.createElement('article');
      card.className = 'command-card command-card-dynamic sdui-dynamic-command-card';
      card.setAttribute('data-tool-id', item.tool_id || item.tool_name);
      card.setAttribute('aria-labelledby', `command-card-${item.tool_id || item.tool_name}-title`);
      card.innerHTML = `
        <div class="command-card-topline">
          <span style="color:var(--brand-color,#c1122f);font-weight:700;">DYNAMIC</span>
          <span>${this.escapeHtml(item.widget_type || 'Feed')}</span>
        </div>
        <h3 id="command-card-${this.escapeHtml(item.tool_id || item.tool_name)}-title">${this.escapeHtml(item.title || item.tool_name)}</h3>
        <p>${this.escapeHtml(item.description || 'Autonomous dynamic tool and feed synthesized by YVES.')}</p>
        <button type="button" class="command-card-action">
          Open ${this.escapeHtml(item.title || item.tool_name)} <span aria-hidden="true">&rarr;</span>
        </button>
      `;
      card.querySelector('.command-card-action')?.addEventListener('click', () => {
        this.openTab(item.tool_id || item.tool_name);
      });
      grid.appendChild(card);
    });
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
            <span class="sdui-badge" id="sdui-modal-tag">DYNAMIC</span>
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
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Live Feed')}</span>
        <span class="sdui-live-dot"></span>
      </div>
      <div class="sdui-feed-list">
        ${(comp.config?.items || [
          { title: 'Feed active', time: 'Just now', desc: 'Live monitoring active.' }
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
    const points = comp.config?.points || [10, 25, 18, 40, 32, 55, 48];
    const maxVal = Math.max(...points, 1);
    const svgPoints = points.map((p, idx) => {
      const x = (idx / (points.length - 1)) * 280 + 10;
      const y = 90 - (p / maxVal) * 70;
      return `${x},${y}`;
    }).join(' ');

    card.innerHTML = `
      <div class="sdui-card-header">
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Trend Chart')}</span>
        <span class="sdui-badge">Live</span>
      </div>
      <div class="sdui-chart-wrap">
        <svg viewBox="0 0 300 100" class="sdui-svg-chart">
          <polyline fill="none" stroke="var(--brand-color, #c1122f)" stroke-width="3" points="${svgPoints}" />
          ${points.map((p, idx) => {
            const x = (idx / (points.length - 1)) * 280 + 10;
            const y = 90 - (p / maxVal) * 70;
            return `<circle cx="${x}" cy="${y}" r="4" fill="#ffffff" />`;
          }).join('')}
        </svg>
      </div>
    `;
    return card;
  },

  renderDataTable(comp) {
    const card = document.createElement('div');
    card.className = 'sdui-card sdui-table-card';
    const columns = comp.config?.columns || ['Column 1', 'Column 2', 'Status'];
    const rows = comp.config?.rows || [
      ['Sample item', 'Active', 'OK'],
      ['Secondary item', 'Synced', 'OK']
    ];

    card.innerHTML = `
      <div class="sdui-card-header">
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Data Table')}</span>
      </div>
      <div class="sdui-table-wrap">
        <table class="sdui-table">
          <thead>
            <tr>${columns.map(c => `<th>${this.escapeHtml(c)}</th>`).join('')}</tr>
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
    const inputs = comp.config?.inputs || [{ name: 'input', label: 'Input Value', type: 'text', placeholder: 'Enter parameters...' }];

    card.innerHTML = `
      <div class="sdui-card-header">
        <span class="sdui-card-title">${this.escapeHtml(comp.title || 'Execute Tool')}</span>
      </div>
      <form class="sdui-form">
        ${inputs.map(inp => `
          <div class="sdui-form-group">
            <label class="sdui-label">${this.escapeHtml(inp.label || inp.name)}</label>
            <input type="${this.escapeHtml(inp.type || 'text')}" name="${this.escapeHtml(inp.name)}" class="sdui-input" placeholder="${this.escapeHtml(inp.placeholder || '')}" />
          </div>
        `).join('')}
        <button type="submit" class="sdui-submit-btn">Run Tool</button>
        <div class="sdui-form-output" style="display:none;"></div>
      </form>
    `;

    const form = card.querySelector('form');
    const out = card.querySelector('.sdui-form-output');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const formData = new FormData(form);
      const payload = { params: {} };
      formData.forEach((val, key) => { payload.params[key] = val; });

      out.style.display = 'block';
      out.textContent = 'Executing...';

      try {
        const res = await fetch(`/api/ui/execute-tool/${toolName}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        out.textContent = JSON.stringify(data.result ?? data, null, 2);
      } catch (err) {
        out.textContent = `Error: ${err.message}`;
      }
    });

    return card;
  },

  bindPullToRefresh() {
    let startY = 0;
    document.addEventListener('touchstart', (e) => {
      if (window.scrollY === 0) {
        startY = e.touches[0].pageY;
      }
    }, { passive: true });

    document.addEventListener('touchend', (e) => {
      const endY = e.changedTouches[0].pageY;
      if (window.scrollY === 0 && endY - startY > 120) {
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
  }
};

export default SDUI;
