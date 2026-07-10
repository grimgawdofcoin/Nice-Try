# King & Sepal — Status

Read `PLAYBOOK.md` first for the full plan. This file is the live tracker: where we are, what's next, and the working rules for how autonomously the agent operates. Update this on every session — it's how the next session (or the next day's automated check-in) knows the business "through and through" without re-deriving anything.

## Working rules (set by founder Selah)

- **Spend ceiling:** up to ~$500 committed without asking first (e.g. LLC filing, business tax receipt, Shopify/Beehiiv subscriptions, a first small cacao sample order). Anything above that — ask first.
- **Legal filings (LLC formation, EIN application):** never filed autonomously, regardless of budget. The agent prepares the exact info/steps; Selah submits these two personally.
- **Outreach to real third parties** (suppliers, FDACS, county offices): the agent drafts — it does **not** send. There is no email-send capability available in this environment, only Gmail draft creation, so drafts land in Gmail's Drafts folder for Selah to review and send.
- **Cadence:** daily check-in/push forward, once the automation is working (see Known blockers).

## Current phase

**Phase 0 — Confirm legality & your lane.** Not yet started.

## Next actions (in order)

1. Draft an email to FDACS confirming ceremonial cacao block/powder qualifies as a cottage food (Phase 0).
2. Draft outreach emails to Tabal Chocolate and Kahkow USA requesting ceremonial-grade confirmation, certs, pricing, MOQ, lead time (Phase 1).
3. Look up Broward County / City of Plantation's Local Business Tax Receipt requirements and cost.
4. Start drafting the compliant label copy (Phase 2) once a hero cacao is chosen.

## Known blockers

- **Background automation is not yet running.** The connector needed to schedule a recurring daily check-in (and to add this repo to the session in the first place) was failing on every retry as of 2026-07-10. Re-arm the daily routine once it's confirmed working — see decision log.
- Supplier pricing/MOQ, insurance quotes, and exact county fee are all still unconfirmed — first-pass numbers in the playbook are estimates.

## Decision log

### 2026-07-10 — Repo + tracker set up
**Plan:** Stand up a working repo for King & Sepal (blocked on a broken connector, fell back to this repo), capture the founder's uploaded execution playbook verbatim, and record the working rules (spend ceiling ~$500, draft-only outreach due to no send capability, no autonomous legal filings, daily cadence once automation works).
**Outcome:** `PLAYBOOK.md` and this `STATUS.md` created on the `king-and-sepal` branch. Daily routine not yet armed — connector was down. Next session: retry arming the routine, then start on Phase 0 next actions above.
