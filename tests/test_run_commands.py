from vivarium_workbench.lib.run_commands import (
    composite_run_command,
    investigation_run_command,
    process_run_command,
    study_run_commands,
)


def test_baseline_and_variant_commands():
    spec = {
        "name": "demo-study",
        "conditions": {
            "baseline": {"composite": "pkg.composites.baseline"},
            "variants": [
                {"name": "knockout", "parameter_overrides": {"k": 1}},
            ],
        },
        "simulation_set": [
            {"name": "ensemble-a", "base_model": "baseline"},
        ],
    }
    cmds = study_run_commands(spec, "demo-study")
    assert cmds["baseline"] == "vwb run study demo-study"
    assert cmds["variants"] == [
        {"name": "knockout",
         "cmd": "vwb run study demo-study --variant knockout"}
    ]
    assert cmds["simulations"] == [
        {"name": "ensemble-a", "cmd": "vwb run study demo-study"}
    ]
    assert cmds["rerun_hint"] == "vwb rerun <run-id>"


def test_no_variants_no_simset():
    cmds = study_run_commands({"name": "s"}, "s")
    assert cmds["baseline"] == "vwb run study s"
    assert cmds["variants"] == []
    assert cmds["simulations"] == []


def test_composite_run_command_with_and_without_steps():
    assert (
        composite_run_command({"id": "pkg.composites.baseline", "default_n_steps": 100})
        == "vwb run composite pkg.composites.baseline --steps 100"
    )
    # No positive default → omit --steps (CLI supplies its own default).
    assert (
        composite_run_command({"id": "pkg.composites.baseline"})
        == "vwb run composite pkg.composites.baseline"
    )
    assert composite_run_command({"id": "pkg.composites.baseline", "default_n_steps": 0}) \
        == "vwb run composite pkg.composites.baseline"
    # A bool is an int subclass but never a step count.
    assert composite_run_command({"id": "c", "default_n_steps": True}) == "vwb run composite c"
    assert composite_run_command({}) == ""


def test_investigation_run_command():
    assert investigation_run_command("dnaa-replication") == "vwb run investigation dnaa-replication"
    assert investigation_run_command("") == ""
    assert investigation_run_command(None) == ""


def test_study_run_commands_with_steps():
    spec = {
        "name": "s",
        "conditions": {"variants": [{"name": "ko"}]},
        "simulation_set": [{"name": "sim-a"}],
    }
    c = study_run_commands(spec, "s", steps=2700)
    assert c["baseline"] == "vwb run study s --steps 2700"
    assert c["variants"] == [{"name": "ko", "cmd": "vwb run study s --steps 2700 --variant ko"}]
    assert c["simulations"] == [{"name": "sim-a", "cmd": "vwb run study s --steps 2700"}]
    # Non-positive / bool / None → no --steps (backward compatible).
    assert study_run_commands(spec, "s")["baseline"] == "vwb run study s"
    assert study_run_commands(spec, "s", steps=0)["baseline"] == "vwb run study s"
    assert study_run_commands(spec, "s", steps=True)["baseline"] == "vwb run study s"


def test_investigation_run_command_with_steps():
    assert investigation_run_command("colonies", steps=2700) == "vwb run investigation colonies --steps 2700"
    assert investigation_run_command("colonies", steps=None) == "vwb run investigation colonies"
    assert investigation_run_command("colonies", steps=0) == "vwb run investigation colonies"


def test_process_run_command():
    assert (
        process_run_command("pbg_demo.processes.Grow")
        == "vwb run process pbg_demo.processes.Grow"
    )
    # local: protocol addresses are passed through verbatim.
    assert process_run_command("local:RAMEmitter") == "vwb run process local:RAMEmitter"
    assert process_run_command("") == ""
    assert process_run_command("  ") == ""
