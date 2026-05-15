// Workspace switcher: dropdown panel in the left rail.
//
// Reads GET /api/workspaces and renders rows by status. Click handlers:
//   running  → navigate same tab to row.url
//   stopped  → POST /api/workspaces/start, then navigate to returned url
//   stale    → POST /api/workspaces/cleanup-stale, then re-render
//   missing  → POST /api/workspaces/forget, then re-render

(function () {
  const trigger = document.getElementById('viv-workspace-switcher-trigger');
  const panel   = document.getElementById('viv-workspace-switcher-panel');
  const list    = document.getElementById('viv-workspace-switcher-list');
  const addBtn  = document.getElementById('viv-workspace-switcher-add');
  if (!trigger || !panel || !list) return;

  const GLYPH = {
    current: '●', running: '●', stopped: '○', stale: '⚠', missing: '⊘',
  };
  const GLYPH_CLASS = {
    current: 'viv-glyph-running', running: 'viv-glyph-running',
    stopped: 'viv-glyph-stopped', stale: 'viv-glyph-stale',
    missing: 'viv-glyph-missing',
  };

  function close() {
    panel.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  }
  function open() {
    panel.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    refresh();
  }

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    if (panel.hidden) open(); else close();
  });
  document.addEventListener('click', (e) => {
    if (!panel.hidden && !panel.contains(e.target) && e.target !== trigger) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !panel.hidden) close();
  });

  async function refresh() {
    list.innerHTML = '<li class="viv-workspace-switcher-loading">Loading…</li>';
    try {
      const resp = await fetch('/api/workspaces');
      const data = await resp.json();
      render(data);
    } catch (err) {
      list.innerHTML = `<li class="viv-ws-error">Failed to load: ${escapeHtml(String(err))}</li>`;
    }
  }

  function render(data) {
    list.innerHTML = '';
    data.workspaces.forEach((ws) => {
      list.appendChild(renderRow(ws, data.current));
    });
  }

  function renderRow(ws, current) {
    const li = document.createElement('li');
    if (ws.status === 'current') li.classList.add('viv-workspace-switcher-list', 'viv-ws-row-current');

    const glyph = document.createElement('span');
    glyph.className = `viv-ws-glyph ${GLYPH_CLASS[ws.status] || ''}`;
    glyph.textContent = GLYPH[ws.status] || '?';
    li.appendChild(glyph);

    if (ws.status === 'current') {
      const label = document.createElement('div');
      label.style.flex = '1';
      label.innerHTML = `<strong>${escapeHtml(ws.name)}</strong> <small>(this)</small>
                         <div class="viv-ws-path">${escapeHtml(ws.path)}</div>`;
      li.appendChild(label);
      return li;
    }

    if (ws.status === 'running') {
      const a = document.createElement('a');
      a.href = ws.url;
      a.innerHTML = `<strong>${escapeHtml(ws.name)}</strong>
                     <span class="viv-ws-path">${escapeHtml(ws.path)}</span>`;
      li.appendChild(a);
      return li;
    }

    const label = document.createElement('div');
    label.style.flex = '1';
    label.innerHTML = `<strong>${escapeHtml(ws.name)}</strong>
                       <div class="viv-ws-path">${escapeHtml(ws.path)}</div>`;
    li.appendChild(label);

    if (ws.status === 'stopped') {
      const btn = document.createElement('button');
      btn.textContent = 'Start ▸';
      btn.addEventListener('click', () => doStart(ws.path, btn, li));
      li.appendChild(btn);
    } else if (ws.status === 'stale') {
      const btn = document.createElement('button');
      btn.textContent = 'Clean up';
      btn.addEventListener('click', () => doCleanup(ws.path, btn, li));
      li.appendChild(btn);
    } else if (ws.status === 'missing') {
      const btn = document.createElement('button');
      btn.textContent = 'Forget ×';
      btn.addEventListener('click', () => doForget(ws.path, btn, li));
      li.appendChild(btn);
    }
    return li;
  }

  async function doStart(path, btn, row) {
    btn.disabled = true;
    btn.textContent = 'Starting…';
    try {
      const resp = await fetch('/api/workspaces/start', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path}),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        rowError(row, body.error || `HTTP ${resp.status}`,
                 body.log_path ? `(log: ${body.log_path})` : '');
        btn.disabled = false; btn.textContent = 'Start ▸';
        return;
      }
      const data = await resp.json();
      window.location.href = data.url;
    } catch (err) {
      rowError(row, String(err));
      btn.disabled = false; btn.textContent = 'Start ▸';
    }
  }

  async function doCleanup(path, btn, row) {
    btn.disabled = true;
    try {
      const resp = await fetch('/api/workspaces/cleanup-stale', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path}),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        rowError(row, body.error || `HTTP ${resp.status}`);
        btn.disabled = false;
        return;
      }
      refresh();
    } catch (err) {
      rowError(row, String(err));
      btn.disabled = false;
    }
  }

  async function doForget(path, btn, row) {
    btn.disabled = true;
    try {
      const resp = await fetch('/api/workspaces/forget', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path}),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        rowError(row, body.error || `HTTP ${resp.status}`);
        btn.disabled = false;
        return;
      }
      refresh();
    } catch (err) {
      rowError(row, String(err));
      btn.disabled = false;
    }
  }

  function rowError(row, msg, hint) {
    const e = document.createElement('div');
    e.className = 'viv-ws-error';
    e.textContent = hint ? `${msg} ${hint}` : msg;
    row.appendChild(e);
  }

  if (addBtn) {
    addBtn.addEventListener('click', async () => {
      const p = window.prompt('Path to workspace directory:');
      if (!p) return;
      const resp = await fetch('/api/workspaces/add', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: p}),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        alert('Could not add: ' + (body.error || `HTTP ${resp.status}`));
        return;
      }
      refresh();
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
})();
