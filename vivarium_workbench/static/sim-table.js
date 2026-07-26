// sim-table.js — the single Simulations-DB table renderer.
//
// One source of truth for a run row (status chip, emitter/origin pills, location,
// time, ⬇Data/⬇Analysis actions) so the global "Simulations DB" page and the
// per-study Simulations tab render IDENTICAL rows. The study tab drops the
// Investigation + Study columns (redundant when scoped to one study) via
// `opts.scope === 'study'`. walkthrough.js delegates its row/cell helpers here.
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function statusChip(status) {
    var colors = {
      completed: ["#dcfce7", "#166534"], running: ["#dbeafe", "#1e40af"],
      failed: ["#fee2e2", "#991b1b"], orphaned: ["#e5e7eb", "#374151"],
    };
    var c = colors[status] || ["#e5e7eb", "#374151"];
    return '<span style="background:' + c[0] + ";color:" + c[1] +
      ';padding:2px 8px;border-radius:10px;font-size:12px;">' + esc(status || "?") + "</span>";
  }

  function emitterPill(t) {
    t = t || "SQLite";
    if (t === "—" || t === "none" || t === "") {
      return '<span class="emitter-pill emitter-none" title="no emitter (summary-only run)">—</span>';
    }
    return '<span class="emitter-pill emitter-' + t.toLowerCase() +
      '" title="emitter / persistence format">' + esc(t) + "</span>";
  }

  function originLabel(row) {
    var o = row && row.remote_origin;
    return o ? String(o.deployment || "remote") : "local";
  }

  function originPill(row) {
    var o = row && row.remote_origin;
    if (!o) return '<span class="origin-pill origin-local" title="local run">local</span>';
    var dep = originLabel(row);
    var tip = "Remote run on " + dep + " (AWS GovCloud)" +
      (o.simulation_id != null ? " — sim " + o.simulation_id : "") +
      (o.experiment_id ? "\nexperiment: " + o.experiment_id : "") +
      (o.s3_uri ? "\nS3: " + o.s3_uri : "");
    return '<span class="origin-pill origin-remote" title="' + esc(tip) + '">' + esc(dep) + "</span>";
  }

  function fmtTime(sec) { return sec ? new Date(sec * 1000).toLocaleString() : "—"; }

  function investigation(row) { return row.investigation_slug || ""; }
  function study(row) {
    return row.study_slug || (row.studies && row.studies.length ? row.studies[0] : "");
  }

  function location(row) {
    var loc = row.store_path || row.db_path || "";
    if (!loc) return '<span style="color:#9ca3af;">—</span>';
    var norm = String(loc).replace(/\\/g, "/");
    var parts = norm.split("/");
    var tail = parts.length > 2 ? "…/" + parts.slice(-2).join("/") : norm;
    return '<code style="font-size:11px;color:#6b7280;display:block;overflow:hidden;' +
      'text-overflow:ellipsis;white-space:nowrap;" title="' + esc(loc) + '">' + esc(tail) + "</code>";
  }

  // Composite cell — enforcement: every simulation must map to exactly one
  // REGISTERED composite. Registered → a link that opens it in the Composite
  // Explorer; missing/unregistered → a red flag (title explains the rule).
  function composite(row) {
    var cid = row && row.spec_id ? String(row.spec_id) : "";
    if (!cid) {
      return '<span title="No composite associated — every simulation must map to one registered composite." ' +
        'style="color:#b91c1c;font-size:12px;white-space:nowrap;">⚠ none</span>';
    }
    var short = cid.split(".").pop();
    if (row.composite_registered) {
      // In-app link (keeps the left nav) that opens THIS run in the Composite
      // Explorer with its saved config pre-filled — wired in renderTable().
      return '<span class="sim-composite-link" data-run-id="' + esc(row.run_id || "") + '" ' +
        'title="' + esc(cid) + ' — open this run in the Composite Explorer (its saved config pre-filled)" ' +
        'style="text-decoration:underline;text-underline-offset:2px;cursor:pointer;white-space:nowrap;color:#2563eb;">' +
        '<code style="font-size:11px;color:inherit;">' + esc(short) + "</code> ↗</span>";
    }
    return '<span title="' + esc(cid) + ' — not a registered composite. Every simulation must map to one registered composite." ' +
      'style="color:#b91c1c;font-size:12px;white-space:nowrap;">⚠ <code style="font-size:11px;color:inherit;">' + esc(short) + "</code></span>";
  }

  // Config cell — the exact generator params that reproduce this run. Shows the
  // first few key=value chips (repro-relevant keys first); full config in the
  // hover title. Empty config → grey em-dash.
  function config(row) {
    var c = row && row.config;
    if (!c || typeof c !== "object" || !Object.keys(c).length) {
      return '<span style="color:#9ca3af;">—</span>';
    }
    var order = ["condition", "media", "seed", "n_steps", "config_overrides"];
    var keys = Object.keys(c).sort(function (a, b) {
      var ia = order.indexOf(a), ib = order.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    var parts = keys.map(function (k) {
      var v = c[k];
      if (v && typeof v === "object") {
        v = Object.keys(v).length ? JSON.stringify(v) : "{}";
      }
      return esc(k) + "=" + esc(String(v));
    });
    var shown = parts.slice(0, 3).join(" · ");
    var more = parts.length > 3 ? " +" + (parts.length - 3) : "";
    var full = JSON.stringify(c, null, 2);
    return '<code style="font-size:11px;color:#6b7280;display:block;overflow:hidden;' +
      'text-overflow:ellipsis;white-space:nowrap;" title="' + esc(full) + '">' +
      shown + esc(more) + "</code>";
  }

  // Compatible-analysis-tools cell — a compact launch chip per entry in
  // `row.matched_tools` (attached server-side by lib/simulations_index.py's
  // `_attach_matched_tools`, capability-matched against the workspace's
  // installed tools/viewers). Empty when nothing matches — no clutter.
  //   - "launcher" tools: the launch_url is the resolve endpoint
  //     (GET /api/analysis-viewer/{uid}/launch) — fetch, then open the
  //     returned {"url": ...} in a new tab (mirrors static/walkthrough.js's
  //     `_launchViewer`).
  //   - everything else (embed-explorer, embed-3d, deep-links): launch_url
  //     is already the concrete page to open — a plain new-tab link.
  function toolsCell(row) {
    var tools = (row && row.matched_tools) || [];
    if (!tools.length) return "";
    return tools.map(function (t) {
      var label = esc(t.label || t.id || "Tool");
      var url = t.launch_url || "";
      if (t.kind === "launcher") {
        return '<button type="button" class="action-btn js-authoring tool-launch-btn" ' +
          'data-launch-url="' + esc(url) + '" title="Launch ' + label + '">' + label + " &#8599;</button>";
      }
      return '<a class="action-btn js-authoring" title="Open ' + label + '" target="_blank" ' +
        'rel="noopener" href="' + esc(url) + '" style="text-decoration:none;">' + label + " &#8599;</a>";
    }).join(" ");
  }

  // Launch a "launcher"-kind tool chip: fetch the resolve endpoint, then open
  // the returned URL. Delegated at the document level (capture phase) so it
  // works for both the global Sim-DB tbody and the per-study renderTable()
  // mount, and so it can stopPropagation before the row's own click-to-open
  // handler fires — same pattern as `_onRerunButtonClick` below.
  function _onToolLaunchClick(e) {
    var btn = e.target.closest(".tool-launch-btn");
    if (!btn) return;
    e.stopPropagation();
    var url = btn.getAttribute("data-launch-url");
    if (!url) return;
    var origLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "…";
    fetch(url).then(function (r) {
      return r.text().then(function (t) {
        var d = {};
        try { d = t ? JSON.parse(t) : {}; }
        catch (e2) { d = { error: "server returned " + r.status }; }
        return { status: r.status, body: d };
      });
    }).then(function (res) {
      btn.disabled = false;
      btn.textContent = origLabel;
      var b = res.body || {};
      if (res.status === 200 && b.url) window.open(b.url, "_blank", "noopener");
      else {
        var msg = "Launch failed: " + (b.error || res.status);
        if (typeof _showToast === "function") _showToast(msg); else alert(msg);
      }
    }).catch(function (err) {
      btn.disabled = false;
      btn.textContent = origLabel;
      var msg = "Launch failed: " + err;
      if (typeof _showToast === "function") _showToast(msg); else alert(msg);
    });
  }
  document.addEventListener("click", _onToolLaunchClick, true);

  function _actions(row) {
    var runIdEnc = encodeURIComponent(row.run_id || "");
    var studySlug = study(row);
    var data = (row.run_id && (row.store_path || row.db_path))
      ? '<a class="action-btn js-authoring" title="Download this run\'s raw emitter data (.zip)" ' +
        'href="/api/simulation-run-download?run_id=' + runIdEnc + '" download style="text-decoration:none;">⬇ Data</a>' : "";
    var analysis = studySlug
      ? '<a class="action-btn js-authoring" title="Download the analysis-flush output for this run\'s study (.zip)" ' +
        'href="/api/study-analysis-zip?study=' + encodeURIComponent(studySlug) + '" download style="text-decoration:none;">⬇ Analysis</a>' : "";
    // Rerun — replays this run as a brand-new one via POST /api/run-rerun.
    // Not available against a published read-only snapshot (no live backend
    // to launch against). No run_id is interpolated into markup/attributes
    // here: embedding it in an inline onclick= JS string would need JS
    // escaping, not esc()'s HTML-entity escaping (the browser HTML-decodes
    // the attribute before compiling it as JS, so a literal `'` in run_id
    // would decode back and terminate the string early). Instead the button
    // carries no id at all — the document-level delegated listener below
    // resolves run_id from the enclosing <tr data-run-id> (already safely
    // HTML-escaped there), and calls stopPropagation itself so the row's own
    // click-to-open handler (the <tr> is clickable) never fires.
    var isSnapshot = (window.__DASH_CONFIG__ || {}).mode === "snapshot";
    var rerun = (row.run_id && !isSnapshot)
      ? '<button type="button" class="action-btn js-authoring rerun-btn" ' +
        'title="Re-run this simulation as a brand-new run">↻ Rerun</button>' : "";
    var parts = [data, analysis, rerun].filter(function (h) { return !!h; });
    return parts.join(" ");
  }

  // Global handler for the ⬇/↻ action buttons rendered above (sim-table.js is
  // an IIFE, so expose on window like the other row helpers). One-click
  // rerun: POST /api/run-rerun, then refresh whichever Simulations table is
  // mounted (global Sim-DB page and/or per-study tab — both expose a
  // refresh hook when present).
  function _rerunSim(runId, btnEl) {
    if (!runId) return;
    var origLabel = btnEl ? btnEl.textContent : "";
    if (btnEl) { btnEl.disabled = true; btnEl.textContent = "… rerunning"; }
    fetch("/api/run-rerun", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; })
        .catch(function () { return { ok: r.ok, status: r.status, body: {} }; });
    }).then(function (res) {
      if (btnEl) { btnEl.disabled = false; btnEl.textContent = origLabel || "↻ Rerun"; }
      var body = res.body || {};
      if (!res.ok) {
        var errMsg = "Rerun failed: " + (body.error || res.status);
        if (typeof _showToast === "function") _showToast(errMsg);
        else alert(errMsg);
        return;
      }
      var okMsg = "Rerun launched" + (body.run_id ? " — new run " + body.run_id : "");
      if (typeof _showToast === "function") _showToast(okMsg);
      else alert(okMsg);
      // Refresh whichever Simulations table(s) are on the current page.
      if (typeof window._initSimulations === "function") window._initSimulations(true);
      if (typeof window._loadStudySims === "function") window._loadStudySims(true);
    }).catch(function (err) {
      if (btnEl) { btnEl.disabled = false; btnEl.textContent = origLabel || "↻ Rerun"; }
      var netMsg = "Rerun failed: network error — " + err;
      if (typeof _showToast === "function") _showToast(netMsg);
      else alert(netMsg);
    });
  }
  window._rerunSim = _rerunSim;

  // Delegated ↻ Rerun click handling — wired ONCE at the document level
  // (not per-mount inside renderTable) because rows rendered by this module
  // reach the DOM through two different paths that don't share a common
  // container: the per-study SimTable.renderTable() mount AND the global
  // Sim-DB page's own tbody (walkthrough.js's _applySimFilter sets
  // tbody.innerHTML from renderRow() output directly, never calling
  // renderTable()). One document-level listener covers both without
  // duplicating wiring — and, critically, avoids double-firing that would
  // happen if a second listener were also added inside renderTable.
  //
  // Capture phase (the trailing `true`) is required, not just convenient:
  // the enclosing <tr> is itself clickable (opens the run) via its OWN
  // bubble-phase listener, so stopping propagation from a bubble-phase
  // document listener would run too late — the <tr> handler bubbles through
  // before an event reaches document. Capturing at document first lets
  // stopPropagation() here pre-empt the <tr> handler entirely.
  //
  // The run_id is read back from the enclosing <tr data-run-id="...">
  // (already safely HTML-escaped when rendered — see renderRow) rather than
  // interpolated into an inline onclick= JS string, which would need JS
  // string-escaping, not esc()'s HTML-entity escaping: the browser
  // HTML-decodes an attribute value before compiling it as JS, so a literal
  // `'` in run_id would decode back to `'` and terminate the string early.
  function _onRerunButtonClick(e) {
    var btn = e.target.closest(".rerun-btn");
    if (!btn) return;
    e.stopPropagation();
    var tr = btn.closest("tr[data-run-id]");
    var runId = tr ? tr.getAttribute("data-run-id") : "";
    if (!runId) return;
    _rerunSim(runId, btn);
  }
  document.addEventListener("click", _onRerunButtonClick, true);

  // Render one <tr>. opts.scope === 'study' drops Investigation + Study columns.
  function renderRow(row, opts) {
    opts = opts || {};
    var studyScope = opts.scope === "study";
    var runId = row.run_id || "";
    var runLabel = row.sim_name || row.label || runId;
    var td = function (h, extra) { return '<td style="padding:6px 8px;' + (extra || "") + '">' + h + "</td>"; };
    var cells = "";
    if (!studyScope) {
      var inv = investigation(row), st = study(row);
      cells += td(inv ? '<code style="font-size:12px;color:#374151;">' + esc(inv) + "</code>" : '<span style="color:#9ca3af;">—</span>', "overflow-wrap:anywhere;");
      cells += td(st ? '<code style="font-size:12px;color:#374151;">' + esc(st) + "</code>" : '<span style="color:#9ca3af;">—</span>', "overflow-wrap:anywhere;");
    }
    cells += td('<code style="font-size:11px;color:#6b7280;display:block;overflow:hidden;' +
      'text-overflow:ellipsis;white-space:nowrap;" title="' + esc(runId + (row.db_path ? "\n" + row.db_path : "")) +
      '">' + esc(runLabel) + "</code>", "overflow:hidden;");
    cells += td(composite(row), "overflow:hidden;");
    cells += td(config(row), "overflow:hidden;max-width:220px;");
    cells += td(location(row), "overflow:hidden;");
    cells += td(originPill(row));
    cells += td(emitterPill(row.emitter_type));
    cells += td(esc(fmtTime(row.completed_at || row.started_at)), "color:#6b7280;");
    cells += td(statusChip(row.status));
    cells += td(toolsCell(row), "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;");
    cells += td(_actions(row), "text-align:center;white-space:nowrap;");
    return '<tr data-run-id="' + esc(runId) + '" style="border-bottom:1px solid #f3f4f6;cursor:pointer;" ' +
      'title="Click to open this run — its study, or the Composite Explorer">' + cells + "</tr>";
  }

  var STUDY_COLS = [
    { label: "Run", key: "run" }, { label: "Composite", key: "composite" },
    { label: "Config", key: "config" },
    { label: "Location", key: "location" },
    { label: "Origin", key: "origin" }, { label: "Emitter", key: "emitter" },
    { label: "Time", key: "time" }, { label: "Status", key: "status" },
    { label: "Tools", key: null }, { label: "", key: null },
  ];

  function sortValue(row, key) {
    if (key === "time") return row.completed_at || row.started_at || 0;
    if (key === "composite") return String(row.spec_id || "").toLowerCase();
    if (key === "emitter") return String(row.emitter_type || "").toLowerCase();
    if (key === "origin") return originLabel(row).toLowerCase();
    if (key === "status") return String(row.status || "").toLowerCase();
    if (key === "location") return String(row.store_path || row.db_path || "").toLowerCase();
    if (key === "run") return String(row.sim_name || row.label || row.run_id || "").toLowerCase();
    return "";
  }

  // Render a sortable, clickable <table> of rows into `mount` (study Simulations
  // tab). Clicking a header toggles asc/desc; clicking a row opens the run. State
  // is stashed on the mount so re-sorts don't re-fetch.
  function renderTable(mount, rows, opts) {
    opts = opts || { scope: "study" };
    if (!mount) return;
    if (!rows || !rows.length) {
      mount.innerHTML = '<p class="empty-state muted" style="margin:0">No simulations recorded for this study yet. Launch one from Configure &amp; Run below.</p>';
      return;
    }
    mount._simRows = rows;
    var sort = mount._simSort || { key: "time", dir: "desc" };
    mount._simSort = sort;
    var sorted = rows.slice().sort(function (a, b) {
      var av = sortValue(a, sort.key), bv = sortValue(b, sort.key);
      var c = av < bv ? -1 : av > bv ? 1 : 0;
      return sort.dir === "asc" ? c : -c;
    });
    var head = "<thead><tr>" + STUDY_COLS.map(function (c) {
      var arrow = (c.key && c.key === sort.key) ? (sort.dir === "asc" ? " ▲" : " ▼") : "";
      var cursor = c.key ? "cursor:pointer;" : "";
      return '<th data-sort-key="' + (c.key || "") + '" style="text-align:left;padding:6px 8px;' +
        "border-bottom:2px solid #e5e7eb;font-size:12px;color:#6b7280;user-select:none;" + cursor +
        '">' + esc(c.label) + arrow + "</th>";
    }).join("") + "</tr></thead>";
    mount.innerHTML = '<table style="width:100%;border-collapse:collapse;">' + head +
      "<tbody>" + sorted.map(function (r) { return renderRow(r, opts); }).join("") + "</tbody></table>";
    mount.querySelectorAll("th[data-sort-key]").forEach(function (th) {
      var key = th.getAttribute("data-sort-key");
      if (!key) return;
      th.addEventListener("click", function () {
        mount._simSort = { key: key, dir: (sort.key === key && sort.dir === "desc") ? "asc" : "desc" };
        renderTable(mount, mount._simRows, opts);
      });
    });
    mount.querySelectorAll("tr[data-run-id]").forEach(function (tr) {
      tr.addEventListener("click", function (e) {
        if (e.target.closest("a")) return;  // let ⬇ links work
        var id = tr.getAttribute("data-run-id");
        var row = rows.find(function (r) { return (r.run_id || "") === id; });
        if (!row) return;
        // Custom handler (study tab → per-run detail panel) wins; else the global
        // Sim-DB behavior (navigate to the run's study / Composite Explorer).
        if (typeof opts.onRowClick === "function") opts.onRowClick(row, tr);
        else if (window._openSimulation) window._openSimulation(row);
      });
    });
    // Composite links always open the run in the Composite Explorer (in-app,
    // nav preserved) with its saved config seeded — regardless of study assoc.
    mount.querySelectorAll(".sim-composite-link").forEach(function (link) {
      link.addEventListener("click", function (e) {
        e.stopPropagation();  // don't fall through to the row's default handler
        var rid = link.getAttribute("data-run-id");
        var row = rows.find(function (r) { return (r.run_id || "") === rid; });
        if (row && window._openCompositeFromRun) window._openCompositeFromRun(row);
      });
    });
  }

  window.SimTable = {
    esc: esc, statusChip: statusChip, emitterPill: emitterPill, originPill: originPill,
    originLabel: originLabel, fmtTime: fmtTime, location: location, study: study,
    investigation: investigation, composite: composite, toolsCell: toolsCell,
    renderRow: renderRow, renderTable: renderTable,
  };
})();
