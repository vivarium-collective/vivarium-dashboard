// loom-embed.js — the composite-card loom EMBED glue, as window globals so it
// works in BOTH the main SPA (which also loads walkthrough.js's copies) and the
// study-detail IFRAME (which loads composite-card.js but NOT walkthrough.js).
//
// composite-card.js's _pcardToggleSec mounts a composite's loom via
// `_openCompositeLoomInline`; before this file, that function existed only in
// walkthrough.js, so opening a composite from a Study → Model card left the loom
// stuck on "Resolving composite & rendering the surface…" (the mount never ran).
// Loading this in the study iframe fixes that. Kept byte-identical to the
// walkthrough.js definitions.
(function () {
  "use strict";

  function _compositeStateUrl(id, overrides) {
    var apiUrl = (window.DataSource && window.DataSource.apiUrl)
      ? window.DataSource.apiUrl.bind(window.DataSource) : function (p) { return p; };
    if (document.body.classList.contains('snapshot')) {
      return apiUrl('/api/composite-state/' + encodeURIComponent(id) + '.json');
    }
    return apiUrl('/api/composite-resolve?id=' + encodeURIComponent(id)) +
      (overrides ? '&overrides=' + encodeURIComponent(overrides) : '');
  }

  // Drag-to-resize the embedded loom panel (grip below the iframe).
  function _wireLoomResize(frame, iframe) {
    var grip = document.createElement('div');
    grip.className = 'ccard-loom-resize';
    grip.title = 'Drag to resize';
    frame.appendChild(grip);
    var startY = 0, startH = 0;
    function pointY(e) { return e.touches && e.touches[0] ? e.touches[0].clientY : e.clientY; }
    function onMove(e) {
      var maxH = Math.round(window.innerHeight * 0.92);
      var h = Math.max(220, Math.min(maxH, startH + (pointY(e) - startY)));
      frame.style.height = h + 'px';
      if (e.cancelable) e.preventDefault();
      try { localStorage.setItem('viv.loomFrameH', String(Math.round(h))); } catch (err) { /* private mode */ }
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onUp);
      if (iframe) iframe.style.pointerEvents = '';
      frame.classList.remove('is-resizing');
    }
    function onDown(e) {
      startY = pointY(e);
      startH = frame.getBoundingClientRect().height;
      if (iframe) iframe.style.pointerEvents = 'none';
      frame.classList.add('is-resizing');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      document.addEventListener('touchmove', onMove, { passive: false });
      document.addEventListener('touchend', onUp);
      if (e.cancelable) e.preventDefault();
    }
    grip.addEventListener('mousedown', onDown);
    grip.addEventListener('touchstart', onDown, { passive: false });
  }

  // Mount a composite's loom into its .ccard-loom-embed container.
  function _openCompositeLoomInline(det) {
    if (!det || det._loomLoaded) return;
    if (det.tagName === 'DETAILS' && !det.open) return;
    det._loomLoaded = true;
    var id = det.getAttribute('data-id');
    var host = det.querySelector('.ccard-loom-frame');
    if (!host) return;
    host.innerHTML = '<p class="muted" style="padding:10px;font-size:0.85em">Resolving composite (this can take a moment)…</p>';
    var apiUrl = (window.DataSource && window.DataSource.apiUrl) ? window.DataSource.apiUrl.bind(window.DataSource) : function (p) { return p; };
    var tabParam = det.getAttribute('data-view') ? '&tab=' + encodeURIComponent(det.getAttribute('data-view')) : '';
    var liveInner = document.body.classList.contains('snapshot')
      ? '' : '&id=' + encodeURIComponent(id) + '&live=1';
    var fullSurface = det.getAttribute('data-surface') === 'full';
    var isSnapshot = document.body.classList.contains('snapshot');
    var chromeParam = fullSurface ? '&header=off' : '&chrome=off';
    var loomUrl = (det._loomLive || (fullSurface && !isSnapshot))
      ? apiUrl('/bigraph-loom/index.html') + '?id=' + encodeURIComponent(id) +
          (det._overrides ? '&overrides=' + encodeURIComponent(det._overrides) : '') + chromeParam + tabParam
      : apiUrl('/bigraph-loom/index.html') + '?static=1&stateUrl=' +
          encodeURIComponent(_compositeStateUrl(id, det._overrides)) + liveInner + chromeParam + tabParam;
    var f = document.createElement('iframe');
    f.className = 'ccard-loom-iframe' + (fullSurface ? ' ccard-loom-iframe-full' : '');
    f.setAttribute('title', 'Loom — ' + id);
    f.src = loomUrl;
    host.innerHTML = '';
    var savedH = 0;
    try { savedH = parseInt(localStorage.getItem('viv.loomFrameH') || '', 10) || 0; } catch (e) { /* private mode */ }
    if (!savedH && fullSurface) savedH = Math.round(window.innerHeight * 0.72);
    if (savedH) host.style.height = Math.max(fullSurface ? 480 : 220, Math.min(Math.round(window.innerHeight * 0.92), savedH)) + 'px';
    host.appendChild(f);
    _wireLoomResize(host, f);
  }

  // Only define if walkthrough.js hasn't already (main SPA); harmless to be the
  // provider in the iframe where walkthrough.js is absent.
  if (typeof window._openCompositeLoomInline !== 'function') {
    window._compositeStateUrl = _compositeStateUrl;
    window._wireLoomResize = _wireLoomResize;
    window._openCompositeLoomInline = _openCompositeLoomInline;
  }
})();
