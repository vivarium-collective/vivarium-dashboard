"""Tests for `_attach_process_docs` contract + config_schema attachment (A2).

The env worker walks a composite-state document and, for each process/step node,
attaches:
  * ``config_schema`` — the resolved class's ``config_schema`` (JSON-sanitized),
  * ``_contract``     — the ``bigraph_schema.contract.resolve_contract`` result.

For a ``Requester`` / ``Evolver`` partition wrapper the contract is resolved from
the WRAPPED ``PartitionedProcess`` (carried in ``config['process']``) and tagged
with ``role: "request" | "execute"``. Everything is additive and never raises —
an unresolvable address yields a valid document with no contract/schema keys.
"""
from __future__ import annotations

import pytest

from vivarium_workbench import env_worker


class FakePlain:
    """A plain process class with a config schema and a math description."""

    config_schema = {"rate": "float", "target": "string"}
    description = "Governs species X.\n\ndX/dt = -k * X"


class FakeScience:
    """The real science class wrapped by a partition Requester/Evolver."""

    config_schema = {"kcat": "float"}
    description = "Catalyzes S to P.\n\nv = kcat * E"


class Requester:
    """A generic partition wrapper (name must be literally ``Requester``)."""

    config_schema = {"process": "node"}


class Evolver:
    """A generic partition wrapper (name must be literally ``Evolver``)."""

    config_schema = {"process": "node"}


def _fake_resolver(mapping):
    def resolve(address):
        return mapping.get(address)
    return resolve


def test_plain_process_gets_config_schema_and_contract(monkeypatch):
    monkeypatch.setattr(
        env_worker, "_pd_class_for_address",
        _fake_resolver({"local:fake.FakePlain": FakePlain}),
    )
    doc = {
        "state": {
            "proc": {
                "_type": "process",
                "address": "local:fake.FakePlain",
                "config": {},
            }
        }
    }
    env_worker._attach_process_docs(doc)
    node = doc["state"]["proc"]
    assert node["config_schema"] == {"rate": "float", "target": "string"}
    assert "_contract" in node
    assert node["_contract"]["math"] == ["dX/dt = -k * X"]
    assert node["_contract"]["summary"] == "Governs species X."
    assert "role" not in node["_contract"]


def test_requester_wrapper_resolves_wrapped_science_with_role(monkeypatch):
    monkeypatch.setattr(
        env_worker, "_pd_class_for_address",
        _fake_resolver({"local:v2ecoli.steps.partition.Requester": Requester}),
    )
    doc = {
        "state": {
            "sci_requester": {
                "_type": "step",
                "address": "local:v2ecoli.steps.partition.Requester",
                # wrapped science object carried as a config instance
                "config": {"process": FakeScience()},
            }
        }
    }
    env_worker._attach_process_docs(doc)
    node = doc["state"]["sci_requester"]
    assert "_contract" in node
    assert node["_contract"]["math"] == ["v = kcat * E"]
    assert node["_contract"]["role"] == "request"


def test_evolver_wrapper_resolves_via_sibling_process_store(monkeypatch):
    # The serialized shape: config is empty; the wrapped process lives in the
    # sibling `process` store keyed by base name, as a repr string in a 1-list.
    monkeypatch.setattr(
        env_worker, "_pd_class_for_address",
        _fake_resolver({
            "local:v2ecoli.steps.partition.Evolver": Evolver,
            "tests.test_process_docs_attach.FakeScience": FakeScience,
        }),
    )
    doc = {
        "state": {
            "agents": {
                "0": {
                    "ecoli-x_evolver": {
                        "_type": "step",
                        "address": "local:v2ecoli.steps.partition.Evolver",
                        "config": {},
                    },
                    "process": {
                        "ecoli-x": [
                            "<tests.test_process_docs_attach.FakeScience "
                            "object at 0x1040abcd0>"
                        ],
                    },
                }
            }
        }
    }
    env_worker._attach_process_docs(doc)
    node = doc["state"]["agents"]["0"]["ecoli-x_evolver"]
    assert "_contract" in node
    assert node["_contract"]["math"] == ["v = kcat * E"]
    assert node["_contract"]["role"] == "execute"


def test_unresolvable_address_yields_document_without_keys(monkeypatch):
    monkeypatch.setattr(
        env_worker, "_pd_class_for_address",
        _fake_resolver({}),  # nothing resolves
    )
    doc = {
        "state": {
            "ghost": {
                "_type": "process",
                "address": "local:nonexistent.Thing",
                "config": {},
            }
        }
    }
    # must not raise
    env_worker._attach_process_docs(doc)
    node = doc["state"]["ghost"]
    assert "_contract" not in node
    assert "config_schema" not in node
    assert "doc" not in node
