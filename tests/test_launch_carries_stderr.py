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
