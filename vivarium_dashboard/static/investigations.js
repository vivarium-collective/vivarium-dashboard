// vivarium_dashboard/static/investigations.js
(function () {
  var state = { plans: [], activeSlug: null };

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function loadInvestigations() {
    return fetch('/api/plans').then(function (r) { return r.json(); }).then(function (plans) {
      state.plans = plans || [];
      renderList();
    }).catch(function (e) {
      console.error('Failed to load investigations:', e);
    });
  }

  function renderList() {
    var ul = document.getElementById('investigations-list');
    if (!ul) return;
    ul.innerHTML = '';
    if (!state.plans.length) {
      var li = document.createElement('li');
      li.className = 'placeholder';
      li.textContent = 'No investigations yet. Click "+ New investigation" to start one.';
      ul.appendChild(li);
      // Show list, hide detail.
      ul.hidden = false;
      var detail = document.getElementById('investigation-detail');
      if (detail) detail.hidden = true;
      return;
    }
    state.plans.forEach(function (p) {
      var li = document.createElement('li');
      li.className = 'investigation-card';
      li.innerHTML =
        '<a class="investigation-title">' + escapeHtml(p.name) + '</a>' +
        ' <span class="badge status-' + escapeHtml(p.status) + '">' + escapeHtml(p.status) + '</span>' +
        ' <span class="muted">' + escapeHtml(p.n_studies) + ' studies</span>' +
        '<p class="muted">' + escapeHtml((p.objective || '').slice(0, 200)) + '</p>';
      li.querySelector('.investigation-title').addEventListener('click', function () {
        openInvestigation(p.slug);
      });
      ul.appendChild(li);
    });
    var detail = document.getElementById('investigation-detail');
    if (detail) detail.hidden = true;
    ul.hidden = false;
  }

  function openInvestigation(slug) {
    state.activeSlug = slug;
    return fetch('/api/plan/' + encodeURIComponent(slug)).then(function (r) {
      if (!r.ok) { alert('Failed to load investigation: ' + r.status); throw r; }
      return r.json();
    }).then(function (plan) {
      var list = document.getElementById('investigations-list');
      var detail = document.getElementById('investigation-detail');
      if (list) list.hidden = true;
      if (detail) detail.hidden = false;

      var title = document.getElementById('investigation-title');
      if (title) title.textContent = plan.name || '';
      var obj = document.getElementById('investigation-objective');
      if (obj) obj.textContent = plan.objective || '';
      var hyp = document.getElementById('investigation-hypothesis');
      if (hyp) hyp.textContent = plan.hypothesis || '';

      var completes = (plan.studies || []).filter(function (s) {
        return s.derived_status === 'complete';
      }).length;
      var statusEl = document.getElementById('investigation-status');
      if (statusEl) statusEl.textContent =
        'Status: ' + (plan.status || 'planned') + ' (' + completes + '/' + (plan.studies || []).length + ' studies complete)';

      var refs = document.getElementById('investigation-references');
      if (refs) {
        refs.innerHTML = '';
        (plan.references || []).forEach(function (r) {
          var li = document.createElement('li');
          li.innerHTML = '📄 <a href="/' + escapeHtml(r.file) + '">' + escapeHtml(r.label || r.file) + '</a>';
          refs.appendChild(li);
        });
      }

      var cards = document.getElementById('investigation-study-cards');
      if (cards) {
        cards.innerHTML = '';
        (plan.studies || []).forEach(function (s, i) {
          var li = document.createElement('li');
          var icon = ({complete: '✅', 'in-progress': '🔄', blocked: '⏸', planned: '⏳'})[s.derived_status] || '•';
          var gateNote = s.gate ? '<span class="muted">(gate: ' + escapeHtml(s.gate) + ')</span>' : '';
          li.className = 'study-card study-' + escapeHtml(s.derived_status);
          li.innerHTML =
            '<span class="study-icon">' + icon + '</span>' +
            ' <a class="study-link">' + (i + 1) + '. ' + escapeHtml(s.study) + '</a>' +
            ' <span class="study-status">' + escapeHtml(s.derived_status) + '</span> ' +
            gateNote;
          li.addEventListener('click', function (e) {
            // Allow the "Open in own page" link inside expanded content to navigate normally.
            if (e.target.matches('.open-study-link')) return;
            toggleStudyCard(li, s.study);
          });
          cards.appendChild(li);
        });
      }
    });
  }

  function toggleStudyCard(li, slug) {
    if (li.classList.contains('expanded')) {
      li.classList.remove('expanded');
      var content = li.querySelector('.study-card-content');
      if (content) content.remove();
      return;
    }
    li.classList.add('expanded');
    fetch('/api/investigation/' + encodeURIComponent(slug)).then(function (r) {
      if (!r.ok) { li.classList.remove('expanded'); return; }
      return r.json();
    }).then(function (study) {
      if (!study) return;
      var content = document.createElement('div');
      content.className = 'study-card-content';
      content.innerHTML = renderStudyExpanded(study);
      li.appendChild(content);
    });
  }

  function renderStudyExpanded(study) {
    function esc(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
      });
    }
    var baselines = (study.baseline || []).map(function (b) {
      return '<li><code>' + esc(b.name) + '</code> — <code class="muted">' + esc(b.composite) + '</code></li>';
    }).join('');
    var variants = (study.variants || []).map(function (v) {
      return '<li><code>' + esc(v.name) + '</code></li>';
    }).join('');
    var interventions = (study.interventions || []).map(function (i) {
      return '<li><strong>' + esc(i.name) + '</strong>: ' + esc(i.description || '') + '</li>';
    }).join('');
    var lr = (study.tests && study.tests.last_results) || null;
    var testsLine = lr
      ? (lr.passed + ' passed / ' + lr.failed + ' failed / ' + lr.skipped + ' skipped')
      : '(no test results yet)';
    return [
      '<div class="card-section"><h5>Objective</h5><p>' + esc(study.objective || '(none)') + '</p></div>',
      '<div class="card-section"><h5>Question</h5><p>' + esc(study.question || '(none)') + '</p></div>',
      '<div class="card-section"><h5>Hypothesis</h5><p>' + esc(study.hypothesis || '(none)') + '</p></div>',
      '<div class="card-section"><h5>Baseline (' + (study.baseline || []).length + ')</h5><ul>' + (baselines || '<li class="muted">(none)</li>') + '</ul></div>',
      '<div class="card-section"><h5>Variants (' + (study.variants || []).length + ')</h5><ul>' + (variants || '<li class="muted">(none)</li>') + '</ul></div>',
      '<div class="card-section"><h5>Interventions (' + (study.interventions || []).length + ')</h5><ul>' + (interventions || '<li class="muted">(none)</li>') + '</ul></div>',
      '<div class="card-section"><h5>Tests</h5><p>' + esc(testsLine) + '</p></div>',
      '<div class="card-section"><a class="open-study-link" href="#studies/' + encodeURIComponent(study.name || '') + '">Open in own page →</a></div>',
    ].join('');
  }

  function backToList() {
    var list = document.getElementById('investigations-list');
    var detail = document.getElementById('investigation-detail');
    if (list) list.hidden = false;
    if (detail) detail.hidden = true;
    state.activeSlug = null;
  }

  function openCreateDialog() {
    var dialog = document.getElementById('new-investigation-dialog');
    if (!dialog) return;
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    var submit = document.getElementById('new-inv-submit');
    if (!submit) return;
    // Attach a one-shot handler.
    submit.addEventListener('click', function () {
      var name = document.getElementById('new-inv-name').value.trim();
      var objective = document.getElementById('new-inv-objective').value;
      var hypothesis = document.getElementById('new-inv-hypothesis').value;
      var studiesStr = document.getElementById('new-inv-studies').value;
      var studies = studiesStr.split(',').map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; })
        .map(function (s) { return { study: s }; });
      if (!name) return;
      fetch('/api/plan-create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, objective: objective, hypothesis: hypothesis, studies: studies}),
      }).then(function (r) {
        if (!r.ok) return r.json().then(function (err) {
          alert('Failed: ' + (err.error || r.status));
        });
        loadInvestigations();
      });
    }, {once: true});
  }

  function _populateBaselineList() {
    var box = document.getElementById('add-study-baseline-list');
    if (!box) return;
    fetch('/api/composites').then(function (r) { return r.json(); }).then(function (catalog) {
      box.innerHTML = '';
      var comps = (catalog && catalog.composites) || [];
      if (!comps.length) {
        box.innerHTML = '<p class="muted">No composites in workspace catalog.</p>';
        return;
      }
      comps.forEach(function (c) {
        var label = document.createElement('label');
        label.className = 'baseline-checkbox';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = c.id;
        cb.dataset.name = c.name || c.id.split('.').pop();
        label.appendChild(cb);
        label.appendChild(document.createTextNode(' ' + (c.name || c.id) + ' '));
        var fqn = document.createElement('code');
        fqn.className = 'muted';
        fqn.textContent = c.id;
        label.appendChild(fqn);
        box.appendChild(label);
      });
    });
  }

  function _setAddStudyFeedback(msg, kind) {
    var el = document.getElementById('add-study-feedback');
    if (!el) return;
    el.textContent = msg;
    el.className = 'muted' + (kind === 'ok' ? ' ok' : kind === 'fail' ? ' fail' : '');
  }

  window._submitAddStudy = function (event) {
    event.preventDefault();
    var form = event.target;
    var fd = new FormData(form);
    var slug = String(fd.get('slug') || '').trim();
    var objective = String(fd.get('objective') || '').trim();
    var gate = String(fd.get('gate') || '');
    var checked = Array.prototype.slice.call(form.querySelectorAll('input[type=checkbox]:checked'));
    if (!slug) { _setAddStudyFeedback('slug required', 'fail'); return false; }
    if (!checked.length) { _setAddStudyFeedback('pick at least one baseline composite', 'fail'); return false; }
    var invSlug = state.activeSlug;
    if (!invSlug) { _setAddStudyFeedback('no active investigation', 'fail'); return false; }

    _setAddStudyFeedback('creating study…', '');

    fetch('/api/investigation-create', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: slug, objective: objective}),
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || 'create failed'); });
      // Sequentially add baseline entries so server-side state stays consistent.
      var seq = Promise.resolve();
      checked.forEach(function (cb, idx) {
        seq = seq.then(function () {
          return fetch('/api/study-baseline-add', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              study: slug,
              name: cb.dataset.name + (idx ? '-' + idx : ''),
              composite: cb.value,
              params: {},
            }),
          }).then(function (resp) {
            if (!resp.ok) return resp.json().then(function (e) { throw new Error(e.error || 'baseline-add failed'); });
          });
        });
      });
      return seq;
    }).then(function () {
      return fetch('/api/plan-study-add', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({slug: invSlug, study: slug, gate: gate || null}),
      });
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || 'plan-study-add failed'); });
      _setAddStudyFeedback('created', 'ok');
      form.reset();
      var details = document.querySelector('.add-study-details');
      if (details) details.open = false;
      openInvestigation(invSlug);  // refresh the detail view
    }).catch(function (e) {
      _setAddStudyFeedback('error: ' + e.message, 'fail');
    });
    return false;
  };

  // Wire button event listeners after DOM is ready.
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('new-investigation-btn');
    if (btn) btn.addEventListener('click', openCreateDialog);
    var back = document.getElementById('investigation-back');
    if (back) back.addEventListener('click', backToList);
    // Populate baseline checkboxes whenever the user opens the add-study details.
    document.addEventListener('toggle', function (e) {
      if (e.target && e.target.classList && e.target.classList.contains('add-study-details')) {
        if (e.target.open) _populateBaselineList();
      }
    }, true);
  });

  // Expose for the page-router (walkthrough.js's _switchPage).
  window.loadInvestigations = loadInvestigations;
})();
