"""Which env-worker methods may run in a worker, and which are jobs.

Step 1 of REFACTOR-PLAN §2A.8 workstream 8 (design:
`docs/env-worker-routing.md`). §2A.7 already draws this line — the worker answers
**interactive** queries; simulations and heavy analyses are **jobs** — and the
distinction it draws is *method-shaped* (`registry_catalog` vs `run_study`), not
call-site-shaped. This module is that line, written down.

**Why classify by method rather than by call site.** `WorkerPool.call()` is the
single choke point all 25 call sites pass through, and it already receives the
method name. Classifying here is robust to an incomplete audit: a call site nobody
has traced still cannot route a simulation into a worker pod sized for
interaction. (Of the eight job-class call sites, four have been traced;
`investigation_steps` dispatches `run_study` with no run-target gate at all.)

**Viz is deliberately NOT classified.** §2A.7: *"Viz straddles — light preview may
stay an env-worker query, heavy post-run rendering moves into the job; split it
**as it comes, don't pre-design**."* So `render_viz_doc` / `viz_preview` /
`validate_generated_visualization` stay interactive until something real forces
the split. Pre-classifying them would be exactly the guess this design rules out.
"""
from __future__ import annotations

__all__ = ["JOB_CLASS_METHODS", "is_job_class"]

#: Methods that *execute the science* rather than answer a question about it.
#: These run a composite: a simulation, a post-run analysis pass, or an
#: investigation's study graph. Cost is unbounded by anything this layer can see
#: — a real study on this system declares 1000 seeds x 10 generations — so they
#: must not be routed to a worker sized for interactive queries.
JOB_CLASS_METHODS = frozenset({
    "run_study",                  # a study's simulation(s)
    "run_study_analyses",         # the post-run v2ecoli analysis pass
    "run_investigation_analysis",  # an investigation's analysis step
    "run_process",                # an arbitrary process/composite, N steps
})


def is_job_class(method: str) -> bool:
    """True when ``method`` executes science rather than answering about it.

    Unknown methods are treated as **interactive**, which is the safe default for
    a *lookup* and the reason ``tests/test_env_worker_routing.py`` asserts every
    declared capability is accounted for: a newly added heavy method should fail
    that test rather than silently inherit the interactive path.
    """
    return method in JOB_CLASS_METHODS
