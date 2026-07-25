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
      var href = "/?focus=composite-explore&id=" + encodeURIComponent(cid) + "#composite-explore";
      return '<a href="' + href + '" title="' + esc(cid) + ' — open in the Composite Explorer" ' +
        'style="text-decoration:none;white-space:nowrap;"><code style="font-size:11px;">' + esc(short) + "</code> ↗</a>";
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
    // to launch against). The <tr> is clickable (opens the run), so the
    // button's onclick MUST stopPropagation or the row-open handler would
    // also fire.
    var isSnapshot = (window.__DASH_CONFIG__ || {}).mode === "snapshot";
    var rerun = (row.run_id && !isSnapshot)
      ? '<button type="button" class="action-btn js-authoring" title="Re-run this simulation as a brand-new run" ' +
        'onclick="event.stopPropagation();window._rerunSim(\'' + esc(row.run_id) + '\', this);">↻ Rerun</button>' : "";
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
    cells += td(_actions(row), "text-align:center;white-space:nowrap;");
    return '<tr data-run-id="' + esc(runId) + '" style="border-bottom:1px solid #f3f4f6;cursor:pointer;" ' +
      'title="Click to open this run — its study, or the Composite Explorer">' + cells + "</tr>";
  }

  var STUDY_COLS = [
    { label: "Run", key: "run" }, { label: "Composite", key: "composite" },
    { label: "Config", key: "config" },
    { label: "Location", key: "location" },
    { label: "Origin", key: "origin" }, { label: "Emitter", key: "emitter" },
    { label: "Time", key: "time" }, { label: "Status", key: "status" }, { label: "", key: null },
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
  }

  window.SimTable = {
    esc: esc, statusChip: statusChip, emitterPill: emitterPill, originPill: originPill,
    originLabel: originLabel, fmtTime: fmtTime, location: location, study: study,
    investigation: investigation, composite: composite,
    renderRow: renderRow, renderTable: renderTable,
  };
})();
