# DEMO: Credit Portfolio Early Warning (Doc7)

Everything here runs **offline**: no cloud project, no credentials, no API key, no browser
engine, no bundler. That is the first thing to say out loud, because it is the claim the rest of
the demo rests on.

```bash
make install          # locked install from requirements-dev.lock
make demo             # the presenter-paced walkthrough (starts its own server)
```

Every obligor, address, covenant clause and news item in this demo is **synthetic**. The parties
announce themselves as FICTIONAL, every address is an `.example` domain, and the one national id
present is a synthetic checksum-valid literal whose only job is to prove that redaction happened.
The estate lives in one place (`adapters/local/_fixtures.py`) and the demo, the local adapters and
the evaluation all read it, so there is one synthetic book rather than three that look alike.

## The eight-step walkthrough

`make demo` starts a loopback server, opens the page, and then waits for you at every step. The
narration is printed on **your terminal**, never on the page, so the audience sees only the clean
output view. At a prompt: **Enter** runs the step, a **number** jumps to that step, **r** restarts
the run, **q** quits.

Every step drives the real services. Nothing is pre-recorded, and every step is ASSERTED: if the
service does not actually reach the state the narration just claimed, the walkthrough says so and
exits non-zero.

| # | Step | What it proves |
|---|---|---|
| 1 | `opened`: bound offline, with the bank's policy visible and a registry that cannot write | Every port binds in all three families with no cloud project and no SDK imported. Two VERTICAL facts on the same page: the grade ladder, the family caps and the floor rules are read from configuration, and the loader refuses a non-monotonic ladder before it serves a request; and the port holding the grade of record declares read methods only. |
| 2 | `routine`: forty one days down, and the obligor stays at pass | Kappa Bunkering. Arrears of 640.00 clear the absolute limit and fail the relative one, so the past-due clock never starts and nothing is routed. The rule that did NOT fire is recorded at weight zero, naming both limits and both observed values. |
| 3 | `escalation`: the score said special mention, the arrears floor said substandard | Delta Agri. The financial family sums 73 and contributes 40 at its cap, the composite of 65 puts the band at special mention, and the ninety-day arrears floor lifts the proposal to substandard: a two-notch downgrade, escalated AND routed in the same call, with no writeback anywhere. The unconfirmed litigation headline contributes exactly zero. |
| 4 | `redaction`: a guarantor's identifier is masked before the model and before the write | Gamma Marine. A covenant clause names a guarantor and carries a national id. One masking seam, and the SAME masked object reaches the audit write, the outbound payload and the model prompt. A live waiver removed the FLOOR and not the signal, and it escalates anyway because the waiver expires inside the notice window. |
| 5 | `review_queue`: what the credit officer receives | One item per routed proposal, redacted against every configured jurisdiction. The substandard proposal asks for two approvals; the affirm with an expiring waiver asks for one. Every payload says `grade_applied=false`, and the count of writes to the registry is zero. |
| 6 | `audit`: the trail verifies, and it reconstructs the decision | Hash chained with the head anchored on a separate volume, exported to JSON Lines and reloaded into a fresh store with every link intact. One record names the grade of record, the proposed grade, the composite and the exact floor rules that lifted it. |
| 7 | `tamper`: a downgrade rewritten out of the trail is DETECTED | An attacker with file access drops the append-only triggers and rewrites one interior record, turning a substandard proposal back into a pass. The chain breaks and names the sequence number. |
| 8 | `portability`: the exit profile refuses loudly | The same calls on the on-premises profile with one environment variable changed. Every seam refuses by name; tracing is ABSENT by design, because a diagnostic must not be fatal. Both sets are asserted in both directions. |

## The four sentences a presenter must not skip

1. **On step 2:** the rule that did NOT fire is on the screen, with both limits and both observed
   values. A second-line reviewer asks what you considered, and a silent pass destroys that.
2. **On step 3:** the arrears FLOOR set the grade, not the composite. Days past due classify an
   exposure whatever the score says, and a clean covenant sheet cannot talk you out of it.
3. **On step 3:** the litigation headline contributed exactly zero, because the feed has not
   confirmed it is about this obligor. Entity resolution is the feed's job, never the model's.
4. **On step 5:** exposure size set the APPROVAL PATH and took no part in the classification. A
   grade that moved with exposure size would be gameable by splitting facilities.

Step 7 is the one to linger on. A demo where nothing ever goes wrong is a sales deck; this one
shows a specific credit fraud, somebody quietly turning a substandard proposal back into a pass,
and shows that the system detects it and names the record.

## The other three ways to run it

```bash
make demo-selftest    # unattended and headless, asserts every step, non-zero on failure
make demo-static      # demo.json plus out/index.html and out/step-*.html, for screenshots
make portability      # the executable portability claim: named checks, pass or fail each
```

`tests/unit/test_demo_surface.py` drives the whole arc inside the offline gate, and the
hosted Cloud Build check runs that gate on every pull request and every push to main, so the
demo cannot rot silently between showings. `scripts/README.md` documents each script and the
environment overrides.

**Still owed (BOOTSTRAP-CHECKLIST section 3, row 15):** nobody has run `make demo-static` and
LOOKED at the pages, and nobody has rehearsed the narration in front of an audience. The
self-test proves the arc holds; it does not prove the pages read well or that the eight beats fit
the time. That gap stays open until somebody does both.

## The claims, and their bounds

State the bounds yourself. An unbounded claim is the one an auditor disproves for you.

| Claimed | Proved by | NOT claimed |
|---|---|---|
| Runs with no cloud, credentials or network | the whole demo, plus `make gate` | that the managed profile works: that needs a project and lives in `tests/integration/` |
| The grade proposal is deterministic and replayable | steps 2 and 3, `make gate` | that a model's narration is deterministic; it is not, and it never decides |
| This service proposes a grade and never applies one | steps 1 and 5, `make portability` | that the approved grade reached the rating system; that integration is a client's |
| Proposals reach a human | steps 3, 4 and 5 | that a credit officer acted; the queue shows submitted, not reviewed |
| The weights and bands are the bank's, not ours | step 1 | that they are CALIBRATED. They are reference defaults, not a fitted scorecard |
| The audit record is tamper-evident and portable | steps 6 and 7, `make portability` | tamper-PROOF: file access beats any store |
| Every port is swappable and every seam is named | step 8, `make portability` | that an on-premises deployment exists, or model or infrastructure portability |

## The UI

```bash
make ui-install && make ui-dev     # http://localhost:3000, proxying to the service
```

Worth showing to a Chief Credit Officer, because the proposal is unreadable as raw JSON. The
console renders six blocks in the order a credit officer reads a proposal: the grade ladder with
the sentence that no grade was changed, the score with raw beside capped, the applied floors, the
covenant table with its origination locators, the signals with the rules that did not fire kept in
a collapsed section, and the memo. The security point stands too: the browser never asserts who
the user is, the service credential never leaves the server, and framing and CORS are per-tenant
allowlists that refuse a wildcard. See `ui/README.md`.

## Managed profile (gcp)

Set `CREDITEWS_PROFILE=gcp` and install the `[gcp]` extra; identity becomes
the platform's signed assertion, audit becomes the Cloud Logging WORM sink, and the four systems
of record are read over their real endpoints. This is NOT part of the offline demo and needs a
real project. See `docs/runbook.md`.
