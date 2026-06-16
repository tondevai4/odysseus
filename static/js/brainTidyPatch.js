(function () {
  if (window.__yvesBrainTidyPatch) return;
  window.__yvesBrainTidyPatch = true;

  function toast(message, kind) {
    const node = document.createElement('div');
    node.className = 'brain-tidy-toast';
    node.textContent = message;
    node.style.cssText = 'position:fixed;right:18px;bottom:92px;z-index:12000;max-width:min(360px,calc(100vw - 32px));padding:10px 12px;border-radius:12px;border:1px solid color-mix(in srgb,var(--border) 75%,var(--brand-color,var(--red)));background:color-mix(in srgb,var(--panel) 94%,var(--bg));color:' + (kind === 'error' ? 'var(--red)' : 'var(--fg)') + ';box-shadow:0 14px 36px rgba(0,0,0,.26);font-size:13px';
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function canonical(value) {
    return normalizeText(value)
      .toLowerCase()
      .replace(/[“”]/g, '"')
      .replace(/[‘’]/g, "'")
      .replace(/[^a-z0-9]+/g, ' ')
      .replace(/\b(the|a|an)\b/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function tokenSet(value) {
    return new Set(canonical(value).split(' ').filter(Boolean));
  }

  function jaccard(a, b) {
    if (!a.size || !b.size) return 0;
    let same = 0;
    for (const token of a) if (b.has(token)) same += 1;
    return same / (a.size + b.size - same);
  }

  function chooseKeep(a, b) {
    if (!!b.pinned !== !!a.pinned) return b.pinned ? b : a;
    const aManual = a.source !== 'auto';
    const bManual = b.source !== 'auto';
    if (aManual !== bManual) return bManual ? b : a;
    return String(b.text || '').length > String(a.text || '').length ? b : a;
  }

  function planTidy(memories) {
    const deletes = new Set();
    const edits = [];
    const exact = new Map();
    const keepers = [];

    for (const memory of memories) {
      const text = normalizeText(memory.text);
      if (!text) {
        deletes.add(memory.id);
        continue;
      }
      if (text !== memory.text) edits.push({ id: memory.id, text, category: memory.category || 'fact' });
      const key = canonical(text);
      if (!key) {
        deletes.add(memory.id);
        continue;
      }
      const existing = exact.get(key);
      if (existing) {
        const keep = chooseKeep(existing, memory);
        const drop = keep === existing ? memory : existing;
        deletes.add(drop.id);
        exact.set(key, keep);
        continue;
      }
      exact.set(key, memory);
      keepers.push(memory);
    }

    const seen = [];
    for (const memory of keepers) {
      if (deletes.has(memory.id)) continue;
      const text = normalizeText(memory.text);
      const set = tokenSet(text);
      let duplicateOf = null;
      for (const previous of seen) {
        if ((previous.category || 'fact') !== (memory.category || 'fact')) continue;
        const score = jaccard(set, previous.tokens);
        const c1 = canonical(text);
        const c2 = previous.canon;
        const closeSubset = c1.length > 30 && c2.length > 30 && (c1.includes(c2) || c2.includes(c1));
        if (score >= 0.94 || (closeSubset && score >= 0.82)) {
          duplicateOf = previous.memory;
          break;
        }
      }
      if (duplicateOf) {
        const keep = chooseKeep(duplicateOf, memory);
        const drop = keep === duplicateOf ? memory : duplicateOf;
        deletes.add(drop.id);
        if (drop === duplicateOf) {
          const idx = seen.findIndex(item => item.memory.id === duplicateOf.id);
          if (idx >= 0) seen.splice(idx, 1, { memory, tokens: set, canon: canonical(text), category: memory.category || 'fact' });
        }
      } else {
        seen.push({ memory, tokens: set, canon: canonical(text), category: memory.category || 'fact' });
      }
    }

    return {
      edits: edits.filter(edit => !deletes.has(edit.id)),
      deletes: [...deletes],
    };
  }

  async function putMemory(edit) {
    const form = new FormData();
    form.set('text', edit.text);
    form.set('category', edit.category || 'fact');
    const res = await fetch(`/api/memory/${encodeURIComponent(edit.id)}`, {
      method: 'PUT',
      credentials: 'same-origin',
      body: form,
    });
    if (!res.ok) throw new Error(`Failed to update memory ${edit.id}`);
  }

  async function deleteMemory(id) {
    const res = await fetch(`/api/memory/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    });
    if (!res.ok && res.status !== 404) throw new Error(`Failed to delete memory ${id}`);
  }

  function applyDomDiff(plan) {
    for (const edit of plan.edits) {
      const item = document.querySelector(`.memory-item[data-memory-id="${CSS.escape(String(edit.id))}"]`);
      const text = item?.querySelector('.memory-item-text');
      if (text) text.textContent = edit.text;
    }
    for (const id of plan.deletes) {
      document.querySelector(`.memory-item[data-memory-id="${CSS.escape(String(id))}"]`)?.remove();
    }
  }

  async function tidy(event) {
    const button = event.target.closest && event.target.closest('#memory-tidy-btn');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (window.__yvesBrainTidyRunning) return;
    window.__yvesBrainTidyRunning = true;

    const original = button.innerHTML;
    button.disabled = true;
    button.textContent = 'Tidying…';
    try {
      const res = await fetch('/api/memory', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error('Could not load memories');
      const data = await res.json();
      const memories = Array.isArray(data.memory) ? data.memory : Array.isArray(data) ? data : [];
      const before = memories.length;
      const plan = planTidy(memories);

      for (const edit of plan.edits) await putMemory(edit);
      for (const id of plan.deletes) await deleteMemory(id);

      applyDomDiff(plan);
      window.dispatchEvent(new CustomEvent('vanta:memory-updated'));
      const changed = plan.edits.length + plan.deletes.length;
      if (!changed) toast('Brain tidy: already clean.');
      else toast(`Brain tidy complete: ${plan.deletes.length} removed, ${plan.edits.length} cleaned (${before} → ${before - plan.deletes.length}).`);
    } catch (error) {
      console.error('Brain tidy failed:', error);
      toast(`Brain tidy failed: ${error.message || error}`, 'error');
    } finally {
      button.disabled = false;
      button.innerHTML = original;
      window.__yvesBrainTidyRunning = false;
    }
  }

  document.addEventListener('click', tidy, true);
})();
