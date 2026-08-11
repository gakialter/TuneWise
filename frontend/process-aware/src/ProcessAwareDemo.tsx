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

const rootCauseLabels: Record<string, string> = {
  PLANE_TILT: "pitch/roll 平面倾斜",
  XY_DECENTER: "X/Y 方向偏心",
  PLATFORM_INSTABILITY: "AA 平台测量波动",
  REFERENCE_DRIFT: "夹具基准或设备标定漂移",
  Z_DEFOCUS_CONDITIONAL: "条件性 Z 向焦点偏移",
};

const candidateTypeLabels: Record<string, string> = {
  CONSERVATIVE: "保守调整方案",
  STANDARD: "标准调整方案",
  CASE_GUIDED: "案例参考方案",
};

function parameterLabel(value: string): string {
  if (value === "pitch") return "pitch（俯仰角）";
  if (value === "roll") return "roll（横滚角）";
  return value;
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
    ["测量数据哈希", evidence.measurement_hash],
    ["检索特征哈希", evidence.query_feature_hash],
    ["特征定义版本", evidence.feature_definition_version],
    ["标准化器版本", evidence.scaler_version],
    ["案例索引哈希", evidence.case_index_hash],
  ];

  return (
    <section className="shared-evidence" aria-labelledby="shared-evidence-title">
      <div className="section-title-row">
        <div>
          <p className="section-kicker">对照实验中保持不变的输入</p>
          <h2 id="shared-evidence-title">两个场景的共同条件</h2>
        </div>
        <span className="shared-lock">
          <span aria-hidden="true">◇</span>
          {evidence.same_across_scenarios ? "A / B 完全相同" : "A / B 条件不一致"}
        </span>
      </div>

      <div className="shared-evidence-grid">
        <div className="evidence-callout measurement-callout">
          <p>测量数据</p>
          <strong>相同</strong>
          <small>{evidence.measurement_evidence_label}</small>
        </div>

        <div className="evidence-callout root-callout">
          <p>根因判断</p>
          <strong>{rootCauseLabels[evidence.top1_root_cause] ?? evidence.top1_root_cause} <span>Top-1</span></strong>
          <ol aria-label="两个场景共用的根因优先级">
            {evidence.ordered_root_causes.map((item) => (
              <li key={item.rank}>
                <span>{String(item.rank).padStart(2, "0")}</span>
                <span>{rootCauseLabels[item.root_cause] ?? item.root_cause}</span>
              </li>
            ))}
          </ol>
        </div>

        <details className="fingerprint-panel technical-details">
          <summary>查看共同输入的技术证据</summary>
          <div className="fingerprint-heading">
            <p>确定性指纹</p>
            <strong>{evidence.feature_dimension} 维</strong>
          </div>
          <dl>
            <div>
              <dt>根因内部类型</dt>
              <dd><code>{evidence.top1_root_cause}</code></dd>
            </div>
            {fingerprints.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd><code title={value} aria-label={`${label}: ${value}`}>{shortFingerprint(value)}</code></dd>
              </div>
            ))}
            <div><dt>模型 / 预处理</dt><dd><code>{evidence.diagnostic_model_version}</code><span aria-hidden="true"> · </span><code>{evidence.preprocessing_version}</code></dd></div>
          </dl>
        </details>
      </div>
    </section>
  );
}

function DecisionHinge({ scenarios }: { scenarios: ProcessAwareScenario[] }) {
  return (
    <section className="decision-hinge" aria-labelledby="decision-hinge-title">
      <div className="hinge-heading">
        <div>
          <p className="section-kicker">一眼看懂这个 A/B 对照</p>
          <h2 id="decision-hinge-title">异常一样，调机过程不同，参考结果也会不同</h2>
        </div>
        <span className="deterministic-label">固定演示结果</span>
      </div>

      <p className="hinge-equation">
        <span>异常数据相同</span>
        <b aria-hidden="true">→</b>
        <span>调机过程不同</span>
        <b aria-hidden="true">→</b>
        <span>当前适用案例不同</span>
        <b aria-hidden="true">→</b>
        <span>案例参考方案不同</span>
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
              <small>{scenario.process_context.process_stage_display.zh}</small>
              <strong>案例 {caseNumber(scenario.eligible_case.case_id)}</strong>
            </div>
            <span className="branch-arrow" aria-hidden="true">→</span>
            <div className="branch-delta">
              <small>案例参考方案</small>
              <strong>{parameterLabel(scenario.case_guided_candidate.parameter_name)} {scenario.case_guided_candidate.delta_ticks} ticks</strong>
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
        <p className="micro-label">上一步调整</p>
        <strong>无</strong>
        <span>当前为第 {context.iteration_index} 轮，未记录上一步动作或结果。</span>
      </div>
    );
  }

  const outcome = context.previous_action_outcome_display;
  return (
    <div className="context-state">
      <p className="micro-label">上一步调整</p>
      <div className="previous-action-value">
        <code>{parameterLabel(context.previous_action.parameter_name)}</code>
        <strong>{context.previous_action.before_value}</strong>
        <span aria-label="changed to">→</span>
        <strong>{context.previous_action.after_value}</strong>
      </div>
      <p className="previous-action-meta">
        变化 {context.previous_action.delta_ticks} tick
      </p>
      <div className="outcome-row">
        <span>调整结果</span>
        {outcome && <strong>{outcome.zh}</strong>}
        <code>{context.previous_action_outcome}</code>
      </div>
    </div>
  );
}

function CandidateReadout({ candidate }: { candidate: CandidateSummary }) {
  return (
    <div className="candidate-readout">
      <div className="candidate-label-row">
        <span>{candidateTypeLabels[candidate.generation_type] ?? candidate.generation_type}</span>
        <code>{candidate.generation_type}</code>
      </div>
      <div className="candidate-delta">
        <div>
          <small>{parameterLabel(candidate.parameter_name)}</small>
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
        <strong>{candidate.validation_status === "PASSED" ? "安全校验通过" : candidate.validation_status}</strong>
        <code>{candidate.validation_status}</code>
      </div>
    </div>
  );
}

function ScenarioCard({ scenario, index }: { scenario: ProcessAwareScenario; index: number }) {
  const letter = scenarioLetters[index] ?? String(index + 1);
  const { process_context: context, eligible_case: eligibleCase } = scenario;
  const profile = eligibleCase.process_profile;
  const compatibilitySummary = context.previous_action === null
    ? `当前处于${context.process_stage_display.zh}，且无上一步调整记录，因此该案例符合当前调机过程。`
    : `当前处于${context.process_stage_display.zh}，上一步调整 ${parameterLabel(context.previous_action.parameter_name)}，结果为${context.previous_action_outcome_display?.zh ?? context.previous_action_outcome}，因此该案例符合当前调机过程。`;

  return (
    <article className={`scenario-card scenario-${letter.toLowerCase()}`} aria-labelledby={`scenario-${letter}-title`}>
      <header className="scenario-header">
        <span className="scenario-letter" aria-hidden="true">{letter}</span>
        <div>
          <p>场景 {letter}</p>
          <h3
            id={`scenario-${letter}-title`}
            aria-label={`${context.process_stage_display.zh} / ${context.process_stage_display.en}`}
          >
            {context.process_stage_display.zh}
            <span>{context.process_stage_display.en}</span>
          </h3>
          <code>{context.process_stage}</code>
        </div>
      </header>

      <div className="synthetic-row" aria-label={`Scenario ${letter} synthetic sources`}>
        <SyntheticStamp label="合成调机过程" sourceKind={context.source_kind} />
        <SyntheticStamp label="合成案例条件" sourceKind={profile.source_kind} />
      </div>

      <PreviousState scenario={scenario} />

      <section className="eligible-case" aria-label={`Scenario ${letter} eligible case`}>
        <div className="eligible-heading">
          <div>
            <p className="micro-label">当前适用案例</p>
            <strong>{eligibleCase.case_id}</strong>
          </div>
          <span className="reason-code">当前调机过程匹配</span>
        </div>
        <p className="case-boundary-note">已审核离线案例 · 合成调机过程条件</p>
        <p className="compatibility-explanation">{compatibilitySummary}</p>
        <div className="distance-readout">
          <span>特征差异距离 <strong>{eligibleCase.distance}</strong></span>
          <small>用于案例排序，不是概率。</small>
        </div>
        <details className="technical-details scenario-technical-details">
          <summary>查看案例适用性与 reason code</summary>
          <dl className="profile-grid">
            <div><dt>适用阶段</dt><dd><code>{profile.compatible_process_stage}</code></dd></div>
            <div><dt>上一步参数</dt><dd>{profile.previous_action_parameter ?? "None"}</dd></div>
            <div><dt>上一步结果</dt><dd><code>{profile.previous_action_outcome ?? "None"}</code></dd></div>
            <div><dt>轮次范围</dt><dd>{profile.minimum_iteration}–{profile.maximum_iteration ?? "∞"}</dd></div>
            <div><dt>reason code</dt><dd><code>{eligibleCase.compatibility.reason_code}</code></dd></div>
            <div><dt>原始解释</dt><dd>{eligibleCase.compatibility.explanation}</dd></div>
          </dl>
        </details>
      </section>

      <CandidateReadout candidate={scenario.case_guided_candidate} />

      <details className="scenario-provenance technical-details">
        <summary>查看场景技术哈希</summary>
        <span>调机过程 <code title={context.context_hash}>{shortFingerprint(context.context_hash)}</code></span>
        <span>案例条件 <code title={profile.profile_hash}>{shortFingerprint(profile.profile_hash)}</code></span>
      </details>
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
        <h3>{candidateTypeLabels[candidate.generation_type] ?? candidate.generation_type}{hashesMatch ? "未改变" : "不一致"}</h3>
      </div>
      <div className="invariant-value">
        <code>{parameterLabel(candidate.parameter_name)}</code>
        <span>{candidate.current_value} → {candidate.proposed_value}</span>
        <strong>{candidate.delta_ticks} ticks</strong>
      </div>
      <p><span className="passed-dot" aria-hidden="true" />{candidate.validation_status === "PASSED" ? "安全校验通过" : candidate.validation_status}</p>
      <details className="technical-details control-proof-details">
        <summary>查看 A / B 候选哈希证据</summary>
        <div
          className="control-hash-proof"
          aria-label={`${candidate.generation_type} A and B candidate hashes ${hashesMatch ? "match" : "do not match"}`}
        >
          <span><small>A hash</small><code title={scenarioHashes.A}>{shortFingerprint(scenarioHashes.A)}</code></span>
          <b aria-hidden="true">{hashesMatch ? "=" : "≠"}</b>
          <span><small>B hash</small><code title={scenarioHashes.B}>{shortFingerprint(scenarioHashes.B)}</code></span>
        </div>
      </details>
    </article>
  );
}

function SafetyInvariant({ validator }: { validator: SafetyValidatorSummary }) {
  return (
    <article className="invariant-card safety-invariant">
      <div className="invariant-title">
        <span className="shield-mark" aria-hidden="true">◇</span>
        <h3>
          安全校验规则{validator.unchanged_across_scenarios ? "未改变" : "不一致"}
        </h3>
      </div>
      <div className="safety-version-row">
        <span>规则版本</span>
        <code>{validator.safety_rule_version}</code>
        <strong>{validator.status}</strong>
      </div>
      <ul aria-label="两个场景共用的安全校验项">
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
          <p className="section-kicker">对照实验控制项</p>
          <h2 id="invariant-band-title">保守、标准方案与安全规则均未改变</h2>
        </div>
        <span className="shared-lock">
          <span aria-hidden="true">=</span>
          {controls.identical_across_scenarios ? "A / B 控制项一致" : "A / B 控制项不一致"}
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
  return (
    <>
      <section className="boundary-strip" aria-label="事实边界">
        <div className="boundary-label">
          <span aria-hidden="true">!</span>
          <strong>事实边界</strong>
        </div>
        <ul>
          <li><strong>这是合成调机过程演示。</strong></li>
          <li>当前演示用于证明 TuneWise 能根据不同调机过程信息选择不同的历史参考案例。</li>
          <li>它不代表{"\u821c\u5b87"}真实调机 SOP，也不证明真实生产环境中的推荐准确率。</li>
        </ul>
        <details className="boundary-english technical-details">
          <summary>English facts boundary</summary>
          <p>Synthetic process-context demonstration. Does not represent Sunny Optical SOP or validated production tuning accuracy.</p>
          <p>{data.facts_boundary}</p>
        </details>
      </section>

      <section className="abstraction-note" aria-label="调机过程信息说明">
        <span>调机过程信息</span>
        <strong>除了当前测量异常，TuneWise 还可以考虑当前处于哪个调机阶段、前一步调整了什么，以及调整后的结果。</strong>
        <small>{data.abstraction_note}</small>
      </section>

      <SharedEvidencePanel evidence={data.shared_evidence} />
      <DecisionHinge scenarios={data.scenarios} />

      <section className="scenario-comparison" data-testid="scenario-comparison" aria-labelledby="scenario-comparison-title">
        <div className="comparison-heading">
          <div>
            <p className="section-kicker">调机过程信息不同</p>
            <h2 id="scenario-comparison-title">两个场景，两条案例参考路径</h2>
          </div>
          <p>只改变合成调机过程信息，观察哪个已审核离线案例能参与案例参考方案。</p>
        </div>
        <div className="scenario-grid">
          {data.scenarios.map((scenario, index) => (
            <ScenarioCard key={scenario.scenario_id} scenario={scenario} index={index} />
          ))}
        </div>
      </section>

      <InvariantBand data={data} />

      <details className="provenance-band technical-details" aria-label="合成演示技术来源">
        <summary>查看演示版本、固定资产与来源</summary>
        <div><span>演示版本</span><code>{data.demo_version}</code></div>
        <div><span>Fixture</span><code>{data.provenance.fixture_version}</code></div>
        <div><span>数据资产</span><code>{data.provenance.demo_dataset_asset_id}</code></div>
        <div><span>来源</span><code>{data.provenance.source_kind}</code></div>
      </details>
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
          message: error instanceof Error ? error.message : "场景对比暂时无法加载。",
        });
      });
    return () => controller.abort();
  }, [requestVersion]);

  return (
    <div className="process-aware-app">
      <a className="skip-link" href="#comparison-main">跳到场景对比</a>
      <header className="app-header">
        <a className="wordmark" href="/" aria-label="返回 TuneWise 固定端到端演示">
          <span className="wordmark-glyph" aria-hidden="true"><i /><i /><i /></span>
          <span><strong>TuneWise</strong><small>证据先于行动</small></span>
        </a>
        <a className="back-link" href="/">
          <span aria-hidden="true">←</span>
          返回固定端到端演示
        </a>
      </header>

      <main id="comparison-main" tabIndex={-1}>
        <section className="hero" aria-labelledby="page-title">
          <div className="hero-index" aria-hidden="true">P/A</div>
          <div className="hero-copy">
            <p className="hero-kicker"><span>合成演示</span> 结合调机过程信息选择参考案例</p>
            <h1 id="page-title">结合调机步骤的决策演示</h1>
            <p className="hero-summary">
              相同异常状态下，当前调机阶段和上一步调整不同，可适用的历史参考案例也会不同。
            </p>
            <small className="hero-technical-title">Process-aware Decision Demo</small>
          </div>
        </section>

        {loadState.kind === "loading" && (
          <section className="load-panel" role="status" aria-live="polite">
            <span className="load-track" aria-hidden="true"><i /></span>
            <div>
              <strong>正在加载场景对比</strong>
              <p>正在读取合成调机过程、共同证据与控制项。</p>
            </div>
          </section>
        )}

        {loadState.kind === "error" && (
          <section className="error-panel" role="alert">
            <span className="error-mark" aria-hidden="true">!</span>
            <div>
              <strong>暂时无法加载调机过程对比</strong>
              <p>{loadState.message}</p>
              <button type="button" onClick={retry}>重新加载</button>
            </div>
          </section>
        )}

        {loadState.kind === "ready" && <DemoContent data={loadState.data} />}
      </main>

      <footer className="app-footer">
        <span>合成、固定、根据调机过程信息选择参考证据。</span>
        <a href="/">固定端到端演示</a>
      </footer>
    </div>
  );
}
