"""Step 2b: the Runs-tab listing enriches a still-running remote (compose) batch
with live BatchProgress (sms-api #183) via the persisted remote_sim_id.

Covers the pure helper (_apply_live_batch_progress) and the end-to-end path through
_read_runs_meta (persisted sim id → live enrichment on the row)."""

from vivarium_workbench.lib import simulations_index as si


class _Client:
    """Stub SmsApiClient whose compose_progress returns a fixed BatchProgress."""

    def __init__(self, base_url=None, timeout=None, payload=None, boom=False):
        self._payload = payload
        self._boom = boom

    def compose_progress(self, sim_id):
        if self._boom:
            raise RuntimeError("tunnel down")
        return self._payload


def _patch_client(monkeypatch, payload=None, boom=False):
    monkeypatch.setattr(
        "vivarium_workbench.lib.sms_api_client.SmsApiClient",
        lambda base_url=None, timeout=None: _Client(base_url, payload=payload, boom=boom),
    )


def test_enrich_running_remote_row(monkeypatch):
    _patch_client(monkeypatch, payload={"lineages": "925:1000", "generations": "10:10",
                                        "overall": 60.7, "status": "RUNNING"})
    row = {"status": "running", "progress_step": None, "n_steps": None}
    si._apply_live_batch_progress(row, 7)
    assert row["status"] == "running"
    assert row["progress_step"] == 925
    assert row["n_steps"] == 1000


def test_enrich_marks_completed_when_batch_done(monkeypatch):
    _patch_client(monkeypatch, payload={"lineages": "1000:1000", "overall": 100.0, "status": "SUCCEEDED"})
    row = {"status": "running"}
    si._apply_live_batch_progress(row, 7)
    assert row["status"] == "completed"


def test_no_sim_id_is_noop(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr("vivarium_workbench.lib.sms_api_client.SmsApiClient",
                        lambda base_url=None: called.update(n=called["n"] + 1))
    row = {"status": "running", "progress_step": 3}
    si._apply_live_batch_progress(row, None)
    assert row == {"status": "running", "progress_step": 3}
    assert called["n"] == 0  # no client constructed when there's no sim id


def test_terminal_row_is_not_enriched(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr("vivarium_workbench.lib.sms_api_client.SmsApiClient",
                        lambda base_url=None: called.update(n=called["n"] + 1))
    row = {"status": "completed", "progress_step": 999}
    si._apply_live_batch_progress(row, 7)
    assert row == {"status": "completed", "progress_step": 999}
    assert called["n"] == 0  # terminal → no fetch


def test_sms_api_error_leaves_row_unchanged(monkeypatch):
    _patch_client(monkeypatch, boom=True)
    row = {"status": "running", "progress_step": 3, "n_steps": 5}
    si._apply_live_batch_progress(row, 7)  # must not raise
    assert row == {"status": "running", "progress_step": 3, "n_steps": 5}


def test_read_runs_meta_enriches_end_to_end(tmp_path, monkeypatch):
    """A persisted remote_sim_id on a running row → the listing fetches live
    BatchProgress and folds it in."""
    from vivarium_workbench.lib import composite_runs as cr

    db = tmp_path / "composite-runs.db"
    conn = cr.connect(db)
    try:
        cr.save_metadata(conn, spec_id="pkg.composites.batch", run_id="r1",
                         params={}, label="batch", started_at=1.0, n_steps=0)
        cr.write_run_remote_sim_id(conn, "r1", 7)
    finally:
        conn.close()

    _patch_client(monkeypatch, payload={"lineages": "925:1000", "generations": "10:10",
                                        "overall": 60.7, "status": "RUNNING"})
    rows = si._read_runs_meta(db, str(db))
    r1 = next(r for r in rows if r["run_id"] == "r1")
    assert r1["progress_step"] == 925
    assert r1["n_steps"] == 1000
    assert r1["status"] == "running"
