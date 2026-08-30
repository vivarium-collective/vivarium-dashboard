"""A failed launch must say WHY, not just that it failed.

`run_composite_subprocess` captures the child's stdout/stderr on a parse failure
and hands them up. `_run_study`'s `_launch` used to keep only
`resp.get("error")` — the string "could not parse run output" — and drop the
traceback that explains it.

The irony worth preserving: the `or resp` fallback WOULD have kept everything.
It never fired, because `error` is always truthy on that path. The degraded
branch was better than the primary one.
"""

from __future__ import annotations

from pathlib import Path

import vivarium_workbench.env_worker as ew


def _launch_source() -> str:
    """The whole of `_launch`, sliced by INDENTATION rather than a char count.

    The first version took `src[i : i + 1600]` and missed the truncation line by
    six characters. A fixed window is the same brittleness as asserting on a
    single line: it encodes today's formatting as a requirement. `_launch` is
    nested inside `_run_study`, so it is indented four and its body eight; the
    function ends at the next non-blank line back at four.
    """
    src = Path(ew.__file__).read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if l.strip().startswith("def _launch("))
    out = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("        "):
            break
        out.append(line)
    return "".join(out)


def test_stderr_is_carried_into_the_error_entry() -> None:
    body = _launch_source()
    assert '"stderr"' in body, "a failed launch must carry the child's stderr"


def test_the_output_is_tail_bounded_not_unbounded() -> None:
    """This lands in a JSONB column and in every status read of the task, so a
    multi-megabyte simulation log would be carried forever, repeatedly."""
    assert ew._LAUNCH_OUTPUT_TAIL > 0
    assert ew._LAUNCH_OUTPUT_TAIL <= 20_000, "too much to carry in a task record"
    assert "_LAUNCH_OUTPUT_TAIL" in _launch_source()


def test_the_tail_is_taken_from_the_END() -> None:
    """A traceback is at the tail. Truncating from the head would keep the
    least useful half of exactly the thing being carried."""
    body = _launch_source()
    assert "[-_LAUNCH_OUTPUT_TAIL:]" in body, "truncate from the end, not the start"


def test_absent_output_adds_no_empty_keys() -> None:
    """Most failures have no child output at all — a spec error, a missing
    variant. Those entries should not sprout empty stderr/stdout fields."""
    body = _launch_source()
    assert "if text:" in body, "only attach output that exists"


def test_the_error_string_is_still_the_primary_field() -> None:
    """The summary stays where callers already look; stderr is additive, not a
    replacement."""
    assert 'entry["error"] = resp.get("error") or resp' in _launch_source()


# --- the producer/consumer contract, which is what actually broke ------------


def _keys_returned_with_a_failure_status() -> set[str]:
    """Every dict key `composite_subprocess` ships alongside a 4xx/5xx.

    Parsed from the source rather than listed here, so a new diagnostic key
    added on the producing side is noticed on the consuming side instead of
    being silently dropped -- which is the exact failure this pins.
    """
    import ast
    from pathlib import Path

    import vivarium_workbench.lib.composite_subprocess as cs

    tree = ast.parse(Path(cs.__file__).read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        # the shape is: return ({...}, <status>)
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Tuple):
            continue
        if len(node.value.elts) != 2:
            continue
        body, status = node.value.elts
        if not isinstance(body, ast.Dict) or not isinstance(status, ast.Constant):
            continue
        if not isinstance(status.value, int) or status.value < 400:
            continue
        for k in body.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
    return keys


def _launch_code() -> str:
    """`_launch` with comments and docstrings REMOVED.

    Learned the hard way, immediately: the first version of the test below
    passed with the fix reverted, because the comment explaining the fix
    contained the very string it asserted on. A source-text test that reads its
    own prose proves nothing. Tokenize and drop anything that is not code.
    """
    import io
    import tokenize

    out: list[str] = []
    prev_end = (0, 0)
    tokens = list(tokenize.generate_tokens(io.StringIO(_launch_source()).readline))
    for i, tok in enumerate(tokens):
        if tok.type == tokenize.COMMENT:
            continue
        # A STRING that stands alone as its own statement is a docstring.
        if tok.type == tokenize.STRING:
            prev = tokens[i - 1] if i else None
            if prev is None or prev.type in (
                tokenize.INDENT,
                tokenize.NEWLINE,
                tokenize.NL,
            ):
                continue
        if tok.start[0] != prev_end[0]:
            out.append("\n")
        out.append(tok.string)
        prev_end = tok.end
    return " ".join(out)


def test_launch_reads_every_diagnostic_key_the_failing_path_emits() -> None:
    """The bug this file exists for, recurring one level down.

    The first pass carried "stderr" and "stdout". The 502 path -- the one a real
    failed run takes -- returns {"error": "run failed", "traceback": tb}. So a
    true partial harvested on dev still read

        {"error": "run failed", "stage": "variant:fails-bad-param", "status": 502}

    and nothing more: the traceback was in the response dict the whole time,
    under a key nobody read. Asserting against the producer's OWN keys is the
    only version of this test that cannot drift again.
    """
    body = _launch_code()
    emitted = _keys_returned_with_a_failure_status()
    # These are structural//already-handled, not diagnostics to forward.
    diagnostics = emitted - {"error", "simulation_id", "dry_run", "run_id"}
    assert diagnostics, "expected the producer to emit at least one diagnostic key"
    missing = {k for k in diagnostics if f'"{k}"' not in body}
    assert not missing, (
        f"_launch drops diagnostic keys the failing path emits: {sorted(missing)}"
    )


def test_traceback_specifically_is_carried() -> None:
    """Named on its own, because it is the key the 502 path uses and the one
    that was missing when a real partial came back undiagnosable."""
    assert '"traceback"' in _launch_code()
