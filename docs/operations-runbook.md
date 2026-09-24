# Operations runbook

A structured checklist for the person on call, not a symptom lookup (see
`docs/troubleshooting.md` for that). Written for "result-publication day"
or any other expected-high-stakes, expected-high-traffic event.

## Before the event

- [ ] `make backup` — a fresh backup taken shortly before matters more
      than one taken days ago.
- [ ] Confirm every managed server shows **online** on the dashboard's
      Servers page. Investigate any that don't now, not during the event.
- [ ] Confirm the application(s) expecting peak traffic are scaled to
      their intended replica count *before* load arrives — scaling up
      reactively during a real traffic spike works (Healer's scale-up
      health-gates each new instance before adding it to the gateway, see
      `docs/scaling.md`), but costs you the time it takes to build/start/
      health-check each new instance meanwhile.
- [ ] Run (or re-run) `scripts/load_test_erp.sh` against the real target
      at the expected peak concurrency — see `docs/load-testing.md` — and
      confirm the instance table stays `healthy` throughout and
      immediately after.
- [ ] Confirm TLS certificates referenced by the application's domain
      config aren't expiring during or shortly after the event
      (`docs/security-boundaries.md` §5 — Healer only reads existing
      CRT/KEY paths, it doesn't track expiry itself; check manually,
      e.g. `openssl x509 -enddate -noout -in <cert>`).
- [ ] Know where the audit log is (dashboard, Administrator role) and who
      has access to it — you'll want it if anything needs to be
      reconstructed afterward.

## During the event

- [ ] Watch the Health page (`/health`) — CPU/RAM/disk summary cards per
      server, and any self-healing notifications. A notification means
      self-healing already gave up on an instance after exhausting its
      configured restart attempts (`docs/self-healing.md`) — that needs a
      human now, it won't retry itself further.
- [ ] Watch the Overview page's "Deployments in progress" /
      "Recent failed deployments" counts.
- [ ] If an instance needs manual intervention, use the Application
      Details page's per-instance Restart/Stop buttons (Phase 14) rather
      than touching the managed server directly — Healer's own state
      needs to stay in sync with what's actually running.
- [ ] If a bad release genuinely needs to come back, use the Releases
      panel's rollback control (health-gated, atomic Nginx switch,
      `docs/blue-green-deployment.md`) rather than a manual redeploy.

## If something goes wrong

1. **A single instance is unhealthy**: check the dashboard's Instance
   table for its `failure_reason`. Self-healing (Phase 10) already
   attempted recovery automatically for anything that reached
   `unhealthy` — a notification means it gave up; use Restart, or Stop
   and let the next scale-up create a fresh replacement.
2. **A release is bad**: roll back through the dashboard (see above).
   The previous release was never removed from traffic during a failed
   switch (`docs/blue-green-deployment.md`'s core guarantee) — you are
   not starting from an outage, you're recovering from a release you'd
   like to stop using.
3. **The Control Plane itself is unhealthy/restarted**: already-deployed
   applications keep serving traffic unaffected (README's "Two paths, kept
   separate") — this is not user-facing on its own. On restart, check the
   startup logs for "startup recovery: reconciled N stuck deployment(s)"
   (Phase 15's `reconcile_service`) to see whether anything was mid-flight
   when it went down, and re-trigger that operation manually once the
   Control Plane is back.
4. **The database needs restoring**: `docs/backup-and-restore.md`'s
   recovery section. Stop `control-plane`/`worker` first.
5. **A server's Agent is compromised or the server is being decommissioned
   mid-event**: `POST /servers/{id}/agent/revoke` (Administrator role,
   Phase 15) immediately disconnects it and invalidates its credential.

## After the event

- [ ] `make backup` again — a clean post-event snapshot.
- [ ] Review the audit log for the event window.
- [ ] Review the health-check/self-healing notifications list for anything
      that fired and self-resolved — worth understanding even if nothing
      needed a human at the time.
- [ ] Scale back down if replicas were raised specifically for the event.
- [ ] Write down anything from `docs/troubleshooting.md` this event should
      have covered but didn't — that gap is real, worth closing before the
      next event.
