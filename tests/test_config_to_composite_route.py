from pathlib import Path

from vivarium_workbench.lib.config_to_composite_views import build_config_composite


class _FakePool:
    def __init__(self, ret): self._ret = ret
    def call(self, ws, method, params):
        assert method == "config_to_composite"
        return self._ret


def test_build_returns_state_on_success(monkeypatch):
    import vivarium_workbench.lib.config_to_composite_views as m
    calls = []

    class _AssertingPool(_FakePool):
        def call(self, ws, method, params):
            calls.append(params)
            return super().call(ws, method, params)

    monkeypatch.setattr(m, "get_pool", lambda: _AssertingPool({"state": {"p": {"_type": "process"}}, "schema": {}}))
    body, status = build_config_composite(Path("/ws"), {"add_processes": ["p"]})
    assert status == 200 and body["kind"] == "config-composite"
    assert body["state"]["p"]["_type"] == "process"
    assert calls == [{"config": {"add_processes": ["p"]}}]


def test_build_501_when_translator_unavailable(monkeypatch):
    import vivarium_workbench.lib.config_to_composite_views as m
    monkeypatch.setattr(m, "get_pool", lambda: _FakePool({"__unavailable__": True}))
    body, status = build_config_composite(Path("/ws"), {})
    assert status == 501 and "error" in body


def test_build_422_on_non_object_config():
    body, status = build_config_composite(Path("/ws"), ["not", "a", "dict"])
    assert status == 422
