"""Tests for the ui.* deployment-config layer (workbench issue #471).

The behaviours that matter most here are the *negative* ones: with no
deployment config present, resolution must be identical to reading
workspace.yaml directly, because that is what keeps local development working
with no configuration at all. The viewer plugins self-gate on these keys and
fail **silently** (a launcher simply does not render), so a regression would be
invisible without these tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib.deploy_config import (
    DEPLOY_CONFIG_ENV_SUFFIX,
    deploy_ui,
    resolve_ui_config,
    workspace_ui,
)

ENV = "VIVARIUM_WORKBENCH_" + DEPLOY_CONFIG_ENV_SUFFIX

# The real local-dev values committed in v2ecoli/sms-ecoli workspace.yaml.
LOCAL_DEV_UI = {
    "ptools_server_url": "http://localhost:1555",
    "dashboard_public_base_url": "http://host.docker.internal:8771",
    "ptools_data_dir": "/ptools-data",
}


def _write(path: Path, ui: dict) -> Path:
    path.write_text(yaml.safe_dump({"ui": ui}, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    _write(tmp_path / "workspace.yaml", dict(LOCAL_DEV_UI))
    return tmp_path


@pytest.fixture(autouse=True)
def _no_deploy_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with no deployment config unless it sets one."""
    monkeypatch.delenv(ENV, raising=False)


class TestNoDeploymentConfig:
    """Local dev: the workspace's own ui: block is the whole answer."""

    def test_workspace_values_survive_untouched(self, ws: Path) -> None:
        assert resolve_ui_config(ws) == LOCAL_DEV_UI

    def test_local_dev_ptools_pair_is_intact(self, ws: Path) -> None:
        # Guards the exact values a developer needs against a local ptools
        # container; deleting them from a science repo must fail a test, not
        # silently hide the viewer.
        resolved = resolve_ui_config(ws)
        assert resolved["ptools_server_url"] == "http://localhost:1555"
        assert resolved["dashboard_public_base_url"] == "http://host.docker.internal:8771"

    def test_empty_when_no_workspace_yaml(self, tmp_path: Path) -> None:
        assert resolve_ui_config(tmp_path) == {}

    def test_deploy_ui_is_empty(self) -> None:
        assert deploy_ui() == {}


class TestDeploymentOverlay:
    def test_deployment_wins(self, ws: Path, tmp_path: Path,
                             monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _write(tmp_path / "deploy.yaml", {"ptools_server_url": "http://site:8080"})
        monkeypatch.setenv(ENV, str(cfg))
        resolved = resolve_ui_config(ws)
        assert resolved["ptools_server_url"] == "http://site:8080"
        # untouched keys still come from the workspace
        assert resolved["ptools_data_dir"] == "/ptools-data"

    def test_null_unsets(self, ws: Path, tmp_path: Path,
                         monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _write(tmp_path / "deploy.yaml", {"ptools_data_dir": None})
        monkeypatch.setenv(ENV, str(cfg))
        # This is what replaces the seed script's ui.pop("ptools_data_dir").
        assert "ptools_data_dir" not in resolve_ui_config(ws)

    def test_nested_map_replaces_not_deep_merged(self, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        _write(ws / "workspace.yaml", {"viz_viewer_urls": {"ecoli_3d": "a", "initial": "b"}})
        cfg = _write(tmp_path / "deploy.yaml", {"viz_viewer_urls": {"ecoli_3d": "z"}})
        monkeypatch.setenv(ENV, str(cfg))
        # Whole-map replacement: a site declaring the key owns the entire set,
        # so it can *remove* an entry the workspace declares.
        assert resolve_ui_config(ws)["viz_viewer_urls"] == {"ecoli_3d": "z"}

    def test_adds_keys_absent_from_the_workspace(self, ws: Path, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _write(tmp_path / "deploy.yaml", {"ptools_internal_url": "http://ptools:1555"})
        monkeypatch.setenv(ENV, str(cfg))
        assert resolve_ui_config(ws)["ptools_internal_url"] == "http://ptools:1555"


class TestDegradesNeverRaises:
    """A broken deployment config must fall back, not take the server down."""

    def test_env_points_at_a_missing_file(self, ws: Path, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV, str(tmp_path / "nope.yaml"))
        assert resolve_ui_config(ws) == LOCAL_DEV_UI

    def test_malformed_yaml(self, ws: Path, tmp_path: Path,
                            monkeypatch: pytest.MonkeyPatch) -> None:
        bad = tmp_path / "deploy.yaml"
        bad.write_text("ui: [this is: not: a mapping\n", encoding="utf-8")
        monkeypatch.setenv(ENV, str(bad))
        assert resolve_ui_config(ws) == LOCAL_DEV_UI

    def test_ui_is_not_a_mapping(self, ws: Path, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "deploy.yaml"
        cfg.write_text(yaml.safe_dump({"ui": "a string"}), encoding="utf-8")
        monkeypatch.setenv(ENV, str(cfg))
        assert resolve_ui_config(ws) == LOCAL_DEV_UI

    def test_empty_env_value_is_treated_as_unset(self, ws: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV, "   ")
        assert resolve_ui_config(ws) == LOCAL_DEV_UI

    def test_a_raising_source_is_skipped(self, ws: Path) -> None:
        def boom() -> dict:
            raise RuntimeError("source exploded")

        resolved = resolve_ui_config(
            ws, sources=[lambda: workspace_ui(ws), boom, lambda: {"composite_view": "x"}]
        )
        assert resolved["composite_view"] == "x"
        assert resolved["ptools_server_url"] == "http://localhost:1555"


class TestOrderedSources:
    """The chain is an ordered list so a per-user layer can slot in later."""

    def test_last_source_wins(self, tmp_path: Path) -> None:
        resolved = resolve_ui_config(
            tmp_path,
            sources=[lambda: {"k": "project"}, lambda: {"k": "user"}, lambda: {"k": "site"}],
        )
        assert resolved["k"] == "site"

    def test_middle_layer_can_override_and_be_overridden(self, tmp_path: Path) -> None:
        resolved = resolve_ui_config(
            tmp_path,
            sources=[lambda: {"a": 1, "b": 1}, lambda: {"a": 2, "b": 2}, lambda: {"a": 3}],
        )
        assert resolved == {"a": 3, "b": 2}
