// Cross-worktree Investigation switcher dropdown for the left rail.
//
// Pass C (2026-05-17). The dropdown now reads /api/investigation-registry —
// an aggregated view across every running dashboard on this host — instead
// of just this server's /api/iset-list. The convention is one Investigation
// per worktree per branch, so each entry corresponds to a separate worktree
// + dashboard server (intentional parallelism).
//
// Layout (top → bottom):
//
//   ┌─────────────────────────────────────────────┐
//   │ Investigations                              │   header
//   ├─────────────────────────────────────────────┤
//   │ [active here] <current slug>      [pill]    │   THIS worktree
//   ├──── OTHER WORKTREES ───────────────────────┤   (hidden if empty)
//   │ <slug>                            [pill] →  │   click → open peer URL
//   │ <slug>                            [pill] →  │
//   ├─────────────────────────────────────────────┤
//   │ + New Investigation                         │
//   └─────────────────────────────────────────────┘
//
// Clicking the current-investigation row opens its detail in-place (same
// behavior as the legacy switcher). Clicking a row under OTHER WORKTREES
// opens that peer dashboard in a new tab — it lives in a different worktree
// and shouldn't be navigated to in this tab.
//
// "+ New Investigation" still calls window._openNewIsetModal (provided by
// walkthrough.js), which scaffolds the YAML in THIS workspace.

(function () {
  const trigger = document.getElementById('viv-workspace-switcher-trigger');
  if (!trigger) return;

  let menu = null;
  let outsideHandler = null;
  let escHandler = null;

  function ensureMounted() {
    if (menu) return;
    menu = document.createElement('div');
    menu.className = 'viv-iset-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = `
      <div class="viv-iset-menu-header">Investigations</div>
      <ul class="viv-iset-menu-list">
        <li class="viv-iset-menu-loading">Loading…</li>
      </ul>
      <div class="viv-iset-menu-divider"></div>
      <button type="button" class="viv-iset-menu-new" role="menuitem">+ New Investigation</button>
    `;
    const container = document.getElementById('viv-workspace-switcher') || document.body;
    container.appendChild(menu);

    menu.querySelector('.viv-iset-menu-new').addEventListener('click', (e) => {
      e.stopPropagation();
      close();
      if (typeof window._openNewIsetModal === 'function') {
        window._openNewIsetModal();
      } else {
        window.alert('New-investigation modal is not available on this page.');
      }
    });

    menu.addEventListener('click', (e) => { e.stopPropagation(); });
  }

  function open() {
    ensureMounted();
    menu.classList.add('open');
    trigger.setAttribute('aria-expanded', 'true');
    refresh();

    setTimeout(() => {
      outsideHandler = (e) => {
        if (menu && !menu.contains(e.target) && !trigger.contains(e.target)) close();
      };
      document.addEventListener('click', outsideHandler);
    }, 0);
    escHandler = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', escHandler);
  }

  function close() {
    if (!menu) return;
    menu.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
    if (outsideHandler) {
      document.removeEventListener('click', outsideHandler);
      outsideHandler = null;
    }
    if (escHandler) {
      document.removeEventListener('keydown', escHandler);
      escHandler = null;
    }
  }

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = menu && menu.classList.contains('open');
    if (isOpen) close(); else open();
  });

  // 10-second timeout — if the server is wedged we don't want the menu to
  // hang on "Loading…" forever. Browsers don't give fetch() a default timeout.
  const REFRESH_TIMEOUT_MS = 10000;

  async function refresh() {
    const list = menu.querySelector('.viv-iset-menu-list');
    list.innerHTML = '<li class="viv-iset-menu-loading">Loading…</li>';

    // AbortController fires the abort signal after REFRESH_TIMEOUT_MS; the
    // pending fetch rejects with AbortError, which renderError classifies
    // as a timeout.
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), REFRESH_TIMEOUT_MS);

    let resp;
    try {
      resp = await fetch('/api/investigation-registry', {
        headers: { Accept: 'application/json' },
        signal: ctrl.signal,
      });
    } catch (err) {
      clearTimeout(timer);
      // Two distinct cases land here:
      //   AbortError  → our own timeout
      //   TypeError   → network unreachable (server down, DNS, etc.)
      // Browsers don't expose a more specific code for the latter; the
      // best we can do is rely on the constructor name.
      const kind = (err && err.name === 'AbortError') ? 'timeout' : 'network';
      console.error('[investigation-switcher] fetch failed', err);
      return renderError(kind, err);
    }
    clearTimeout(timer);

    if (!resp.ok) {
      const body = await resp.text().catch(() => '');
      console.error('[investigation-switcher] HTTP', resp.status, body);
      return renderError('http', new Error('HTTP ' + resp.status));
    }

    let data;
    try {
      data = await resp.json();
    } catch (err) {
      console.error('[investigation-switcher] malformed JSON', err);
      return renderError('parse', err);
    }
    render(data.current || null, data.running_others || []);
  }

  // Render an actionable error block with a Retry button, instead of a raw
  // exception string. `kind` selects the user-facing message; the original
  // error is always available in devtools via the console.error above.
  function renderError(kind, err) {
    const list = menu.querySelector('.viv-iset-menu-list');
    list.innerHTML = '';

    const messages = {
      network: {
        headline: 'Dashboard server unreachable',
        hint: 'The local server may have stopped. Run <code>pbg-server status</code> to check, or restart it.',
      },
      timeout: {
        headline: 'Dashboard didn’t respond in time',
        hint: 'The server is busy or wedged. Wait a few seconds and retry.',
      },
      http: {
        headline: 'Dashboard returned an error',
        hint: 'Server is up but rejected the request. Check the server log for the stack trace.',
      },
      parse: {
        headline: 'Malformed response from server',
        hint: 'The server returned something that isn’t JSON. Likely a crash mid-response — check the server log.',
      },
    };
    const m = messages[kind] || {
      headline: 'Failed to load investigations',
      hint: 'See devtools console for the underlying error.',
    };

    const li = document.createElement('li');
    li.className = 'viv-iset-menu-error';
    li.innerHTML = `
      <div class="viv-iset-menu-error-headline">${escapeHtml(m.headline)}</div>
      <div class="viv-iset-menu-error-hint">${m.hint}</div>
      <div class="viv-iset-menu-error-detail" title="${escapeHtml(String(err && err.message ? err.message : err))}">${escapeHtml(String(err && err.message ? err.message : err))}</div>
      <button type="button" class="viv-iset-menu-error-retry">Retry</button>
    `;
    list.appendChild(li);

    li.querySelector('.viv-iset-menu-error-retry').addEventListener('click', (e) => {
      e.stopPropagation();
      refresh();
    });
  }

  function render(current, others) {
    const list = menu.querySelector('.viv-iset-menu-list');
    list.innerHTML = '';

    if (current && current.slug) {
      list.appendChild(renderCurrentRow(current));
    } else {
      const li = document.createElement('li');
      li.className = 'viv-iset-menu-empty';
      li.textContent = 'No investigations in this worktree yet.';
      list.appendChild(li);
    }

    if (others && others.length) {
      const divider = document.createElement('li');
      divider.className = 'viv-iset-menu-section';
      divider.textContent = 'OTHER WORKTREES';
      list.appendChild(divider);
      others.forEach((peer) => list.appendChild(renderPeerRow(peer)));
    }
    // If `others` is empty, the OTHER WORKTREES section is omitted entirely
    // — no empty header, no placeholder row.
  }

  function renderCurrentRow(current) {
    const li = document.createElement('li');
    li.className = 'viv-iset-menu-row viv-iset-menu-row-current';
    li.setAttribute('role', 'menuitem');
    li.tabIndex = 0;

    const effStatus = current.effective_status || 'planning';
    const pillClass = effStatus.replace(/[^a-z_]/g, '_');
    const title = current.title || current.slug;

    li.innerHTML = `
      <div class="viv-iset-menu-row-line1">
        <strong class="viv-iset-menu-row-title">${escapeHtml(title)}</strong>
        <span class="status-pill ${escapeHtml(pillClass)} viv-iset-menu-row-pill">${escapeHtml(effStatus)}</span>
      </div>
      <div class="viv-iset-menu-row-slug">${escapeHtml(current.slug)}
        <span class="viv-iset-menu-row-current-tag">(active here)</span>
      </div>
    `;

    const activate = () => {
      close();
      switchInvestigationLocal(current.slug);
    };
    li.addEventListener('click', (e) => { e.stopPropagation(); activate(); });
    li.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
    });
    return li;
  }

  function renderPeerRow(peer) {
    const li = document.createElement('li');
    li.className = 'viv-iset-menu-row viv-iset-menu-row-peer';
    li.setAttribute('role', 'menuitem');
    li.tabIndex = 0;
    li.title = `Open ${peer.url} (worktree: ${peer.worktree_path})`;

    const effStatus = peer.effective_status || 'unknown';
    const pillClass = effStatus.replace(/[^a-z_]/g, '_');
    const title = peer.title || peer.slug || '(unnamed)';

    li.innerHTML = `
      <div class="viv-iset-menu-row-line1">
        <strong class="viv-iset-menu-row-title">${escapeHtml(title)}</strong>
        <span class="status-pill ${escapeHtml(pillClass)} viv-iset-menu-row-pill">${escapeHtml(effStatus)}</span>
        <span class="viv-iset-menu-row-arrow" aria-hidden="true">→</span>
      </div>
      <div class="viv-iset-menu-row-slug">${escapeHtml(peer.slug || '')}</div>
    `;

    const activate = () => {
      close();
      // Open the peer dashboard in a new tab — it lives in a different
      // worktree, so navigating to it in this tab would orphan the user's
      // state in the current worktree.
      window.open(peer.url, '_blank', 'noopener');
    };
    li.addEventListener('click', (e) => { e.stopPropagation(); activate(); });
    li.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
    });
    return li;
  }

  function switchInvestigationLocal(name) {
    if (typeof window._switchPage === 'function') {
      try { window._switchPage('investigations'); } catch (_) { /* ignore */ }
    }
    if (typeof window._openInvestigationDetail === 'function') {
      window._openInvestigationDetail(name);
    } else {
      window.location.hash = '#investigations';
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
})();
