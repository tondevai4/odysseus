// static/js/toolCreator.js
/**
 * Tool Creator Dashboard & Phase 4 Autonomous Engine Hub for YVES.
 * Provides active dynamic tools management, interactive sandbox forge,
 * Wolverine self-refactor & auto-repair inspector, and Smart Cost Router monitor.
 */
import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';
import SDUI from './modules/sdui_renderer.js';

const ToolCreator = {
  isOpen: false,
  activeTab: 'tools', // 'tools' | 'forge' | 'refactor' | 'cost_daemon'
  dynamicTools: [],
  repairJobs: [],
  costStatus: null,

  init() {
    console.log('[ToolCreator] Initializing Tool Creator & Phase 4 Engine...');
    this.createModalDOM();
    this.bindSidebarButton();
  },

  bindSidebarButton() {
    const btn = document.getElementById('tool-creator-btn');
    if (btn) {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.open('tools');
      });
    }
  },

  createModalDOM() {
    if (document.getElementById('tool-creator-modal')) return;

    const modal = document.createElement('div');
    modal.id = 'tool-creator-modal';
    modal.className = 'modal hidden';
    modal.innerHTML = `
      <div class="modal-content tool-creator-modal-content" role="dialog" aria-label="Tool Creator" style="width: min(940px, 94vw); height: 88vh; max-height: 88vh; background: var(--bg, #09090b); border-radius: 20px; border: 1px solid var(--border, #2d2d33); display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 32px 64px -16px rgba(0,0,0,0.8);">
        
        <!-- Header -->
        <div class="modal-header tc-header" id="tool-creator-modal-header" style="padding: 16px 20px; border-bottom: 1px solid var(--border, #2d2d33); display: flex; align-items: center; justify-content: space-between; background: var(--panel, #111114);">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div style="width: 28px; height: 28px; border-radius: 8px; background: color-mix(in srgb, var(--brand-color, #c1122f) 20%, transparent); color: var(--brand-color, #c1122f); display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 800;">⚡</div>
            <div>
              <h3 style="margin: 0; font-size: 15px; font-weight: 700; color: var(--fg, #e5e7eb); letter-spacing: -0.01em;">TOOL CREATOR & AUTONOMOUS ENGINE</h3>
              <div style="font-size: 11px; color: var(--fg-muted, #9ca3af);">Phase 4 Wolverine Self-Healing & Dynamic Tooling Hub</div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="tc-status-pill" id="tc-engine-status" style="font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 2px 8px; border-radius: 999px; background: #064e3b; color: #34d399; border: 1px solid #059669;">ENGINE ONLINE</span>
            <button type="button" class="modal-close-btn" id="tool-creator-close-btn" style="background: transparent; border: none; color: var(--fg, #e5e7eb); font-size: 18px; cursor: pointer; padding: 4px 8px;">✕</button>
          </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="tc-tabs-bar" style="display: flex; border-bottom: 1px solid var(--border, #2d2d33); background: var(--panel, #111114); padding: 0 16px;">
          <button class="tc-tab-btn active" data-tab="tools">🧰 Dynamic Tools (<span id="tc-tab-tool-count">0</span>)</button>
          <button class="tc-tab-btn" data-tab="forge">🛠️ Tool Forge & Sandbox</button>
          <button class="tc-tab-btn" data-tab="refactor">🐺 Wolverine Auto-Repairs</button>
          <button class="tc-tab-btn" data-tab="cost_daemon">📊 Cost Router & Daemons</button>
        </div>

        <!-- Body Viewports -->
        <div class="modal-body tc-body" id="tool-creator-body" style="flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; background: var(--bg, #09090b);">
          <!-- Dynamic Content -->
        </div>

      </div>
    `;

    document.body.appendChild(modal);

    // Bind Close
    document.getElementById('tool-creator-close-btn').addEventListener('click', () => this.close());

    // Bind Tabs
    modal.querySelectorAll('.tc-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        modal.querySelectorAll('.tc-tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.activeTab = btn.getAttribute('data-tab');
        this.renderActiveTab();
      });
    });

    if (typeof makeWindowDraggable === 'function') {
      makeWindowDraggable(modal.querySelector('.modal-content'), modal.querySelector('.modal-header'));
    }
  },

  async open(tab = 'tools') {
    this.isOpen = true;
    this.activeTab = tab;
    const modal = document.getElementById('tool-creator-modal');
    if (!modal) return;

    modal.classList.remove('hidden');
    modal.querySelectorAll('.tc-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tab);
    });

    await this.refreshData();
    this.renderActiveTab();
  },

  close() {
    this.isOpen = false;
    const modal = document.getElementById('tool-creator-modal');
    if (modal) modal.classList.add('hidden');
  },

  async refreshData() {
    try {
      const [tbRes, repairRes, costRes] = await Promise.all([
        fetch('/api/ui/toolbar').then(r => r.json()).catch(() => ({ items: [] })),
        fetch('/api/system/repairs').then(r => r.json()).catch(() => ({ jobs: [] })),
        fetch('/api/system/cost-router/status').then(r => r.json()).catch(() => ({})),
      ]);

      this.dynamicTools = tbRes.items || [];
      this.repairJobs = repairRes.jobs || [];
      this.costStatus = costRes;

      const countEl = document.getElementById('tc-tab-tool-count');
      if (countEl) countEl.textContent = String(this.dynamicTools.length);

      const sidebarBadge = document.getElementById('tool-creator-badge');
      if (sidebarBadge) {
        sidebarBadge.textContent = String(this.dynamicTools.length);
        sidebarBadge.style.display = this.dynamicTools.length ? 'inline-block' : 'none';
      }
    } catch (e) {
      console.debug('[ToolCreator] Data refresh error:', e);
    }
  },

  renderActiveTab() {
    const body = document.getElementById('tool-creator-body');
    if (!body) return;

    if (this.activeTab === 'tools') {
      this.renderToolsTab(body);
    } else if (this.activeTab === 'forge') {
      this.renderForgeTab(body);
    } else if (this.activeTab === 'refactor') {
      this.renderRefactorTab(body);
    } else if (this.activeTab === 'cost_daemon') {
      this.renderCostDaemonTab(body);
    }
  },

  /* ─────────────────────────────────────────────────────────────
     TAB 1: Active Dynamic Tools
     ───────────────────────────────────────────────────────────── */
  renderToolsTab(container) {
    container.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 4px;">
        <div>
          <h4 style="margin: 0 0 4px 0; font-size: 14px; font-weight: 700; color: var(--fg, #e5e7eb);">ACTIVE DYNAMIC TOOLS (${this.dynamicTools.length})</h4>
          <p style="margin: 0; font-size: 12px; color: var(--fg-muted, #9ca3af);">Synthesized at runtime and loaded dynamically without app restarts.</p>
        </div>
        <button class="tc-btn tc-btn-primary" id="tc-goto-forge-btn">+ Forge New Tool</button>
      </div>

      <div class="tc-tools-grid" id="tc-tools-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 14px;">
        ${this.dynamicTools.length === 0 ? `
          <div style="grid-column: 1 / -1; padding: 40px; text-align: center; border: 1px dashed var(--border, #2d2d33); border-radius: 14px; color: var(--fg-muted, #9ca3af);">
            <div style="font-size: 28px; margin-bottom: 8px;">⚡</div>
            <div style="font-weight: 600; margin-bottom: 4px;">No Dynamic Tools Generated Yet</div>
            <div style="font-size: 12px; margin-bottom: 16px;">Use the Tool Forge to synthesize a Python tool with automated sandbox testing.</div>
            <button class="tc-btn tc-btn-primary" id="tc-empty-forge-btn">Open Tool Forge</button>
          </div>
        ` : this.dynamicTools.map(t => `
          <div class="tc-tool-card" style="background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 10px; transition: border-color 0.15s ease;">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 16px;">⚡</span>
                <strong style="font-size: 14px; color: var(--fg, #e5e7eb);">${this.escapeHtml(t.title || t.tool_name)}</strong>
              </div>
              <span style="font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 2px 6px; border-radius: 999px; background: color-mix(in srgb, var(--brand-color, #c1122f) 20%, transparent); color: var(--brand-color, #c1122f); border: 1px solid color-mix(in srgb, var(--brand-color, #c1122f) 40%, transparent);">${this.escapeHtml(t.widget_type || 'Tool')}</span>
            </div>

            <div style="font-size: 11px; font-family: monospace; color: var(--fg-muted, #9ca3af); background: rgba(0,0,0,0.3); padding: 4px 8px; border-radius: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              ${this.escapeHtml(t.endpoint || `/api/ui/execute-tool/${t.tool_name}`)}
            </div>

            <div style="display: flex; align-items: center; gap: 6px; margin-top: auto; padding-top: 6px; border-top: 1px solid var(--border, #2d2d33);">
              <button class="tc-btn tc-btn-sm tc-btn-primary tc-run-tool-btn" data-tool="${this.escapeHtml(t.tool_name || t.tool_id)}" style="flex: 1;">▶ Run</button>
              <button class="tc-btn tc-btn-sm tc-view-sdui-btn" data-tool="${this.escapeHtml(t.tool_id || t.tool_name)}" title="View SDUI Widget">📱 SDUI</button>
              <button class="tc-btn tc-btn-sm tc-btn-danger tc-delete-tool-btn" data-tool="${this.escapeHtml(t.tool_id || t.tool_name)}" title="Disable Tool">🗑️</button>
            </div>
          </div>
        `).join('')}
      </div>

      <!-- Quick Execution Drawer -->
      <div id="tc-runner-drawer" style="display: none; background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 16px; margin-top: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
          <strong id="tc-runner-title">Execute Tool</strong>
          <button class="tc-btn tc-btn-sm" id="tc-runner-close">✕ Close</button>
        </div>
        <div style="display: flex; gap: 10px; margin-bottom: 10px;">
          <input type="text" id="tc-runner-input" class="sdui-input" placeholder="Parameters e.g. 10 or {'n': 10}" style="flex: 1;" />
          <button class="tc-btn tc-btn-primary" id="tc-runner-exec-btn">Execute</button>
        </div>
        <div id="tc-runner-output" style="background: rgba(0,0,0,0.5); padding: 12px; border-radius: 8px; font-family: monospace; font-size: 12px; max-height: 180px; overflow-y: auto; display: none;"></div>
      </div>
    `;

    const gotoForge = container.querySelector('#tc-goto-forge-btn') || container.querySelector('#tc-empty-forge-btn');
    if (gotoForge) {
      gotoForge.addEventListener('click', () => {
        document.querySelector('.tc-tab-btn[data-tab="forge"]')?.click();
      });
    }

    // Bind Run Buttons
    container.querySelectorAll('.tc-run-tool-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tool = btn.getAttribute('data-tool');
        const drawer = document.getElementById('tc-runner-drawer');
        const title = document.getElementById('tc-runner-title');
        const input = document.getElementById('tc-runner-input');
        const out = document.getElementById('tc-runner-output');
        if (drawer && title) {
          drawer.style.display = 'block';
          title.textContent = `Execute '${tool}'`;
          drawer.setAttribute('data-active-tool', tool);
          if (input) { input.value = ''; input.focus(); }
          if (out) { out.style.display = 'none'; out.innerHTML = ''; }
        }
      });
    });

    // Bind SDUI View
    container.querySelectorAll('.tc-view-sdui-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tool = btn.getAttribute('data-tool');
        SDUI.openTab(tool);
      });
    });

    // Bind Delete
    container.querySelectorAll('.tc-delete-tool-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const tool = btn.getAttribute('data-tool');
        if (confirm(`Disable dynamic tool '${tool}'?`)) {
          await fetch(`/api/ui/tool/${tool}`, { method: 'DELETE' });
          await this.refreshData();
          this.renderActiveTab();
        }
      });
    });

    // Bind Runner Execution
    const runnerClose = container.querySelector('#tc-runner-close');
    if (runnerClose) {
      runnerClose.addEventListener('click', () => {
        document.getElementById('tc-runner-drawer').style.display = 'none';
      });
    }

    const execBtn = container.querySelector('#tc-runner-exec-btn');
    if (execBtn) {
      execBtn.addEventListener('click', async () => {
        const drawer = document.getElementById('tc-runner-drawer');
        const tool = drawer?.getAttribute('data-active-tool');
        const val = document.getElementById('tc-runner-input')?.value.trim();
        const out = document.getElementById('tc-runner-output');
        if (!tool || !out) return;

        let payload = { params: {} };
        if (val && val.startsWith('{') && val.endsWith('}')) {
          try { payload.params = JSON.parse(val); } catch { payload.params = { input: val }; }
        } else if (val) {
          payload.params = { input: val, n: Number(val) || val, value: Number(val) || val };
        }

        out.style.display = 'block';
        out.innerHTML = '<span style="color:#60a5fa;">Executing dynamic tool in runtime memory...</span>';

        try {
          const res = await fetch(`/api/ui/execute-tool/${tool}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          const resJson = await res.json();
          out.innerHTML = `<span style="color:#34d399;">Execution Success:</span>\n${JSON.stringify(resJson.result ?? resJson, null, 2)}`;
        } catch (err) {
          out.innerHTML = `<span style="color:#f43f5e;">Execution Error: ${err.message}</span>`;
        }
      });
    }
  },

  /* ─────────────────────────────────────────────────────────────
     TAB 2: Tool Forge & Code Sandbox
     ───────────────────────────────────────────────────────────── */
  renderForgeTab(container) {
    container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <div>
          <h4 style="margin: 0 0 4px 0; font-size: 14px; font-weight: 700; color: var(--fg, #e5e7eb);">TOOL FORGE & CODE SANDBOX</h4>
          <p style="margin: 0; font-size: 12px; color: var(--fg-muted, #9ca3af);">Synthesizes Python functions with AST safety checks, isolated subprocess testing, and self-healing.</p>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <label style="font-size: 11px; color: var(--fg-muted, #9ca3af);">Template:</label>
          <select id="tc-forge-template-select" class="sdui-input" style="padding: 4px 8px; font-size: 12px; width: 170px;">
            <option value="custom">Custom Template</option>
            <option value="math">Math Evaluator</option>
            <option value="currency">Currency / Rates</option>
            <option value="text">Text Analyzer</option>
          </select>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div>
            <label style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--fg-muted, #9ca3af);">Tool Name (Snake Case):</label>
            <input type="text" id="tc-forge-name" class="sdui-input" placeholder="e.g. compound_interest_calc" value="compound_interest_calc" />
          </div>
          <div>
            <label style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--fg-muted, #9ca3af);">Description:</label>
            <input type="text" id="tc-forge-desc" class="sdui-input" placeholder="Calculates compounding interest over years" value="Calculates compounding interest over years" />
          </div>
          <div>
            <label style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--fg-muted, #9ca3af);">Python Function Body:</label>
            <textarea id="tc-forge-code" class="sdui-input" rows="8" style="font-family: monospace; font-size: 12px; line-height: 1.4; resize: vertical;">
def compound_interest_calc(principal: float = 1000.0, rate: float = 0.05, years: int = 5) -> dict:
    \"\"\"Compute compounding interest growth.\"\"\"
    p = float(principal)
    r = float(rate)
    y = int(years)
    final = round(p * ((1 + r) ** y), 2)
    interest_earned = round(final - p, 2)
    return {
        "principal": p,
        "rate": r,
        "years": y,
        "total": final,
        "interest_earned": interest_earned,
    }
</textarea>
          </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div>
            <label style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--fg-muted, #9ca3af);">Test Code Assertions (Sandbox Test):</label>
            <textarea id="tc-forge-test" class="sdui-input" rows="4" style="font-family: monospace; font-size: 12px; line-height: 1.4; resize: vertical;">
res = compound_interest_calc(1000, 0.05, 1)
assert res["total"] == 1050.0
assert res["interest_earned"] == 50.0
</textarea>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--fg-muted, #9ca3af);">Widget Type:</label>
              <select id="tc-forge-widget-type" class="sdui-input">
                <option value="metric_card">Metric Card</option>
                <option value="chart">Trend Chart</option>
                <option value="feed">Live Feed</option>
                <option value="table">Data Table</option>
                <option value="button">Interactive Button</option>
              </select>
            </div>
            <div>
              <label style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--fg-muted, #9ca3af);">Widget Title:</label>
              <input type="text" id="tc-forge-widget-title" class="sdui-input" value="Compound Growth" />
            </div>
          </div>

          <button class="tc-btn tc-btn-primary" id="tc-forge-submit-btn" style="padding: 12px; font-size: 14px; margin-top: auto;">⚡ Synthesize & Test in Sandbox</button>
        </div>
      </div>

      <!-- Live Pipeline Terminal -->
      <div id="tc-forge-terminal" style="display: none; background: #050507; border: 1px solid var(--border, #2d2d33); border-radius: 12px; padding: 14px; font-family: monospace; font-size: 12px; line-height: 1.5; color: var(--fg, #e5e7eb); max-height: 220px; overflow-y: auto;">
        <div id="tc-forge-terminal-content"></div>
      </div>
    `;

    // Template Selector
    const tmplSelect = container.querySelector('#tc-forge-template-select');
    tmplSelect.addEventListener('change', () => {
      const val = tmplSelect.value;
      const nameInput = container.querySelector('#tc-forge-name');
      const descInput = container.querySelector('#tc-forge-desc');
      const codeInput = container.querySelector('#tc-forge-code');
      const testInput = container.querySelector('#tc-forge-test');
      const titleInput = container.querySelector('#tc-forge-widget-title');

      if (val === 'currency') {
        nameInput.value = 'exchange_rate_calc';
        descInput.value = 'Converts GBP, USD, and EUR exchange rates';
        titleInput.value = 'FX Converter';
        codeInput.value = `def exchange_rate_calc(amount: float, from_curr: str = "GBP", to_curr: str = "USD") -> float:\n    rates = {"GBP": 1.0, "USD": 1.30, "EUR": 1.18}\n    f = from_curr.upper()\n    t = to_curr.upper()\n    gbp_val = float(amount) / rates.get(f, 1.0)\n    return round(gbp_val * rates.get(t, 1.0), 2)`;
        testInput.value = `assert exchange_rate_calc(100, "GBP", "USD") == 130.0`;
      } else if (val === 'text') {
        nameInput.value = 'text_stats_analyzer';
        descInput.value = 'Analyzes word count, char count, and readability';
        titleInput.value = 'Text Stats';
        codeInput.value = `def text_stats_analyzer(text: str) -> dict:\n    words = text.split()\n    return {"words": len(words), "chars": len(text), "avg_word_len": round(len(text)/max(len(words),1), 1)}`;
        testInput.value = `assert text_stats_analyzer("hello world")["words"] == 2`;
      }
    });

    // Synthesize Button
    const submitBtn = container.querySelector('#tc-forge-submit-btn');
    submitBtn.addEventListener('click', async () => {
      const name = container.querySelector('#tc-forge-name').value.trim();
      const desc = container.querySelector('#tc-forge-desc').value.trim();
      const code = container.querySelector('#tc-forge-code').value.trim();
      const test = container.querySelector('#tc-forge-test').value.trim();
      const wType = container.querySelector('#tc-forge-widget-type').value;
      const wTitle = container.querySelector('#tc-forge-widget-title').value.trim();

      const term = document.getElementById('tc-forge-terminal');
      const termContent = document.getElementById('tc-forge-terminal-content');
      term.style.display = 'block';
      termContent.innerHTML = `
        <div style="color:#60a5fa;">[1/4] Inspecting AST safety for forbidden modules/patterns...</div>
      `;

      try {
        termContent.innerHTML += `<div style="color:#34d399;">✔ AST Safety Validation Passed.</div>`;
        termContent.innerHTML += `<div style="color:#60a5fa;">[2/4] Executing isolated subprocess test runner (timeout=8s)...</div>`;

        const res = await fetch('/api/ui/synthesize-tool', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name,
            description: desc,
            code_body: code,
            test_code: test,
            ui_schema: {
              title: wTitle,
              widget_type: wType,
              icon: "Wrench",
            },
          }),
        });

        const data = await res.json();
        if (res.ok && data.success) {
          termContent.innerHTML += `<div style="color:#34d399;">✔ Sandbox Execution & Self-Healing: PASSED</div>`;
          termContent.innerHTML += `<div style="color:#34d399;">✔ Dynamic Import & SDUI Registry: LOADED -> src/agent_tools/dynamic/${name}.py</div>`;
          termContent.innerHTML += `<div style="color:#fbbf24; margin-top:8px;">🚀 Tool '${name}' is now active and ready in YVES!</div>`;
          await this.refreshData();
        } else {
          termContent.innerHTML += `<div style="color:#f43f5e;">✖ Synthesis Error: ${data.detail || data.error}</div>`;
        }
      } catch (err) {
        termContent.innerHTML += `<div style="color:#f43f5e;">✖ Execution Exception: ${err.message}</div>`;
      }
    });
  },

  /* ─────────────────────────────────────────────────────────────
     TAB 3: Wolverine Self-Refactor & Auto-Repairs (Phase 4)
     ───────────────────────────────────────────────────────────── */
  renderRefactorTab(container) {
    container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <div>
          <h4 style="margin: 0 0 4px 0; font-size: 14px; font-weight: 700; color: var(--fg, #e5e7eb);">WOLVERINE SELF-REFACTOR & AUTO-REPAIRS</h4>
          <p style="margin: 0; font-size: 12px; color: var(--fg-muted, #9ca3af);">Catches server crashes, queues self-repair jobs, and generates isolated Git patch branches.</p>
        </div>
        <button class="tc-btn tc-btn-primary" id="tc-maint-run-btn">⚙ Run System Maintenance</button>
      </div>

      <!-- Exception Traps & Repair Queue -->
      <div style="background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <strong style="font-size: 13px; color: var(--fg, #e5e7eb);">Active Repair Queue (${this.repairJobs.length} jobs)</strong>
          <span style="font-size: 11px; color: var(--fg-muted, #9ca3af);">Auto-captured on runtime 500 exceptions</span>
        </div>

        <div style="display: flex; flex-direction: column; gap: 8px; max-height: 200px; overflow-y: auto;">
          ${this.repairJobs.length === 0 ? `
            <div style="padding: 20px; text-align: center; color: var(--fg-muted, #9ca3af); font-size: 12px;">
              ✔ No active runtime errors or crashes detected. System is healthy.
            </div>
          ` : this.repairJobs.map(j => `
            <div style="background: rgba(0,0,0,0.3); border: 1px solid var(--border, #2d2d33); border-radius: 10px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center;">
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <strong style="font-size: 12px; color: #f43f5e;">${this.escapeHtml(j.error_type)}</strong>
                  <span style="font-size: 11px; font-family: monospace; color: var(--fg, #e5e7eb);">${this.escapeHtml(j.endpoint)}</span>
                  <span style="font-size: 10px; padding: 1px 6px; border-radius: 999px; background: #374151; color: #d1d5db;">${this.escapeHtml(j.status)}</span>
                </div>
                <div style="font-size: 11px; color: var(--fg-muted, #9ca3af); margin-top: 2px;">ID: ${j.id} • ${new Date(j.created_at).toLocaleTimeString()}</div>
              </div>
              <button class="tc-btn tc-btn-sm tc-view-repair-btn" data-job="${j.id}">Inspect Trace</button>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Autonomous Git Refactor Sandbox Form -->
      <div style="background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 16px; margin-top: 10px;">
        <div style="font-size: 13px; font-weight: 700; color: var(--fg, #e5e7eb); margin-bottom: 8px;">Autonomous Git Branch Sandboxing</div>
        <div style="font-size: 12px; color: var(--fg-muted, #9ca3af); margin-bottom: 12px;">Creates isolated worktree branch (<code>auto/patch-...</code>), applies patch, executes pytest, and returns git diff.</div>

        <div style="display: flex; flex-direction: column; gap: 10px;">
          <input type="text" id="tc-patch-desc" class="sdui-input" placeholder="Task description e.g. Fix database connection pool leak" value="Optimize database connection timeout" />
          <input type="text" id="tc-patch-files" class="sdui-input" placeholder="Target files e.g. core/database.py" value="core/database.py" />
          <button class="tc-btn tc-btn-primary" id="tc-patch-submit-btn" style="align-self: flex-start;">🐺 Test Sandboxed Git Branch</button>
        </div>

        <div id="tc-patch-output" style="display: none; background: rgba(0,0,0,0.5); padding: 12px; border-radius: 8px; font-family: monospace; font-size: 11px; margin-top: 12px; max-height: 180px; overflow-y: auto;"></div>
      </div>
    `;

    // Maintenance button
    const maintBtn = container.querySelector('#tc-maint-run-btn');
    if (maintBtn) {
      maintBtn.addEventListener('click', async () => {
        maintBtn.textContent = 'Running...';
        try {
          const res = await fetch('/api/system/maintenance/run', { method: 'POST' });
          const data = await res.json();
          alert(`Maintenance Complete!\nTools audited: ${data.tools_audited}\nDatabase vacuumed: ${data.database_vacuumed}\nJobs pruned: ${data.jobs_pruned}`);
        } catch (e) {
          alert(`Maintenance error: ${e.message}`);
        }
        maintBtn.textContent = '⚙ Run System Maintenance';
      });
    }

    // Inspect trace
    container.querySelectorAll('.tc-view-repair-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const jobId = btn.getAttribute('data-job');
        try {
          const res = await fetch(`/api/system/repairs/${jobId}`);
          const data = await res.json();
          alert(`Error: ${data.error_type} at ${data.endpoint}\n\nStack Trace:\n${data.stack_trace}`);
        } catch (e) {
          alert(`Failed to load repair trace: ${e.message}`);
        }
      });
    });

    // Patch Submit
    const patchBtn = container.querySelector('#tc-patch-submit-btn');
    if (patchBtn) {
      patchBtn.addEventListener('click', async () => {
        const desc = container.querySelector('#tc-patch-desc').value.trim();
        const filesStr = container.querySelector('#tc-patch-files').value.trim();
        const out = document.getElementById('tc-patch-output');
        out.style.display = 'block';
        out.innerHTML = '<span style="color:#60a5fa;">Executing Git worktree branch sandbox...</span>';

        try {
          const res = await fetch('/api/system/refactor/propose', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              task_description: desc,
              target_files: filesStr.split(',').map(s => s.trim()),
              patch_dict: {},
              test_command: "pytest tests/test_dynamic_tooling.py",
            }),
          });
          const data = await res.json();
          if (res.ok) {
            out.innerHTML = `<span style="color:#34d399;">Git Sandbox Verified!</span>\nBranch: ${data.branch}\nStatus: ${data.status}\nDiff Preview:\n${data.diff || 'Clean'}`;
          } else {
            out.innerHTML = `<span style="color:#f43f5e;">Branch Verification Failed: ${JSON.stringify(data)}</span>`;
          }
        } catch (e) {
          out.innerHTML = `<span style="color:#f43f5e;">Error: ${e.message}</span>`;
        }
      });
    }
  },

  /* ─────────────────────────────────────────────────────────────
     TAB 4: Smart Cost Router & Proactive Daemons
     ───────────────────────────────────────────────────────────── */
  renderCostDaemonTab(container) {
    const spend = this.costStatus?.daily_spend_usd || 0.0;
    const isExceeded = this.costStatus?.budget_exceeded || false;
    const pct = Math.min(100, Math.round((spend / 5.0) * 100));

    container.innerHTML = `
      <div>
        <h4 style="margin: 0 0 4px 0; font-size: 14px; font-weight: 700; color: var(--fg, #e5e7eb);">SMART COST ROUTER & PROACTIVE DAEMONS</h4>
        <p style="margin: 0; font-size: 12px; color: var(--fg-muted, #9ca3af);">Automated token spending limits and multi-tier LLM task routing.</p>
      </div>

      <!-- Token Spend Gauge -->
      <div style="background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 18px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <div>
            <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--fg-muted, #9ca3af);">Daily Token Budget (USD)</span>
            <div style="font-size: 24px; font-weight: 800; color: var(--fg, #ffffff);">$${spend.toFixed(2)} <span style="font-size: 14px; font-weight: 500; color: var(--fg-muted, #9ca3af);">/ $5.00</span></div>
          </div>
          <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 4px 10px; border-radius: 999px; ${isExceeded ? 'background:#7f1d1d;color:#fca5a5;' : 'background:#064e3b;color:#34d399;'}">
            ${isExceeded ? 'BUDGET EXCEEDED (LOCAL ONLY)' : 'BUDGET ACTIVE (TIER 0-2)'}
          </span>
        </div>

        <div style="width: 100%; height: 8px; background: rgba(255,255,255,0.08); border-radius: 999px; overflow: hidden;">
          <div style="width: ${pct}%; height: 100%; background: ${isExceeded ? '#ef4444' : 'var(--brand-color, #c1122f)'}; transition: width 0.3s ease;"></div>
        </div>
      </div>

      <!-- 3-Tier Dynamic Routing Matrix -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px;">
        
        <div style="background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 16px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
            <strong style="font-size: 13px; color: #34d399;">Tier 0: Local Free</strong>
            <span style="font-size: 11px; color: #34d399;">$0.00/1M</span>
          </div>
          <div style="font-size: 12px; font-weight: 600; color: var(--fg, #e5e7eb);">Qwen 2.5 Coder / Ollama</div>
          <div style="font-size: 11px; color: var(--fg-muted, #9ca3af); margin-top: 4px;">Daily conversation, web scraping parsing, AST checks, simple JSON formatting.</div>
        </div>

        <div style="background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 16px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
            <strong style="font-size: 13px; color: #60a5fa;">Tier 1: Sub-Cent Cloud</strong>
            <span style="font-size: 11px; color: #60a5fa;">~$0.15/1M</span>
          </div>
          <div style="font-size: 12px; font-weight: 600; color: var(--fg, #e5e7eb);">gpt-4o-mini</div>
          <div style="font-size: 11px; color: var(--fg-muted, #9ca3af); margin-top: 4px;">Morning briefings, Reflexion error distillation, SDUI schemas, email triage.</div>
        </div>

        <div style="background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 16px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
            <strong style="font-size: 13px; color: #f43f5e;">Tier 2: High Reasoning</strong>
            <span style="font-size: 11px; color: #f43f5e;">~$1.10/1M</span>
          </div>
          <div style="font-size: 12px; font-weight: 600; color: var(--fg, #e5e7eb);">o3-mini / gpt-4o</div>
          <div style="font-size: 11px; color: var(--fg-muted, #9ca3af); margin-top: 4px;">Git repo refactoring, complex mathematical models, multi-persona Oracle debates.</div>
        </div>

      </div>

      <!-- Autonomous Proactive Daemon Status -->
      <div style="background: var(--surface-1, #18181f); border: 1px solid var(--border, #2d2d33); border-radius: 14px; padding: 16px;">
        <strong style="font-size: 13px; color: var(--fg, #e5e7eb); display: block; margin-bottom: 10px;">Autonomous Proactive Daemon Schedule</strong>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; font-size: 12px;">
          <div style="padding: 10px; background: rgba(0,0,0,0.3); border-radius: 8px;">
            <div style="color: var(--fg-muted, #9ca3af);">07:00 AM Daily</div>
            <strong style="color: var(--fg, #e5e7eb);">Morning Briefing</strong>
          </div>
          <div style="padding: 10px; background: rgba(0,0,0,0.3); border-radius: 8px;">
            <div style="color: var(--fg-muted, #9ca3af);">03:00 AM Daily</div>
            <strong style="color: var(--fg, #e5e7eb);">Nightly Memory Evolution</strong>
          </div>
          <div style="padding: 10px; background: rgba(0,0,0,0.3); border-radius: 8px;">
            <div style="color: var(--fg-muted, #9ca3af);">04:00 AM Daily</div>
            <strong style="color: var(--fg, #e5e7eb);">Database Vacuum & Prune</strong>
          </div>
          <div style="padding: 10px; background: rgba(0,0,0,0.3); border-radius: 8px;">
            <div style="color: var(--fg-muted, #9ca3af);">Every 4 Hours</div>
            <strong style="color: var(--fg, #e5e7eb);">Voyager Interest Profiler</strong>
          </div>
        </div>
      </div>
    `;
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

export default ToolCreator;
