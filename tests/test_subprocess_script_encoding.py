"""A debug artifact must never be able to fail the run it describes.

`run_composite_subprocess` saves a copy of the generated script for post-mortem
reading. That write had no `encoding`, so it used the LOCALE default — ascii in
a container — while the generated script carries non-ASCII (this module's own
f-string templates use em-dashes and arrows). Every hosted `run_study` therefore
died with

    UnicodeEncodeError: 'ascii' codec can't encode character '\\u2014'

before any simulation began. And the guard around it was `except OSError`, which
does not catch `UnicodeEncodeError` (a `ValueError`) — so the one error the write
actually threw was the one error the guard let through.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

import vivarium_workbench.lib.composite_subprocess as cs


def test_the_generated_script_really_does_contain_non_ascii() -> None:
    """The premise. If this module were pure ASCII the bug could not occur, and
    a future reader should be able to see that it is not."""
    src = Path(cs.__file__).read_text(encoding="utf-8")
    offenders = [c for c in src if ord(c) > 127]
    assert offenders, "no non-ASCII: this test's premise no longer holds"


def test_the_debug_write_specifies_utf8_not_the_locale() -> None:
    """Source-level, because the failure only reproduces under an ascii locale,
    which pytest cannot portably impose on an already-running interpreter.

    Matched over a WINDOW rather than a single line: `ruff format` splits the
    call across four lines, and the first version of this test asserted on one
    line and broke the moment the formatter touched it. A source-level assertion
    has to survive reformatting or it is a tripwire for the wrong thing.
    """
    src = Path(cs.__file__).read_text(encoding="utf-8")
    i = src.index('f"{run_id}.subprocess.py"')
    window = src[i : i + 200]
    assert 'encoding="utf-8"' in window, f"locale-dependent write near: {window[:120]!r}"


def test_the_debug_write_guard_catches_more_than_oserror() -> None:
    """`except OSError` was the actual defect: it made the write LOOK
    best-effort while letting UnicodeEncodeError through."""
    src = Path(cs.__file__).read_text(encoding="utf-8")
    i = src.index(".subprocess.py")
    guard = src[i : i + 400]
    assert "except Exception" in guard, "a best-effort artifact must not raise"
    assert "except OSError:" not in guard.split("except Exception")[0]


def test_writing_the_script_under_an_ascii_stream_would_have_failed() -> None:
    """Demonstrates the mechanism directly, so the fix is not just asserted.

    An ascii-encoded text stream is exactly what `open(..., "w")` yields under
    an ascii locale; writing the real script into one raises. The same content
    into a utf-8 stream does not.
    """
    script = "# generated — with an em-dash and an arrow →\nprint('hi')\n"

    ascii_stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    with pytest.raises(UnicodeEncodeError):
        ascii_stream.write(script)

    utf8_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    utf8_stream.write(script)  # must not raise


def test_a_unicode_error_is_not_an_oserror() -> None:
    """The precise reason `except OSError` did not save the run — worth pinning,
    because it reads like it should have."""
    assert not issubclass(UnicodeEncodeError, OSError)
    assert issubclass(UnicodeEncodeError, ValueError)


def test_the_state_write_is_also_explicit() -> None:
    """Safe today only because BigraphJSONEncoder escapes non-ASCII — a property
    of another package, not of this call site."""
    src = Path(cs.__file__).read_text(encoding="utf-8")
    i = src.index("os.fdopen(_state_fd")
    assert 'encoding="utf-8"' in src[i : i + 120], "locale-dependent state write"
