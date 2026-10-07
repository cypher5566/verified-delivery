# Replay benchmark — reviewer brief and effort (2026-10-07)

Why: one real day of use (three deliveries, 33 Codex gate runs, 135 reviewer-minutes; median 250 s per run)
took 1–2 hours per bug. Per-run time was not the cost; the number of rounds was (14 plan rounds on one
delivery, 6 + 4 on another) plus protocol-only stops (timeout, fingerprint drift, index-hash definition,
detached-HEAD identity) that found nothing about the product.

## Method
- Three historical requests replayed against isolated checkouts at the original commits, with only the
  artifacts that existed at the time (later gate reports removed so the answer could not leak).
- Ground truth written before any result was read.
- Arms, one run each per case, same model (gpt-6.1-sol), timeout 1500 s:
  A = previous brief, effort medium, original request.
  B = new brief, effort medium, request without the old output-format demands.
  C = new brief, effort low, same request as B.

## Cases and ground truth
1. Plan gate, TTS seq-release plan v1. GT1: releasing a parked tail-merge caption's slot makes its later
   restoration lose real speech.
2. Plan gate, production migration plan v1. GT2a: unbounded lock wait (no lock_timeout) can stall
   classroom requests. GT2b: rollback destroys real progress written after apply. Secondary: CLI
   atomicity/privilege unproven; preservation proof too weak.
3. Result gate, the shipped TTS change (clean: verified in production). Measures false blockers.

## Results
| Case | A (old brief, medium) | B (new brief, medium) | C (new brief, low) |
|---|---|---|---|
| 1 | FAIL, GT1 found, 205 s, 1723 words | FAIL, GT1 found + one NEW real defect, 144 s, 958 words | FAIL, GT1 + same NEW defect, 118 s, 830 words |
| 2 | Stopped on fingerprint MISMATCH (origin/main had moved): 0/2 primary, 43 s | GT2a + GT2b BLOCKING, atomicity NON-BLOCKING, drift as PROTOCOL NOTE, 85 s | same as B, 77 s |
| 3 | FAIL on a false blocker (detached HEAD vs branch name), 83 s | PASS, new defect noted NON-BLOCKING, 172 s | PASS, 121 s |

NEW defect (B and C, confirmed afterwards on the shipped code with the real gate methods): releasing an
unvoiced seq arms the six-second skip timer early, so a slow earlier sentence is replayed after a later
one (shipped order [3, 1] at t=7.1/8.2 s vs baseline [1, 3] at 8.2/13.1 s). Low severity; tracked.

Decision rule (fixed in advance): adopt if primary recall is not lower on any case, false blockers are
not higher, and time or protocol-driven non-passing verdicts drop. Result: recall B = C ≥ A on every case;
protocol-driven non-passing verdicts A = 2/3, B = C = 0/3; reports about half as long. Adopted.
Effort: low matched medium on every case and was 15–30 % faster; the runner therefore stops pinning
effort (provider default applies) and tier 3 passes `--effort medium` explicitly.

## Limits
- n = 1 per arm per case; this rules out large regressions, not small ones.
- No historical pre-fix candidate for a concurrency-heavy result gate survived, so result-review recall
  on timing bugs was not measured here (only plan-gate recall and result-gate false blockers).
- Round reduction comes from the tier/run-budget rules, not from this replay; measure it on the next
  real deliveries (count runs and rounds per delivery against the 33-run baseline above).

## Addendum — high and xhigh (same cases, same new brief as arms B/C, one run each, timeout 1500 s)
Added because the first pass compared only low and medium.

| | low (C) | medium (B) | high (D) | xhigh (E) |
|---|---|---|---|---|
| GT1 (case 1) | found | found | found | found |
| GT2a + GT2b (case 2) | both | both | both | both |
| GT2c (secondary) | non-blocking | non-blocking | non-blocking, deeper (read the CLI source) | same as high |
| GT2d (secondary) | missed | missed | missed | missed |
| NEW reorder defect, case 1 (plan) | blocking | blocking | **missed** | blocking |
| NEW reorder defect, case 3 (result) | non-blocking | non-blocking | **blocking** (most accurate severity) | **missed** (asserted no ordering regression) |
| False blockers | 0 | 0 | 0 | 0 |
| Mean wall time | 105 s | 134 s | 250 s | 342 s |

Reading: no evidence that high or xhigh find more. Every effort found every primary ground truth; the
new defect was missed once each by high and xhigh but by neither low nor medium. Differences between
runs look like sampling variance, not effort, while cost rises 2.4x (high) and 3.3x (xhigh). Decision
unchanged: no pinned effort by default (model default, low for gpt-6.1-sol); tier 3 passes medium.
Untested hypothesis worth measuring next: two parallel low-effort reviews merged may beat one xhigh
review on recall at lower wall time, because their misses appear independent.
