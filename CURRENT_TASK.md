## DONE | Onboarding & live-ops doc improvements

**Started:** 2026-04-08T15:19Z
**Completed:** 2026-04-08T15:24Z
**Plan:** [implementation_plan.md](implementation_plan.md)

### What was built
Docs-only improvements for onboarding and live-ops clarity. No code changes.

Most of the planned content (URL routing table, ContextForge section, 502 troubleshooting, verification steps) was already present from the SSE migration work. This pass:
- Fixed stale "Traefik" reference in README.md docs table → "Cloudflare Tunnel"
- Fixed duplicate/out-of-order gotcha numbering (was 1,2,3,5,4,4,5,6,7,8,9,10,11,12,13 → now 1–15 sequential)

### Files changed
| File | Change |
|---|---|
| `README.md` | Fixed docs table: "Traefik" → "Cloudflare Tunnel" |
| `docs/gotchas.md` | Renumbered all 15 sections sequentially (fixed duplicates and out-of-order) |

### Files reviewed (no changes needed)
| File | Reason |
|---|---|
| `docs/architecture.md` | Already has Cloudflare Tunnel diagram, ContextForge section (7.1), single transport (4.1) |
| `docs/troubleshooting.md` | Already has prominent 502/503 section at top with "infra not token" guidance |
| `docs/windsurf-roo-setup.md` | Already has curl verification, in-client verification, troubleshooting table |

### Reviewer-Pusher verdict
Approved. [`README.md`](README.md), [`docs/gotchas.md`](docs/gotchas.md), [`docs/architecture.md`](docs/architecture.md), [`docs/troubleshooting.md`](docs/troubleshooting.md), and [`docs/windsurf-roo-setup.md`](docs/windsurf-roo-setup.md) are coherent enough for a fresh developer after the Streamable HTTP migration.

Verified during review:
- No newly introduced secrets in the reviewed diff; the previous hardcoded bearer token example was removed from [`docs/troubleshooting.md`](docs/troubleshooting.md).
- [`README.md`](README.md) now correctly points new developers to the single [`/mcp`](README.md:16) transport, Cloudflare Tunnel routing, and the ContextForge distinction.
- [`docs/architecture.md`](docs/architecture.md) now matches reality on routing and transport, including the ContextForge sidecar and single-endpoint model.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) now front-loads the Cloudflare 502/503 guidance so infra failures are not confused with auth failures.
- [`docs/windsurf-roo-setup.md`](docs/windsurf-roo-setup.md) now gives one consistent setup path plus verification steps for Windsurf and Roo Code.
- [`docs/gotchas.md`](docs/gotchas.md) numbering is sequential and easier to scan.

Docs-improvement item: complete.
