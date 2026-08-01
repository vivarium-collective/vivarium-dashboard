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


def test_process_run_command_is_a_single_python_line():
    cmd = process_run_command("pbg_demo.processes.Grow", "pbg_demo")
    # Single line, uses the workspace core, resolves the class by its address,
    # and references the address for the fallback match + assert message.
    assert cmd.startswith('python3 -c "')
    assert cmd.endswith('"')
    assert "\n" not in cmd
    assert "import pbg_demo.core as _m" in cmd
    assert "build_core()" in cmd
    assert "'pbg_demo.processes.Grow'" in cmd  # full address
    assert "'Grow'" in cmd  # short-name fallback
    # local: protocol addresses strip to the bare name for the short match.
    cmd2 = process_run_command("local:RAMEmitter", "pbg_demo")
    assert "'RAMEmitter'" in cmd2
    assert process_run_command("", "pbg_demo") == ""
    assert process_run_command("local:X", "") == ""
