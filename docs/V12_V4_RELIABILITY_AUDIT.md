# V12 / V4 Reliability Audit — Sandbox

**Scope:** read-only audit of the current V12 `main`, V12 EMA PR #8 head, and V4 `main`.
**Isolation:** this audit branch changes only `MraJJqq/vegas-sandbox`. It does not write to, dispatch, deploy, scan, or send Bark through either formal repository.

## Current findings

### A. V12 scan / state / Bark / watchdog

- The 27-symbol configuration and V4 universe resolve to the same contract set: 23 stock contracts plus BTC, HYPE, XAU and CL.
- Scan orchestration uses 4 workers and only includes closed candles. It marks a scan complete only when all configured symbols have data; the public feed is published only after a complete 27/27 scan.
- Daily signal state is merged by symbol + candle timestamp + filter side, and resets when the Beijing signal date changes.
- Bitget retrieval has bounded retries, a shared request throttle, resumable cache, gap repair, and validation. A gap-repair failure fails closed rather than fabricating candles.
- Bark persists accepted and pending delivery states. Ambiguous network outcomes are not automatically resent, which favors duplicate prevention over guaranteed delivery.
- Watchdog recovery uses durable issue locks before dispatch and checks whether a later successful run superseded a failure.

**Remaining reliability risk:** Bark's fingerprint includes `started_at`, so two distinct workflow runs for the same scheduled slot and identical message body are treated as different deliveries. Same-run duplicate suppression works, but there is no stable scheduled-slot idempotency key. This should be addressed only after deciding how manual scans should behave; otherwise legitimate manual pushes could be suppressed.

**Operational limitation:** ambiguous Bark delivery is intentionally not retried automatically. It prevents duplicate pushes but may require manual inspection when the network outcome is unknown.

### B. V12 → V4 feed

- V12 publishes `v12/public-signals.json` only after a complete scan and writes the snapshot atomically.
- V4 reads one canonical raw GitHub URL, validates source/schema/day/full 27-symbol membership, and distinguishes unavailable data from a confirmed no-signal state.
- V4 refreshes the feed on a five-minute cadence, caches successful reads for 30 seconds, coalesces in-flight requests, and suspends/aborts work while hidden.
- Signal data is rendered only in the bottom ticker and does not control the K-line universe or rotation.

**Remaining hardening opportunity:** V4 validates the outer feed and symbol universe, but the feed adapter does not deeply validate every signal row (known contract, timestamp, direction and tunnel names) before accepting the payload. The ticker filters unknown contracts and requires `formal_signal === true`, so malformed rows are unlikely to become visible, but strict row validation would make the contract stronger.

### C. Performance / redundancy

- V12 uses bounded parallel symbol scans and a global Bitget request throttle; V4 market requests are bounded to concurrency 2.
- V4 has one lifecycle owner, hidden-page suspension, in-flight cancellation, timer cleanup, and incremental EMA update support.
- V4 signal refresh and card quote refresh are separate five-minute tasks; market candle refresh is also five-minute after warmup. They are guarded against overlap.
- No high-confidence evidence from the inspected code justifies a broad refactor. Preserve the current module boundaries and optimize only measured bottlenecks.

### D. EMA release status

V12 `main` still contains the old Pandas `ewm(adjust=False)` seed. The SMA-seed alignment is in PR #8 (`fix/v12-ema-sma-seed`), which is currently open and draft. This audit does not merge it or alter either formal repository. The BTC sandbox experiment supports practical parity for the tested data window; it is not a proof across every contract and every possible history start.

## Verdict

The main architecture is sound: complete-scan publication, daily signal accumulation, conservative Bark ambiguity handling, read-only V4 consumption, and lifecycle cleanup are all present.

The two concrete improvements worth considering are:
1. Add a stable slot/run idempotency key for Bark, with explicit behavior for manual scans.
2. Validate each V12 signal row strictly in the V4 feed adapter.

No production code was changed. Any implementation of these two items should be separately reviewed and tested in this sandbox before a formal-repository PR is proposed.
