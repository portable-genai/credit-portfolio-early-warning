"use client";

import { useCallback, useEffect, useState } from "react";

// Every request goes to THIS origin. The browser never learns the service's address and never
// holds its credential; the route handler under /api/agent forwards, having discarded whatever
// identity the client tried to assert.
const API = "/api/agent";

// Mirrors the service's seeded local personas. The picker is a DEV convenience: the server
// validates the selection against its own list, so a hand-crafted value cannot invent a persona.
const PERSONAS = ["analyst", "approver", "auditor", "other-tenant"];

// The supervisory ladder, worst last. Rendered as a strip so a reader sees the distance between
// the grade of record and the proposal rather than reading two words and inferring it.
const LADDER = ["pass", "special_mention", "substandard", "doubtful", "loss"];

// Statuses a reader must not skim past. A covenant nobody tested must not look like one that
// passed, and one not yet due must not look like one nobody tested.
const UNEVIDENCED = ["not_evidenced", "stale", "not_due"];

function label(value: string): string {
  return value.replace(/_/g, " ");
}

interface CardSummary {
  name?: string;
  description?: string;
}

interface Obligor {
  obligor_id: string;
  name: string;
  sector?: string;
  current_grade?: string;
  clean_periods?: number;
  last_review_on?: string;
}

interface CitationRow {
  source_id: string;
  title: string;
  snippet?: string;
}

interface FamilyScore {
  family: string;
  raw_weight: number;
  cap: number;
  capped_weight: number;
  signal_count: number;
}

interface CovenantTest {
  covenant_id: string;
  type: string;
  status: string;
  threshold: number;
  operator: string;
  observed_value: number | null;
  test_period: string;
  certificate_age_days: number | null;
  headroom: number | null;
  rule_id: string;
  detail: string;
  citations: CitationRow[];
}

interface SignalRow {
  rule_id: string;
  family: string;
  severity: string;
  weight: number;
  metric: string;
  observed_value: number | null;
  threshold: number | null;
  periods_tested: number;
  detail: string;
  evidence_ref: string;
  citations: CitationRow[];
}

interface ReviewResponse {
  obligor_id: string;
  obligor_name: string;
  as_of: string;
  test_period: string;
  current_grade: string;
  band_grade: string;
  proposed_grade: string;
  movement: string;
  notches: number;
  applied_floors: string[];
  applied_ceiling: string;
  withheld_reason: string;
  composite_score: number;
  family_scores: FamilyScore[];
  effective_days_past_due: number;
  arrears_material: boolean;
  staging_backstop: string;
  data_completeness: number;
  covenant_tests: CovenantTest[];
  signals: SignalRow[];
  confirmation_requested: string[];
  severity: string;
  requires_human_review: boolean;
  review_reasons: string[];
  review_ref: string;
  required_approvals: number;
  grade_applied: boolean;
  summary: string;
  memo_headline: string;
  memo_body: string;
  memo_discarded_reason: string;
}

export default function Home() {
  const [persona, setPersona] = useState(PERSONAS[0]);
  const [obligors, setObligors] = useState<Obligor[]>([]);
  const [obligorId, setObligorId] = useState("");
  const [testPeriod, setTestPeriod] = useState("");
  const [asOf, setAsOf] = useState("");
  const [result, setResult] = useState<ReviewResponse | null>(null);
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const [card, setCard] = useState<CardSummary | null>(null);
  const [showQuiet, setShowQuiet] = useState(false);

  // The service names itself, so this UI carries no hardcoded product name to go stale.
  useEffect(() => {
    let live = true;
    fetch(API + "/.well-known/agent-card.json", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (live) setCard(body as CardSummary | null);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  // The obligor picker is populated from the READ-ONLY listing the registry port serves. There
  // is no write counterpart on this surface or on any other.
  const loadObligors = useCallback(() => {
    let live = true;
    fetch(API + "/v1/obligors", { cache: "no-store", headers: { "X-Dev-Persona": persona } })
      .then((response) => (response.ok ? response.json() : []))
      .then((body) => {
        if (!live) return;
        const rows = (body as Obligor[]) ?? [];
        setObligors(rows);
        setObligorId((current) => current || (rows.length ? rows[0].obligor_id : ""));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [persona]);

  useEffect(loadObligors, [loadObligors]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure("");
    try {
      const response = await fetch(API + "/v1/watchlist-review", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Dev-Persona": persona },
        body: JSON.stringify({
          obligor_id: obligorId,
          test_period: testPeriod,
          as_of: asOf,
        }),
      });
      const body = await response.text();
      if (!response.ok) {
        setResult(null);
        setFailure(body);
      } else {
        setResult(JSON.parse(body) as ReviewResponse);
      }
    } catch (error) {
      setResult(null);
      setFailure(String(error));
    } finally {
      setBusy(false);
    }
  }

  const fired = result ? result.signals.filter((signal) => signal.weight > 0) : [];
  const considered = result ? result.signals.filter((signal) => signal.weight === 0) : [];
  const families = result ? result.family_scores : [];

  return (
    <main>
      <h1>{card?.name ?? "Watchlist review console"}</h1>
      <p className="sub">
        {card?.description ??
          "Review one obligor and propose a watchlist grade. Nothing here applies a grade."}
      </p>

      <form onSubmit={submit}>
        <fieldset>
          <legend>Who you are</legend>
          <label>
            Seeded dev persona (local profile only; the server resolves identity, not this field)
            <select value={persona} onChange={(event) => setPersona(event.target.value)}>
              {PERSONAS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset>
          <legend>The review</legend>
          <label>
            Obligor (from the read-only registry listing)
            <select value={obligorId} onChange={(event) => setObligorId(event.target.value)}>
              {obligors.map((obligor) => (
                <option key={obligor.obligor_id} value={obligor.obligor_id}>
                  {obligor.name} ({label(obligor.current_grade ?? "pass")})
                </option>
              ))}
            </select>
          </label>
          <label>
            Reporting period (blank means the latest the covenant feed reports)
            <input
              value={testPeriod}
              placeholder="FY2026H1"
              onChange={(event) => setTestPeriod(event.target.value)}
            />
          </label>
          <label>
            As of (blank means today; the resolved date is echoed on the answer)
            <input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
          </label>
          <button type="submit" disabled={busy || !obligorId}>
            {busy ? "Working" : "Review this obligor"}
          </button>
        </fieldset>
      </form>

      {failure ? <pre className="result error">{failure}</pre> : null}

      {result ? (
        <div className="review">
          {/* 1. The proposal, and the sentence about what was NOT done, in the same block. */}
          <section className="block">
            <h2>Proposal</h2>
            <ol className="ladder">
              {LADDER.map((grade) => {
                const marks: string[] = [];
                if (grade === result.current_grade) marks.push("of record");
                if (grade === result.proposed_grade) marks.push("proposed");
                return (
                  <li key={grade} className={marks.length ? "rung marked" : "rung"}>
                    <span className="rung-name">{label(grade)}</span>
                    {marks.length ? <span className="rung-mark">{marks.join(" and ")}</span> : null}
                  </li>
                );
              })}
            </ol>
            <p className="movement">
              {label(result.movement)}, {result.notches} notch(es), severity {result.severity}
            </p>
            <p className="notapplied">
              <strong>No grade was changed.</strong> grade_applied is {String(result.grade_applied)},
              and this service has no write path to the grading system of record: the port declares
              read methods only. {result.review_ref ? "Routed to " + result.review_ref : "Not routed"}
              , requiring {result.required_approvals} approval(s).
            </p>
            {result.review_reasons.length ? (
              <p className="reasons">
                Why it reached you: {result.review_reasons.map(label).join(", ")}
              </p>
            ) : null}
          </section>

          {/* 2. The score, with raw beside capped so a reader sees where a cap bound. */}
          <section className="block">
            <h2>Score</h2>
            <p className="composite">
              composite <strong>{result.composite_score}</strong>, band {label(result.band_grade)},
              evidence coverage {result.data_completeness}, effective days past due{" "}
              {result.effective_days_past_due} (arrears material: {String(result.arrears_material)})
            </p>
            <table>
              <thead>
                <tr>
                  <th>Family</th>
                  <th>Raw</th>
                  <th>Cap</th>
                  <th>Contributed</th>
                  <th>Signals</th>
                </tr>
              </thead>
              <tbody>
                {families.map((score) => (
                  <tr key={score.family} className={score.raw_weight > score.cap ? "capped" : ""}>
                    <td>{label(score.family)}</td>
                    <td>{score.raw_weight}</td>
                    <td>{score.cap}</td>
                    <td>{score.capped_weight}</td>
                    <td>{score.signal_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* 3. The floors: the most important row on the page when a floor did the classifying. */}
          <section className="block">
            <h2>Floors and ceiling</h2>
            {result.applied_floors.length ? (
              <p className="chips">
                {result.applied_floors.map((floor) => (
                  <span className="chip" key={floor}>
                    {floor}
                  </span>
                ))}
              </p>
            ) : (
              <p className="muted">No floor applied: the band alone decided this proposal.</p>
            )}
            {result.band_grade !== result.proposed_grade ? (
              <p className="floor-note">
                The score alone said <strong>{label(result.band_grade)}</strong>. A named floor rule
                said <strong>{label(result.proposed_grade)}</strong>.
              </p>
            ) : null}
            {result.applied_ceiling ? (
              <p className="floor-note">Ceiling applied: {result.applied_ceiling}</p>
            ) : null}
            {result.withheld_reason ? (
              <p className="floor-note">Withheld: {label(result.withheld_reason)}</p>
            ) : null}
            <p className="muted">
              IFRS 9 backstop tripped: {label(result.staging_backstop)}. The engine raises the
              presumption; only a human rebuts one, and no impairment stage is proposed.
            </p>
          </section>

          {/* 4. The covenant table, with the origination locator on each row. */}
          <section className="block">
            <h2>Covenants</h2>
            <table>
              <thead>
                <tr>
                  <th>Covenant</th>
                  <th>Test</th>
                  <th>Observed</th>
                  <th>Headroom</th>
                  <th>Certificate age</th>
                  <th>Status</th>
                  <th>Origination locator</th>
                </tr>
              </thead>
              <tbody>
                {result.covenant_tests.map((test) => (
                  <tr
                    key={test.covenant_id}
                    className={
                      test.status === "breach"
                        ? "breach"
                        : UNEVIDENCED.includes(test.status)
                          ? "unevidenced"
                          : ""
                    }
                  >
                    <td>{test.covenant_id}</td>
                    <td>
                      {label(test.type)} {test.operator} {test.threshold} ({test.test_period})
                    </td>
                    <td>{test.observed_value === null ? "none" : test.observed_value}</td>
                    <td>{test.headroom === null ? "n/a" : test.headroom.toFixed(2)}</td>
                    <td>
                      {test.certificate_age_days === null ? "n/a" : test.certificate_age_days + "d"}
                    </td>
                    <td>
                      {label(test.status)} <span className="rule">{test.rule_id}</span>
                    </td>
                    <td className="locator">
                      {test.citations.map((citation) => citation.source_id).join(" ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              Tested against the terms credit-memo-drafting extracted at origination. A covenant
              nobody evidenced is never counted compliant, and one not yet due is not the same as
              one nobody evidenced.
            </p>
          </section>

          {/* 5. Signals, with the rules that did NOT fire kept and collapsed. */}
          <section className="block">
            <h2>Signals</h2>
            <table>
              <thead>
                <tr>
                  <th>Rule</th>
                  <th>Family</th>
                  <th>Weight</th>
                  <th>Observed against threshold</th>
                  <th>Periods</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {fired.map((signal) => (
                  <tr key={signal.rule_id + signal.evidence_ref}>
                    <td>{signal.rule_id}</td>
                    <td>{label(signal.family)}</td>
                    <td>{signal.weight}</td>
                    <td>
                      {signal.observed_value === null ? "present" : signal.observed_value}
                      {signal.threshold === null ? "" : " against " + signal.threshold}
                    </td>
                    <td>{signal.periods_tested}</td>
                    <td className="locator">
                      {[signal.evidence_ref, ...signal.citations.map((c) => c.source_id)]
                        .filter(Boolean)
                        .join(" ")}
                    </td>
                  </tr>
                ))}
                {fired.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="muted">
                      No rule fired.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>

            <button
              type="button"
              className="ghost"
              onClick={() => setShowQuiet((current) => !current)}
            >
              {showQuiet ? "Hide" : "Show"} rules considered that did not fire ({considered.length})
            </button>
            {showQuiet ? (
              <ul className="quiet">
                {considered.map((signal) => (
                  <li key={signal.rule_id}>
                    <strong>{signal.rule_id}</strong> {signal.detail}
                  </li>
                ))}
              </ul>
            ) : null}

            {result.confirmation_requested.length ? (
              <div className="outside">
                <h3>Awaiting your confirmation (outside the score)</h3>
                <p className="muted">
                  The feed has not confirmed these items are about this obligor, so they scored
                  exactly nothing and can never move a grade.
                </p>
                <ul>
                  {result.confirmation_requested.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>

          {/* 6. The memo, and the discard reason when validation rejected the draft. */}
          <section className="block">
            <h2>Memo</h2>
            <p className="muted">
              Drafted for the credit officer; every figure comes from the engine, and the draft is
              discarded if it does not.
            </p>
            {result.memo_discarded_reason ? (
              <>
                <p className="discarded">Draft discarded: {result.memo_discarded_reason}</p>
                <p>{result.summary}</p>
              </>
            ) : result.memo_headline ? (
              <>
                <h3>{result.memo_headline}</h3>
                <p>{result.memo_body}</p>
              </>
            ) : (
              <p>{result.summary}</p>
            )}
          </section>
        </div>
      ) : null}

      <footer>
        Synthetic, obviously fictional data only. Identity is resolved server-side and the
        client-asserted actor is discarded; see ui/README.md for the embedding contract. This
        console proposes a grade and never applies one.
      </footer>
    </main>
  );
}
