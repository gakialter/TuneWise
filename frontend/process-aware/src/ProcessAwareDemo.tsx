import { useCallback, useEffect, useState } from "react";

import { fetchProcessAwareDemo } from "./api";
import type {
  CandidateSummary,
  ProcessAwareDemoResponse,
  ProcessAwareScenario,
  SafetyValidatorSummary,
  SharedEvidence,
} from "./types";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; data: ProcessAwareDemoResponse }
  | { kind: "error"; message: string };

const scenarioLetters = ["A", "B"] as const;

function shortFingerprint(value: string): string {
  if (value.length <= 24) {
    return value;
  }
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

function caseNumber(caseId: string): string {
  return caseId.split("-").at(-1) ?? caseId;
}

function SyntheticStamp({ label, sourceKind }: { label: string; sourceKind: string }) {
  return (
    <span className="synthetic-stamp">
      <span aria-hidden="true" className="stamp-dot" />
      <span>
        <strong>{label}</strong>
        <small>{sourceKind}</small>
      </span>
    </span>
  );
}

function SharedEvidencePanel({ evidence }: { evidence: SharedEvidence }) {
  const fingerprints = [
    ["Measurement hash", evidence.measurement_hash],
    ["Query feature", evidence.query_feature_hash],
    ["Feature definition", evidence.feature_definition_version],
    ["Scaler", evidence.scaler_version],
    ["Case index", evidence.case_index_hash],
  ];

  return (
    <section className="shared-evidence" aria-labelledby="shared-evidence-title">
      <div className="section-title-row">
        <div>
          <p className="section-kicker">Locked input / 共享输入</p>
          <h2 id="shared-evidence-title">Shared Evidence</h2>
        </div>
        <span className="shared-lock">
          <span aria-hidden="true">◇</span>
          {evidence.same_across_scenarios ? "Same across A + B" : "Comparison mismatch"}
        </span>
      </div>

      <div className="shared-evidence-grid">
        <div className="evidence-callout measurement-callout">
          <p>Same measurement evidence</p>
          <strong>{evidence.measurement_evidence_label}</strong>
          <code title={evidence.measurement_hash}>{shortFingerprint(evidence.measurement_hash)}</code>
        </div>

        <div className="evidence-callout root-callout">
          <p>Same root-cause ranking</p>
          <strong>{evidence.top1_root_cause} <span>Top-1</span></strong>
          <ol aria-label="Shared root-cause ranking">
            {evidence.ordered_root_causes.map((item) => (
              <li key={item.rank}>
                <span>{String(item.rank).padStart(2, "0")}</span>
                <code>{item.root_cause}</code>
              </li>
            ))}
          </ol>
        </div>

        <div className="fingerprint-panel">
          <div className="fingerprint-heading">
            <p>Shared deterministic fingerprint</p>
            <strong>{evidence.feature_dimension}-D</strong>
          </div>
          <dl>
            {fingerprints.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  <code title={value} aria-label={`${label}: ${value}`}>
                    {shortFingerprint(value)}
                  </code>
                </dd>
              </div>
            ))}
            <div>
              <dt>Model / preprocessing</dt>
              <dd>
                <code>{evidence.diagnostic_model_version}</code>
                <span aria-hidden="true"> · </span>
                <code>{evidence.preprocessing_version}</code>
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </section>
  );
}

function DecisionHinge({ scenarios }: { scenarios: ProcessAwareScenario[] }) {
  return (
    <section className="decision-hinge" aria-labelledby="decision-hinge-title">
      <div className="hinge-heading">
        <div>
          <p className="section-kicker">Decision hinge / 决策铰链</p>
          <h2 id="decision-hinge-title">The measurement stays fixed. Eligibility turns.</h2>
        </div>
        <span className="deterministic-label">DETERMINISTIC</span>
      </div>

      <p className="hinge-equation">
        <span>Same anomaly evidence</span>
        <b aria-hidden="true">→</b>
        <span>Different process context</span>
        <b aria-hidden="true">→</b>
        <span>Different eligible case evidence</span>
        <b aria-hidden="true">→</b>
        <span>Different CASE_GUIDED recommendation</span>
      </p>

      <div className="hinge-track" aria-hidden="true">
        <div className="track-origin"><span /></div>
        <div className="track-shaft" />
        <div className="track-pivot"><span /></div>
        <div className="track-fork track-fork-a" />
        <div className="track-fork track-fork-b" />
      </div>

      <div className="hinge-outcomes">
        {scenarios.map((scenario, index) => (
          <div className="hinge-outcome" key={scenario.scenario_id}>
            <span className="branch-letter">{scenarioLetters[index] ?? index + 1}</span>
            <div>
              <small>{scenario.process_context.process_stage}</small>
              <strong>Case {caseNumber(scenario.eligible_case.case_id)}</strong>
            </div>
            <span className="branch-arrow" aria-hidden="true">→</span>
            <div className="branch-delta">
              <small>CASE_GUIDED</small>
              <strong>{scenario.case_guided_candidate.delta_ticks} ticks</strong>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function PreviousState({ scenario }: { scenario: ProcessAwareScenario }) {
  const { process_context: context } = scenario;

  if (context.previous_action === null) {
    return (
      <div className="context-state empty-context-state">
        <p className="micro-label">Previous state</p>
        <strong>No previous action / outcome</strong>
        <span>Iteration {context.iteration_index} · intentionally empty</span>
      </div>
    );
  }

  const outcome = context.previous_action_outcome_display;
  return (
    <div className="context-state">
      <p className="micro-label">Previous action</p>
      <div className="previous-action-value">
        <code>{context.previous_action.parameter_name}</code>
        <strong>{context.previous_action.before_value}</strong>
        <span aria-label="changed to">→</span>
        <strong>{context.previous_action.after_value}</strong>
      </div>
      <p className="previous-action-meta">
        {context.previous_action.delta_ticks} tick · {context.previous_action.action_version}
      </p>
      <div className="outcome-row">
        <code>{context.previous_action_outcome}</code>
        {outcome && <strong>{outcome.en} / {outcome.zh}</strong>}
      </div>
    </div>
  );
}

function CandidateReadout({ candidate }: { candidate: CandidateSummary }) {
  return (
    <div className="candidate-readout">
      <div className="candidate-label-row">
        <span>Recommendation</span>
        <code>{candidate.generation_type}</code>
      </div>
      <div className="candidate-delta">
        <div>
          <small>{candidate.parameter_name}</small>
          <span>
            <strong>{candidate.current_value}</strong>
            <b aria-label="proposed as">→</b>
            <strong>{candidate.proposed_value}</strong>
          </span>
        </div>
        <div className="delta-tick">
          <strong>{candidate.delta_ticks}</strong>
          <small>ticks</small>
        </div>
      </div>
      <div className="candidate-validation">
        <span className="passed-dot" aria-hidden="true" />
        <strong>{candidate.validation_status}</strong>
        <code>{candidate.safety_rule_version}</code>
      </div>
    </div>
  );
}

function ScenarioCard({ scenario, index }: { scenario: ProcessAwareScenario; index: number }) {
  const letter = scenarioLetters[index] ?? String(index + 1);
  const { process_context: context, eligible_case: eligibleCase } = scenario;
  const profile = eligibleCase.process_profile;

  return (
    <article className={`scenario-card scenario-${letter.toLowerCase()}`} aria-labelledby={`scenario-${letter}-title`}>
      <header className="scenario-header">
        <span className="scenario-letter" aria-hidden="true">{letter}</span>
        <div>
          <p>Scenario {letter}</p>
          <h3
            id={`scenario-${letter}-title`}
            aria-label={`${context.process_stage_display.en} / ${context.process_stage_display.zh}`}
          >
            {context.process_stage_display.en}
            <span>/ {context.process_stage_display.zh}</span>
          </h3>
          <code>{context.process_stage}</code>
        </div>
      </header>

      <div className="synthetic-row" aria-label={`Scenario ${letter} synthetic sources`}>
        <SyntheticStamp label="Synthetic context" sourceKind={context.source_kind} />
        <SyntheticStamp label="Synthetic profile" sourceKind={profile.source_kind} />
      </div>

      <PreviousState scenario={scenario} />

      <section className="eligible-case" aria-label={`Scenario ${letter} eligible case`}>
        <div className="eligible-heading">
          <div>
            <p className="micro-label">Eligible historical case</p>
            <strong>Case {caseNumber(eligibleCase.case_id)}</strong>
            <code>{eligibleCase.case_id}</code>
          </div>
          <span className="reason-code">{eligibleCase.compatibility.reason_code}</span>
        </div>
        <p className="case-boundary-note">APPROVED offline case · synthetic process profile</p>
        <p className="compatibility-explanation">{eligibleCase.compatibility.explanation}</p>
        <div className="distance-readout">
          <span>Distance <strong>{eligibleCase.distance}</strong></span>
          <small>Retrieval distance, not a probability.</small>
        </div>
        <dl className="profile-grid">
          <div><dt>Profile stage</dt><dd><code>{profile.compatible_process_stage}</code></dd></div>
          <div><dt>Previous parameter</dt><dd>{profile.previous_action_parameter ?? "None"}</dd></div>
          <div><dt>Previous outcome</dt><dd><code>{profile.previous_action_outcome ?? "None"}</code></dd></div>
          <div><dt>Iteration range</dt><dd>{profile.minimum_iteration}–{profile.maximum_iteration ?? "∞"}</dd></div>
        </dl>
      </section>

      <CandidateReadout candidate={scenario.case_guided_candidate} />

      <div className="scenario-provenance">
        <span>Context <code title={context.context_hash}>{shortFingerprint(context.context_hash)}</code></span>
        <span>Profile <code title={profile.profile_hash}>{shortFingerprint(profile.profile_hash)}</code></span>
      </div>
    </article>
  );
}

function UnchangedCandidate({
  candidate,
  scenarioHashes,
}: {
  candidate: CandidateSummary;
  scenarioHashes: { A: string; B: string };
}) {
  const hashesMatch = scenarioHashes.A === scenarioHashes.B;

  return (
    <article className="invariant-card">
      <div className="invariant-title">
        <span className={hashesMatch ? "equal-mark" : "mismatch-mark"} aria-hidden="true">
          {hashesMatch ? "=" : "≠"}
        </span>
        <h3>{candidate.generation_type} {hashesMatch ? "unchanged" : "mismatch"}</h3>
      </div>
      <div className="invariant-value">
        <code>{candidate.parameter_name}</code>
        <span>{candidate.current_value} → {candidate.proposed_value}</span>
        <strong>{candidate.delta_ticks} ticks</strong>
      </div>
      <div
        className="control-hash-proof"
        aria-label={`${candidate.generation_type} A and B candidate hashes ${hashesMatch ? "match" : "do not match"}`}
      >
        <span>
          <small>A hash</small>
          <code title={scenarioHashes.A}>{shortFingerprint(scenarioHashes.A)}</code>
        </span>
        <b aria-hidden="true">{hashesMatch ? "=" : "≠"}</b>
        <span>
          <small>B hash</small>
          <code title={scenarioHashes.B}>{shortFingerprint(scenarioHashes.B)}</code>
        </span>
      </div>
      <p><span className="passed-dot" aria-hidden="true" />{candidate.validation_status}</p>
    </article>
  );
}

function SafetyInvariant({ validator }: { validator: SafetyValidatorSummary }) {
  return (
    <article className="invariant-card safety-invariant">
      <div className="invariant-title">
        <span className="shield-mark" aria-hidden="true">◇</span>
        <h3>
          Safety Validator {validator.unchanged_across_scenarios ? "unchanged" : "mismatch"}
        </h3>
      </div>
      <div className="safety-version-row">
        <span>Rule version</span>
        <code>{validator.safety_rule_version}</code>
        <strong>{validator.status}</strong>
      </div>
      <ul aria-label="Unchanged safety validation checks">
        {validator.validation_checks.map((check) => (
          <li key={check.check_code}>
            <code>{check.check_code}</code>
            <span>{check.status}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}

function InvariantBand({ data }: { data: ProcessAwareDemoResponse }) {
  const controls = data.unchanged_controls;
  return (
    <section className="invariant-band" aria-labelledby="invariant-band-title">
      <div className="section-title-row">
        <div>
          <p className="section-kicker">Control lane / 未改变项</p>
          <h2 id="invariant-band-title">The safety envelope does not move.</h2>
        </div>
        <span className="shared-lock">
          <span aria-hidden="true">=</span>
          {controls.identical_across_scenarios ? "Identical across A + B" : "Control mismatch"}
        </span>
      </div>
      <div className="invariant-grid">
        <UnchangedCandidate
          candidate={controls.conservative_candidate}
          scenarioHashes={{
            A: controls.scenario_candidate_hashes.A.CONSERVATIVE,
            B: controls.scenario_candidate_hashes.B.CONSERVATIVE,
          }}
        />
        <UnchangedCandidate
          candidate={controls.standard_candidate}
          scenarioHashes={{
            A: controls.scenario_candidate_hashes.A.STANDARD,
            B: controls.scenario_candidate_hashes.B.STANDARD,
          }}
        />
        <SafetyInvariant validator={controls.safety_validator} />
      </div>
    </section>
  );
}

function DemoContent({ data }: { data: ProcessAwareDemoResponse }) {
  const boundaryLines = data.facts_boundary.split(/\r?\n/).filter(Boolean);

  return (
    <>
      <section className="boundary-strip" aria-label="Facts boundary">
        <div className="boundary-label">
          <span aria-hidden="true">!</span>
          <strong>Facts boundary</strong>
        </div>
        <ul>
          {boundaryLines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>

      <section className="abstraction-note" aria-label="Abstraction note">
        <span>Product-specific vocabulary</span>
        <strong>{data.abstraction_note}</strong>
      </section>

      <SharedEvidencePanel evidence={data.shared_evidence} />
      <DecisionHinge scenarios={data.scenarios} />

      <section className="scenario-comparison" data-testid="scenario-comparison" aria-labelledby="scenario-comparison-title">
        <div className="comparison-heading">
          <div>
            <p className="section-kicker">Context split / 上下文分叉</p>
            <h2 id="scenario-comparison-title">Same signal. Two eligible case paths.</h2>
          </div>
          <p>Only the synthetic process context/profile changes which APPROVED offline case may guide the candidate.</p>
        </div>
        <div className="scenario-grid">
          {data.scenarios.map((scenario, index) => (
            <ScenarioCard key={scenario.scenario_id} scenario={scenario} index={index} />
          ))}
        </div>
      </section>

      <InvariantBand data={data} />

      <section className="provenance-band" aria-label="Synthetic demo provenance">
        <div><span>Demo version</span><code>{data.demo_version}</code></div>
        <div><span>Fixture</span><code>{data.provenance.fixture_version}</code></div>
        <div><span>Dataset asset</span><code>{data.provenance.demo_dataset_asset_id}</code></div>
        <div><span>Source</span><code>{data.provenance.source_kind}</code></div>
      </section>
    </>
  );
}

export default function ProcessAwareDemo() {
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });
  const [requestVersion, setRequestVersion] = useState(0);

  const retry = useCallback(() => {
    setLoadState({ kind: "loading" });
    setRequestVersion((version) => version + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoadState({ kind: "loading" });
    void fetchProcessAwareDemo(controller.signal)
      .then((data) => setLoadState({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setLoadState({
          kind: "error",
          message: error instanceof Error ? error.message : "The comparison could not be loaded.",
        });
      });
    return () => controller.abort();
  }, [requestVersion]);

  return (
    <div className="process-aware-app">
      <a className="skip-link" href="#comparison-main">Skip to comparison</a>
      <header className="app-header">
        <a className="wordmark" href="/" aria-label="TuneWise fixed demo home">
          <span className="wordmark-glyph" aria-hidden="true"><i /><i /><i /></span>
          <span><strong>TuneWise</strong><small>Evidence before action</small></span>
        </a>
        <a className="back-link" href="/">
          <span aria-hidden="true">←</span>
          Return to fixed demo
        </a>
      </header>

      <main id="comparison-main" tabIndex={-1}>
        <section className="hero" aria-labelledby="page-title">
          <div className="hero-index" aria-hidden="true">P/A</div>
          <div className="hero-copy">
            <p className="hero-kicker"><span>SYNTHETIC</span> Deterministic evidence routing</p>
            <h1 id="page-title">Process-aware Decision Demo</h1>
            <p className="hero-summary">
              A compact A/B proof that identical anomaly evidence can yield different eligible case guidance when the recorded process context changes.
            </p>
          </div>
        </section>

        {loadState.kind === "loading" && (
          <section className="load-panel" role="status" aria-live="polite">
            <span className="load-track" aria-hidden="true"><i /></span>
            <div>
              <strong>Loading deterministic comparison</strong>
              <p>Reading the synthetic contexts, evidence fingerprints, and unchanged controls.</p>
            </div>
          </section>
        )}

        {loadState.kind === "error" && (
          <section className="error-panel" role="alert">
            <span className="error-mark" aria-hidden="true">!</span>
            <div>
              <strong>Process-aware comparison unavailable</strong>
              <p>{loadState.message}</p>
              <button type="button" onClick={retry}>Retry comparison</button>
            </div>
          </section>
        )}

        {loadState.kind === "ready" && <DemoContent data={loadState.data} />}
      </main>

      <footer className="app-footer">
        <span>Synthetic, deterministic, context-sensitive evidence selection.</span>
        <a href="/">Fixed demo</a>
      </footer>
    </div>
  );
}
