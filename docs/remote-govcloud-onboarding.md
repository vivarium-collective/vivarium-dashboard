# Remote GovCloud Onboarding

**Audience:** a teammate (e.g. Chris) getting set up to run the Workbench against the **remote
GovCloud backend** for the first time, instead of (or in addition to) the local engine.

**What this is:** the Workbench can point at a remote backend — **viva-api** (the repo was
renamed from `sms-api` on 2026-08-03; same service, same API, GitHub redirects the old URL) —
to build pinned `repo@commit` simulator images and run large batches on GovCloud (Ray → AWS
Batch → zarr/parquet on S3) instead of your laptop. Everything still lands back in your
workspace as a normal study run you browse the same way as a local one.

---

## 0. Prerequisites

- **AWS SSO access to the `stanford-sso` GovCloud profile**, with permission to reach the
  internal ALB via SSM port-forward. If you already have credentials from the AWS Batch work
  with Ryan, you very likely already have this — confirm with Alex rather than assume.
- A local **Workbench** checkout with a workspace to serve (`vivarium-workbench serve --workspace .`
  already working locally — do that first if you haven't).
- `sms-cdk` checked out as a sibling repo (the tunnel script lives there).

---

## 1. Authenticate + open the tunnel

The remote endpoint sits behind an internal load balancer — you reach it via an SSM
port-forward, not a public URL.

```bash
aws sso login --profile stanford-sso

AWS_PROFILE=stanford-sso AWS_DEFAULT_REGION=us-gov-west-1 \
  sms-cdk/scripts/ptools-proxy.sh -s smsvpctest      # forwards localhost:8080
```

Keep that running in its own terminal for the whole session — SSO tokens expire every few
hours, and the tunnel drops with them. If requests suddenly start failing, `aws sso login`
again and restart the proxy first, before assuming anything is actually broken.

## 2. Point the Workbench at it

```bash
VIVA_API_BASE=http://localhost:8080 vivarium-workbench serve --workspace .
```

(`SMS_API_BASE` also still works, as a fallback alias — same variable, either name is fine.)
It defaults to `http://localhost:8080` anyway, so if the tunnel is already up on that port you
can usually just leave the var unset.

## 3. Using it

Open the workbench UI → the **Source** panel:

- A health row up top shows **reachable ✓ / unreachable ✗** against the tunnel, with the
  backend's version — check this *before* trying to switch, it tells you immediately whether
  the tunnel is actually up rather than letting you hit a confusing timeout later.
- The **"sms-api builds"** scope (yes, still labeled `sms-api` in the UI today — cosmetic only,
  same backend as `viva-api`) lists simulator versions already built. **Build via sms-api**
  registers a new `repo@commit` on demand if the one you want isn't listed yet.
- Once a build is selected/registered, submit runs as normal — they execute remotely and land
  back as study runs in your workspace, with status polled live in the UI.

---

## What's more solid than it used to be

The remote-switch path got hardened specifically so people outside the core team could use it
(workbench PR #630, merged into v0.3.7+; current prod is v0.3.9+):

- The health check above — you see reachability before you commit to a switch, not after.
- Long-running remote submissions tolerate transient tunnel blips (bounded retry) instead of
  dying on the first hiccup.
- Switching builds has a real timeout with a visible countdown and a Cancel button, instead of
  hanging indefinitely.
- Failures surface an actual reason ("tunnel down" / "workspace not pushed" / etc.) instead of a
  raw stack trace.

## Heads-up / known limitations

- **There is currently no application-level auth on the remote build/run routes.** The tunnel
  itself — i.e. your AWS SSO permissions — is the entire access boundary today. That's a known,
  deliberate gap (optional bearer-token auth is the tracked follow-up), not an oversight; just be
  aware that "can reach the tunnel" == "can build and run things," full stop.
- The UI still says `sms-api` in a few places (health text, button labels, the builds-scope tab).
  That's leftover copy from before the repo rename — same backend, no functional difference.

## If something's not working

Restart the tunnel and re-auth first (see step 1) — that's the fix more often than not. Beyond
that, ping Alex or Eran directly rather than debugging blind; this path is still actively evolving.
