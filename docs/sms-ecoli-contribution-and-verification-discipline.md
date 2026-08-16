# sms-ecoli Contribution and Verification Discipline

**Scope:** every fix, feature, or contribution intended for the delivered
simulator/workspace repo, `CovertLabEcoli/sms-ecoli` (private) — and every
claim that such a contribution is "verified" or "the deliverable is ready."
This lives in `vivarium-workbench/docs` because the workbench UI is the
instrument the verification half of this rule is run through: a `smscdk`-deployed
Workbench pointed at sms-ecoli is not just *a* way to check readiness, it is
the check.

## The rule, stated plainly

Treating sms-ecoli-related work as done requires two conditions, both true
at once, neither substitutable for the other:

- **Condition X — the write path.** The code change was made in
  `vivarium-collective/v2ecoli` first, as a real PR merged there, and only
  then ported into sms-ecoli via `scripts/sync_upstream.sh`. It was never
  committed directly to sms-ecoli's own tree.
- **Condition Y — the verification path.** The pass/fail signal used to
  close the item came from a real, fully-remote roundtrip against
  **sms-ecoli itself**, through the real `smscdk`-deployed vivarium-workbench
  UI. It did not come from v2ecoli, a local engine, or a pre-merge stack
  (e.g. `smsvpctest`) standing in for that final claim.

If either condition is missing, the verification is incomplete — no matter
how clean the other condition's own result looks. The rest of this doc
explains why both are load-bearing, and how to check them in practice.

## Condition X — the write path: v2ecoli first, always

Any contribution or fix intended to reach sms-ecoli MUST be made through a
PR and merge into `vivarium-collective/v2ecoli` (the public upstream)
first. Only once that merge is confirmed safe and ready to bring in does
`scripts/sync_upstream.sh` port it into `CovertLabEcoli/sms-ecoli`. The sync
itself is deterministic and push-button once it runs — but running it is a
deliberate decision made after the v2ecoli merge is trusted, never an
automatic reaction to one.

Do not commit original work directly to sms-ecoli's own tree — not on
`main`, not on a feature branch, not even for a change that "feels"
sms-ecoli-specific. If something genuinely needs sms-ecoli-only behavior,
that is a conversation to have explicitly with the workspace maintainers
first; it is never a default assumption.

**Why this is non-negotiable, not just tidy.** sms-ecoli is a deliberately
reduced subset of v2ecoli — pulled in by `sync_upstream.sh` and scoped down
by `scripts/descope.py` against `descope/manifest.yaml` — kept as a
near-mirror of v2ecoli on purpose, to keep the two in lockstep. The sync is
deterministic: every file outside a small pinned-ours allowlist (`README`,
`.gitignore`, `descope/`, `.claude/`, `.github/workflows/`,
`scripts/publish_dashboard.sh`) is replaced wholesale by v2ecoli's current
content on every sync run. Original work committed directly to sms-ecoli on
any file v2ecoli also owns has no protection from this — no merge conflict,
no warning, nothing to catch it. It is simply overwritten the next time the
sync runs.

This already happened for real. A checkpoint/resume feature was committed
directly to sms-ecoli's tree (sms-ecoli PR #39) and was silently dropped
when a later deterministic sync from v2ecoli (sync PR #44, bringing in
v2ecoli commit `049971a81`) brought the same file back in line with
v2ecoli's own — independently, already incomplete — port of the same
feature. The loss was silent: no failed test, no merge conflict, no error,
because the sync worked exactly as designed. The fix had to be redone
properly, through v2ecoli, and re-synced. The lesson generalizes: v2ecoli-first
is the only path that survives the sync mechanism sms-ecoli depends on to
stay current.

## Condition Y — the verification path: sms-ecoli + smscdk, always

Despite X, the actual deliverable is sms-ecoli itself, running through the
fully-remote vivarium-workbench UI deployed on the `smscdk` AWS GovCloud
stack — full stop.

Because sms-ecoli is kept as a near-mirror of v2ecoli via the sync mechanism
in Condition X, it is tempting to treat a clean, successful, fully-remote UI
roundtrip — running investigations, studies, or single simulations — against
v2ecoli as sufficient proof that the actual deliverable is ready.

**It is not.** Stated forcefully, because this is the part that gets
skipped:

> Verifiable and reproducible success of an end-to-end roundtrip via manual
> fully-remote-UI interactions — using v2ecoli as the tested target — does
> NOT equate to deliverable readiness. The same kind of fully-remote
> roundtrip success, but with sms-ecoli as the actual tested target, is one
> of many crucial, critical benchmarks of deliverable readiness — and it is
> not optional or substitutable.

A verification pass only counts toward "the deliverable is ready" when it is
run against sms-ecoli itself, through the real `smscdk`-deployed workbench
UI. It does **not** count when run against:

- v2ecoli, even via the identical UI flow with the identical steps,
- a local engine,
- a pre-merge test stack (e.g. `smsvpctest`) as a substitute for the final
  claim.

### Why Y carries a genuinely distinct risk, not just "wrong repo, same idea as X"

`CovertLabEcoli/sms-ecoli` is a **private** repository — access restricted to
a specific list (Stanford-affiliated collaborators, plus a small named group
of maintainers/contributors). This is unlike the public
`vivarium-collective/v2ecoli`, and it means sms-ecoli-targeted verification
exercises a real, distinct failure surface that v2ecoli-only testing
structurally cannot reach or catch at all:

- **Authentication and credential access** — a GitHub token or session that
  is actually valid for the private repo specifically. This exact class of
  gap has already recurred multiple times in this ecosystem's real history
  (a build-time `git clone` auth failure; separate `GITHUB_TOKEN`-missing
  gaps), always against the private repo specifically, and never
  reproducible by testing only against the public one.
- **Any future access-control or permissions surface** — anything gated on
  "is this identity allowed to see sms-ecoli at all," which has no analog
  when testing against a public repo.

A fully green result against the public repo says literally nothing about
whether these private-repo-specific paths still work. They are untested by
construction if verification only ever targets v2ecoli.

## How to apply

Before treating any implementation or fix as "verified" or "the deliverable
is ready," check both conditions explicitly:

1. **Was the actual code change made via the v2ecoli-first-then-synced path
   (X)?** — merged in `vivarium-collective/v2ecoli`, then ported with
   `scripts/sync_upstream.sh`, never committed directly to sms-ecoli.
2. **Was the actual pass/fail signal used to CLOSE the item produced by
   testing against real sms-ecoli + the real `smscdk`-deployed workbench,
   specifically (Y)?**

Either condition missing means the verification is incomplete — regardless
of how clean the other condition's own result looks. Neither condition can
substitute for the other; they answer different questions. X is about where
code originates and how it stays consistent with upstream long-term. Y is
about what "done" actually means for the shipped product.
