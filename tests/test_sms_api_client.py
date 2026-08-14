import io
import json
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from vivarium_workbench.lib.sms_api_client import (
    SmsApiClient,
    SmsApiError,
    chain_dispatch_timeout,
)


class _Resp(io.BytesIO):
    status = 200

    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@contextmanager
def _patch_urlopen(monkeypatch, capture, payload, status=200):
    def fake_urlopen(req, timeout=None):
        capture["url"] = req.full_url
        capture["method"] = req.get_method()
        capture["body"] = req.data
        capture["timeout"] = timeout
        if status != 200:
            from urllib.error import HTTPError

            raise HTTPError(req.full_url, status, "err", {}, io.BytesIO(b"boom"))
        return _Resp(payload, status)

    monkeypatch.setattr("vivarium_workbench.lib.sms_api_client.urlopen", fake_urlopen)
    yield


def test_latest_simulator_builds_query(monkeypatch):
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"git_commit_hash": "abc123"}):
        c = SmsApiClient("http://h:8080")
        out = c.latest_simulator("https://github.com/x/v2ecoli", "master")
    assert out["git_commit_hash"] == "abc123"
    assert cap["url"].startswith("http://h:8080/core/v1/simulator/latest?")
    assert "git_branch=master" in cap["url"]
    assert "git_repo_url=https%3A%2F%2Fgithub.com%2Fx%2Fv2ecoli" in cap["url"]


def test_observables_repeats_names_param(monkeypatch):
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"time": [0.0], "series": {"mass": [1.0]}}):
        c = SmsApiClient("http://h:8080")
        out = c.observables(49, ["mass", "volume"], seed=0)
    assert out["series"]["mass"] == [1.0]
    assert "/api/v1/simulations/49/observables?" in cap["url"]
    assert "names=mass%2Cvolume" in cap["url"]
    assert "seed=0" in cap["url"]


def test_non_200_raises(monkeypatch):
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {}, status=404):
        c = SmsApiClient("http://h:8080")
        with pytest.raises(SmsApiError):
            c.simulation_status(999)


def test_run_simulation_query_and_repeated_observables(monkeypatch):
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"database_id": 50}):
        c = SmsApiClient("http://h:8080")
        out = c.run_simulation(
            simulator_id=15, num_generations=1, num_seeds=1, run_parca=True,
            observables=["mass", "volume"], experiment_id="exp1",
        )
    assert out["database_id"] == 50
    assert cap["method"] == "POST"
    qs = parse_qs(urlsplit(cap["url"]).query)
    assert qs["simulator_id"] == ["15"]
    assert qs["num_generations"] == ["1"]
    assert qs["run_parca"] == ["True"]
    assert qs["observables"] == ["mass", "volume"]  # repeated key, not comma-joined
    assert qs["experiment_id"] == ["exp1"]


def test_run_simulation_sends_analysis_options_as_json_body(monkeypatch):
    """analysis_options is a Pydantic model with no Query()/Body() wrapper on
    the sms-api route — FastAPI reads a bare model param from the JSON
    request body, not the query string (unlike every other run_simulation
    param above)."""
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"database_id": 51}):
        c = SmsApiClient("http://h:8080")
        out = c.run_simulation(
            simulator_id=15, num_generations=1, num_seeds=1, run_parca=True,
            observables=["mass"], analysis_options={"multiseed": {"ecocyc_table": {}}},
        )
    assert out["database_id"] == 51
    assert json.loads(cap["body"].decode()) == {
        "analysis_options": {"multiseed": {"ecocyc_table": {}}}
    }
    qs = parse_qs(urlsplit(cap["url"]).query)
    assert "analysis_options" not in qs  # never in the query string


def test_run_simulation_omits_json_body_when_no_analysis_options(monkeypatch):
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"database_id": 52}):
        c = SmsApiClient("http://h:8080")
        c.run_simulation(
            simulator_id=15, num_generations=1, num_seeds=1, run_parca=True,
            observables=["mass"],
        )
    assert cap["body"] is None


# ---------------------------------------------------------------------------
# Backlog item 51: chain-dispatch timeout scaling
#
# A canonical 1000-seed x 10-generation dispatch submits 10,000 individual AWS
# Batch jobs synchronously inside ONE run_simulation() call (real production
# incident, 2026-08-14) -- the flat 30s constructor timeout fires long before
# that finishes, even though the request is actually succeeding server-side.
# ---------------------------------------------------------------------------

def test_chain_dispatch_timeout_scales_with_job_count():
    """The real derivation, called directly (not hand-duplicated arithmetic):
    a large campaign must get a materially larger timeout than a tiny one, and
    the large value must comfortably clear the real ~900s (~15 min) wall-clock
    time the 2026-08-14 production 1000x10 dispatch actually took -- otherwise
    this exact bug reproduces."""
    small = chain_dispatch_timeout(num_seeds=1, num_generations=1)
    large = chain_dispatch_timeout(num_seeds=1000, num_generations=10)
    assert large > small
    assert large - small > 300.0  # "materially larger", not a rounding-error bump
    assert large > 900.0  # clears the real observed wall-clock time with margin
    assert small < 31.0  # a single-job request keeps ~today's flat 30s behavior


def test_chain_dispatch_timeout_is_monotonic_in_job_count():
    """More jobs never yields a smaller timeout, across a spread of sizes."""
    sizes = [(1, 1), (10, 1), (10, 5), (100, 5), (500, 10), (1000, 10)]
    timeouts = [chain_dispatch_timeout(s, g) for s, g in sizes]
    assert timeouts == sorted(timeouts)


def test_run_simulation_threads_scaled_timeout_into_real_urlopen_call(monkeypatch):
    """run_simulation() must actually PASS the scaled value down to the real
    HTTP call, not just compute and discard it. Only urlopen -- the actual
    socket/network boundary -- is faked here; run_simulation(), _post(), and
    chain_dispatch_timeout() all execute for real, so this proves the real
    plumbing rather than asserting against a mock of the layer in doubt."""
    cap_small: dict = {}
    with _patch_urlopen(monkeypatch, cap_small, {"database_id": 60}):
        c = SmsApiClient("http://api:8000")  # constructor default timeout=30.0
        c.run_simulation(
            simulator_id=1, num_generations=1, num_seeds=1, run_parca=True,
            observables=["mass"],
        )
    cap_large: dict = {}
    with _patch_urlopen(monkeypatch, cap_large, {"database_id": 61}):
        c = SmsApiClient("http://api:8000")
        c.run_simulation(
            simulator_id=1, num_generations=10, num_seeds=1000, run_parca=True,
            observables=["mass"],
        )
    assert cap_large["timeout"] > cap_small["timeout"]
    # Exactly what the real function computes -- not an approximation.
    assert cap_small["timeout"] == chain_dispatch_timeout(num_seeds=1, num_generations=1)
    assert cap_large["timeout"] == chain_dispatch_timeout(num_seeds=1000, num_generations=10)


def test_post_connection_failure_message_has_no_tunnel_claim(monkeypatch):
    """Regression: workbench -> viva-api is a plain in-cluster ClusterIP call
    (http://api:8000) with no SSM tunnel involved at all, so a connection
    failure from run_simulation() must not claim one exists (real bug found
    live during the 2026-08-14 incident that motivated this whole fix)."""
    def fake_urlopen(req, timeout=None):
        raise URLError("Connection refused")

    monkeypatch.setattr("vivarium_workbench.lib.sms_api_client.urlopen", fake_urlopen)
    c = SmsApiClient("http://api:8000")
    with pytest.raises(SmsApiError) as exc_info:
        c.run_simulation(
            simulator_id=1, num_generations=1, num_seeds=1, run_parca=True,
            observables=["mass"],
        )
    msg = str(exc_info.value)
    assert "unreachable" in msg  # keeps working with existing "unreachable" classifiers
    assert "tunnel" not in msg.lower()  # the specific wrong claim this fixes


def test_upload_simulator_sends_json_body(monkeypatch):
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"database_id": 16, "status": "running"}):
        c = SmsApiClient("http://h:8080")
        out = c.upload_simulator({"git_commit_hash": "abc", "git_repo_url": "u", "git_branch": "b"}, force=True)
    assert out["database_id"] == 16
    assert cap["method"] == "POST"
    assert json.loads(cap["body"].decode())["git_commit_hash"] == "abc"
    assert "force=true" in cap["url"]


def test_run_analysis_sends_modules_as_query_json(monkeypatch):
    """modules is read via a query param on sms-api's endpoint (?modules=<json>),
    not a request body -- unlike run_simulation's analysis_options."""
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"job_id": "ana-exp1", "analysis_name": "analysis-exp1-ab12"}):
        c = SmsApiClient("http://h:8080")
        out = c.run_analysis(115, {"multiseed": {"doubling_time_distribution": {}}})
    assert out["job_id"] == "ana-exp1"
    assert cap["method"] == "POST"
    assert cap["body"] is None
    assert "/api/v1/simulations/115/analysis?" in cap["url"]
    qs = parse_qs(urlsplit(cap["url"]).query)
    assert json.loads(qs["modules"][0]) == {"multiseed": {"doubling_time_distribution": {}}}


def test_composite_resolve_posts_to_simulator_route(monkeypatch):
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"name": "c", "parameters": {}, "state": {}}):
        c = SmsApiClient("http://x")
        out = c.composite_resolve(66, "pkg.composites.cell", {"k": 5})
    assert cap["url"] == "http://x/core/v1/simulator/66/composite-resolve"
    assert cap["method"] == "POST"
    assert json.loads(cap["body"]) == {"composite_ref": "pkg.composites.cell", "overrides": {"k": 5}}
    assert out["name"] == "c"


def test_download_data_streams_to_file(monkeypatch, tmp_path):
    cap = {}
    payload = b"\x1f\x8b\x08fake-gzip-bytes"

    class _RawResp:
        status = 200

        def __init__(self):
            self._b = io.BytesIO(payload)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._b.close()

        def read(self, n=-1):
            return self._b.read(n)

    def fake_urlopen(req, timeout=None):
        cap["url"] = req.full_url
        cap["method"] = req.get_method()
        return _RawResp()

    monkeypatch.setattr("vivarium_workbench.lib.sms_api_client.urlopen", fake_urlopen)
    c = SmsApiClient("http://h:8080")
    out = c.download_data(49, tmp_path)
    assert out == tmp_path / "sim_49.tar.gz"
    assert out.read_bytes() == payload
    assert cap["method"] == "POST"
    assert cap["url"] == "http://h:8080/api/v1/simulations/49/data"


def test_analysis_status_gets_by_database_id(monkeypatch):
    cap = {}
    with _patch_urlopen(monkeypatch, cap, {"id": 7, "status": "completed", "error_log": None}):
        c = SmsApiClient("http://h:8080")
        out = c.analysis_status(7)
    assert out["status"] == "completed"
    assert cap["method"] == "GET"
    assert cap["url"] == "http://h:8080/analyses/7/status"
