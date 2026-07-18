import { useEffect, useState } from "react";

import {
  AnomalyDetectionResult,
  CaseRetrievalResult,
  confirmParameterPlan,
  ConfirmedPlan,
  createInitialTask,
  generateParameterPlans,
  importPresetAsset,
  ParameterPlanningResult,
  retrieveApprovedCases,
  runAnomalyDetection,
  runRootCauseDiagnosis,
  DiagnosticResult,
  Task,
  TaskCreationError,
} from "./api";

const versionLabels: Record<keyof Task["versions"], string> = {
  public_asset_version: "公共资产",
  application_version: "应用",
  dataset_version: "数据集",
  schema_version: "数据结构",
  generator_version: "生成器",
  rule_set_version: "规则集",
  model_version: "模型",
  preprocessing_version: "预处理",
  evaluation_rule_version: "评价规则",
  canonicalizer_version: "规范化器",
};

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; task: Task }
  | { kind: "error"; code: string; message: string };

type ImportState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; code: string; message: string };

type DetectionState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; code: string; message: string };

type DiagnosisState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; code: string; message: string };

type CaseRetrievalState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; result: CaseRetrievalResult }
  | { kind: "error"; code: string; message: string };

type ParameterPlanningState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; result: ParameterPlanningResult }
  | { kind: "error"; code: string; message: string };

type PlanConfirmationState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; plan: ConfirmedPlan }
  | { kind: "error"; code: string; message: string };

const candidateTerminalConfirmationCodes = new Set([
  "CANDIDATE_STALE",
  "CANDIDATE_HASH_MISMATCH",
  "CANDIDATE_NOT_CURRENT",
  "CANDIDATE_NOT_PASSED",
  "SAFETY_REVALIDATION_FAILED",
]);

const contextTerminalConfirmationCodes = new Set([
  "PLANNING_RESULT_STALE",
  "CURRENT_PARAMETER_MISMATCH",
  "SNAPSHOT_VERSION_MISMATCH",
  "CONTROL_LIMIT_SNAPSHOT_CHANGED",
  "PARAMETER_CONSTRAINT_SNAPSHOT_CHANGED",
  "RULE_VERSION_CHANGED",
  "RETRIEVAL_VERSION_CHANGED",
  "CONFIRMED_PLAN_CONFLICT",
]);

const detectionCopy: Record<
  AnomalyDetectionResult["anomaly_result"],
  { title: string; summary: string; tone: string }
> = {
  TARGET_ANOMALY: {
    title: "检测到四角 MTF 不对称下降",
    summary: "中心门控、四角异常信号与持续性条件均成立，任务已推进到异常检测阶段。",
    tone: "target",
  },
  NORMAL: {
    title: "未超过原型控制限",
    summary: "当前中心与四角指标未同时满足目标异常或整体退化规则。",
    tone: "normal",
  },
  NON_TARGET_GLOBAL_DEGRADATION: {
    title: "非目标整体退化场景",
    summary: "中心与四角呈整体下降，整体退化保护规则优先阻止进入四角不对称主流程。",
    tone: "protected",
  },
  INSUFFICIENT_DATA: {
    title: "数据不足，检测已保护停止",
    summary: "样本数量、必需字段或持续性计算条件不足，系统未使用默认值继续判断。",
    tone: "insufficient",
  },
};

const ruleLabels: Record<string, string> = {
  INPUT_DATA_SUFFICIENT: "输入数据完整性",
  GLOBAL_DEGRADATION_PROTECTION: "整体退化保护",
  CENTER_NOT_CLEARLY_LOW: "中心 MTF 门控",
  CORNER_MIN_LIMIT: "最差角下限",
  CORNER_RANGE_LIMIT: "四角极差限",
  CORNER_STD_LIMIT: "四角离散限",
  CORNER_SIGNAL_PRESENT: "四角异常信号",
  MINIMUM_CONSECUTIVE_VIOLATIONS: "最小连续越限",
  MINIMUM_VIOLATION_RATIO: "最小越限比例",
  PERSISTENCE_CONDITION: "持续性条件",
  TARGET_ANOMALY_DECISION: "目标异常决策",
};

const parameterLabels: Record<string, string> = {
  x_offset: "X 偏移",
  y_offset: "Y 偏移",
  pitch: "Pitch",
  roll: "Roll",
  z_offset: "Z 偏移",
};

const platformLabels: Record<string, string> = {
  vibration_rms: "振动 RMS",
  repeat_position_error: "重复定位误差",
  calibration_residual_x: "X 标定残差",
  calibration_residual_y: "Y 标定残差",
};

function DetectionResultView({
  detection,
}: {
  detection: AnomalyDetectionResult;
}) {
  const copy = detectionCopy[detection.anomaly_result];
  const protectedResult = detection.anomaly_result !== "TARGET_ANOMALY";
  const metrics = [
    {
      label: "中心 MTF",
      value: detection.aggregate_metrics.mtf_center,
      limitLabel: "中心下限",
      limit: detection.control_limits.center_lower_limit,
    },
    {
      label: "最差角落 MTF",
      value: detection.aggregate_metrics.corner_mtf_min,
      limitLabel: "角落下限",
      limit: detection.control_limits.corner_lower_limit,
    },
    {
      label: "四角极差",
      value: detection.aggregate_metrics.corner_mtf_range,
      limitLabel: "不对称限",
      limit: detection.control_limits.asymmetry_limit,
    },
    {
      label: "四角标准差",
      value: detection.aggregate_metrics.corner_mtf_std,
      limitLabel: "离散限",
      limit: detection.control_limits.corner_std_limit,
    },
  ];

  return (
    <div className={`detection-result detection-${copy.tone}`}>
      <div className="detection-result-heading">
        <div>
          <span className="result-code">{detection.anomaly_result}</span>
          <h3>{copy.title}</h3>
          <p>{copy.summary}</p>
        </div>
        <div className="detection-binding" aria-label="检测版本与输入哈希">
          <code>规则集 {detection.rule_set_version}</code>
          <code>输入 {detection.input_hash.slice(0, 12)}</code>
        </div>
      </div>

      {protectedResult && (
        <div className="route-protection" role="note">
          <strong>主流程已停止</strong>
          <span>未满足的规则见下方结构化证据。</span>
          <span className="protection-statement">不生成根因诊断或参数建议。</span>
        </div>
      )}

      <dl className="detection-metrics" aria-label="指标与控制限对照">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>{metric.value ?? "不可用"}</dd>
            <small>
              {metric.limitLabel} {metric.limit}
            </small>
          </div>
        ))}
      </dl>

      <div className="detection-evidence-grid">
        <section aria-labelledby="persistence-title" className="persistence-card">
          <p className="metric-label" id="persistence-title">持续性证据</p>
          <dl>
            <div>
              <dt>越限样本数量</dt>
              <dd>
                {detection.persistence_evidence.violating_sample_count} / {detection.persistence_evidence.sample_count}
              </dd>
            </div>
            <div>
              <dt>越限样本比例</dt>
              <dd>
                {detection.persistence_evidence.violation_ratio} / {detection.persistence_evidence.minimum_violation_ratio}
              </dd>
            </div>
            <div>
              <dt>最大连续越限</dt>
              <dd>
                {detection.persistence_evidence.maximum_consecutive_violations} / {detection.persistence_evidence.minimum_consecutive_violations}
              </dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="checks-title" className="rule-checks-card">
          <p className="metric-label" id="checks-title">逐项规则检查</p>
          <ol className="rule-check-list">
            {detection.rule_checks.map((check) => (
              <li key={check.rule_id}>
                <span className={`check-status check-${check.status.toLowerCase()}`}>
                  {check.status}
                </span>
                <div>
                  <strong>{ruleLabels[check.rule_id] ?? check.rule_id}</strong>
                  <p>{check.detail}</p>
                  {check.actual !== null && (
                    <code>
                      actual {check.actual}
                      {check.operator && check.threshold
                        ? ` ${check.operator} ${check.threshold}`
                        : ""}
                    </code>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}

const rootCauseLabels: Record<string, string> = {
  PLANE_TILT: "Pitch/Roll 平面倾斜",
  XY_DECENTER: "X/Y 方向偏心",
  PLATFORM_INSTABILITY: "AA 平台测量波动",
  REFERENCE_DRIFT: "夹具基准或设备标定漂移",
  Z_DEFOCUS_CONDITIONAL: "条件性 Z 向焦点偏移",
};

function DiagnosisResultView({ diagnostic }: { diagnostic: DiagnosticResult }) {
  const sufficient = diagnostic.evidence_status === "SUFFICIENT_EVIDENCE";
  return (
    <div className="diagnosis-result">
      <div className={`evidence-banner ${sufficient ? "evidence-sufficient" : "evidence-insufficient"}`} role="status">
        <div>
          <span className="result-code">{diagnostic.evidence_status}</span>
          <h3>{sufficient ? "诊断证据满足冻结规则" : "诊断证据不足，仅供排查"}</h3>
          <p>
            {sufficient
              ? "Top-1 得分、类别间距、兼容规则与完整性检查均通过。"
              : "仍展示 Top-3 排查顺序；参数候选数量固定为 0，后续流程保持关闭。"}
          </p>
        </div>
        <code title={diagnostic.result_hash}>业务结果 {diagnostic.result_hash.slice(0, 12)}</code>
      </div>

      <div className="diagnosis-heading">
        <div>
          <p className="section-kicker">固定模型 · 结构化解释</p>
          <h2>Top-3 根因排查顺序</h2>
        </div>
        <p>相对分数用于当前五类候选排序，不表示真实故障概率。</p>
      </div>

      <ol className="root-cause-list">
        {diagnostic.ordered_top3.map((candidate) => (
          <li key={candidate.root_cause} className="root-cause-card">
            <header>
              <span className="root-cause-rank">#{candidate.rank}</span>
              <div>
                <strong>{candidate.root_cause}</strong>
                <small>{rootCauseLabels[candidate.root_cause] ?? candidate.root_cause}</small>
              </div>
              <span className={`adjustability ${candidate.adjustability === "ADJUSTABLE" ? "adjustable" : "inspection-only"}`}>
                {candidate.adjustability === "ADJUSTABLE" ? "可调" : "仅排查"}
              </span>
              <div className="relative-score">
                <span>相对分数</span>
                <strong>{(Number(candidate.normalized_score) * 100).toFixed(2)}%</strong>
                <small>logit {candidate.raw_logit}</small>
              </div>
            </header>
            <div className="candidate-evidence-grid">
              <section>
                <h4>显式规则与关键观测</h4>
                <ul className="structured-list">
                  {candidate.matched_explicit_rules.map((rule) => (
                    <li key={rule.rule_id}><strong>{rule.rule_id}</strong><span>{rule.detail}</span></li>
                  ))}
                  {candidate.key_observations.map((item) => (
                    <li key={item.feature_name}><strong>{item.feature_name}</strong><span>{item.summary}</span></li>
                  ))}
                </ul>
              </section>
              <section>
                <h4>主要正向 logit 贡献</h4>
                <ol className="contribution-list">
                  {candidate.positive_logit_contributions.map((item) => (
                    <li key={item.feature_index}>
                      <div><strong>{item.feature_name}</strong><code>{item.contribution}</code></div>
                      <small>{item.description}</small>
                    </li>
                  ))}
                </ol>
              </section>
              <section>
                <h4>冲突证据</h4>
                {candidate.conflict_evidence.length ? (
                  <ul className="structured-list conflict-list">
                    {candidate.conflict_evidence.map((item) => (
                      <li key={item.rule_id}><strong>{item.rule_id}</strong><span>{item.detail}</span></li>
                    ))}
                  </ul>
                ) : <p className="empty-evidence">未发现当前类别的显式规则冲突。</p>}
              </section>
            </div>
          </li>
        ))}
      </ol>

      <div className="diagnosis-footer-grid">
        <section>
          <h4>Z 类硬门控</h4>
          <strong>{diagnostic.z_gate_result.status}</strong>
          <p>
            {diagnostic.z_gate_result.passed
              ? "中心、四角整体下降及非主导不对称条件均成立。"
              : "Z 类已从展示候选移除，其余类别已重新归一化。"}
          </p>
        </section>
        <section>
          <h4>诊断资产版本</h4>
          <dl>
            <div><dt>结果</dt><dd>{diagnostic.diagnostic_result_version}</dd></div>
            <div><dt>模型</dt><dd>{diagnostic.model_version}</dd></div>
            <div><dt>预处理器</dt><dd>{diagnostic.preprocessing_version}</dd></div>
            <div><dt>特征定义</dt><dd>{diagnostic.feature_definition_version}</dd></div>
            <div><dt>证据规则</dt><dd>{diagnostic.evidence_rule_version}</dd></div>
          </dl>
        </section>
        <section>
          <h4>证据检查</h4>
          <ul className="evidence-check-summary">
            {diagnostic.evidence_checks.map((check) => (
              <li key={check.rule_id}><span>{check.rule_id}</span><strong>{check.status}</strong></li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

function CaseRetrievalResultView({ result }: { result: CaseRetrievalResult }) {
  const empty = result.retrieval_status === "NO_RELEVANT_CASE_AVAILABLE";
  return (
    <div className="case-retrieval-result">
      <div className={`case-retrieval-status ${empty ? "case-retrieval-empty" : ""}`} role="status">
        <div>
          <span className="result-code">{result.retrieval_status}</span>
          <strong>
            {empty
              ? "暂无兼容已审核案例"
              : `已返回 ${result.returned_count} 个兼容已审核案例`}
          </strong>
          {result.shortfall_message && <p>{result.shortfall_message}</p>}
        </div>
        <dl aria-label="案例检索版本">
          <div><dt>案例索引</dt><dd>{result.case_index_version}</dd></div>
          <div><dt>检索标准化器</dt><dd>{result.scaler_version}</dd></div>
          <div><dt>兼容规则</dt><dd>{result.compatibility_rule_version}</dd></div>
        </dl>
      </div>

      {!empty && (
        <ol className="approved-case-list">
          {result.ordered_cases.map((approvedCase) => (
            <li
              key={approvedCase.case_id}
              className="approved-case-card"
              aria-label={`已审核案例 ${approvedCase.case_id}`}
            >
              <header>
                <span className="case-rank">#{approvedCase.rank}</span>
                <div>
                  <strong>{approvedCase.case_id}</strong>
                  <small>{approvedCase.product_model}</small>
                </div>
                <span className="approved-badge">APPROVED</span>
                <div className="case-distance">
                  <strong>距离 {approvedCase.distance}</strong>
                  <small>中性显示值 {approvedCase.similarity_display_value}</small>
                </div>
              </header>

              <div className="case-facts">
                <div>
                  <span>已审核根因</span>
                  <strong>{approvedCase.reviewed_root_cause}</strong>
                </div>
                <div>
                  <span>候选阶段</span>
                  <strong>
                    {approvedCase.retrieval_stage === "TOP3_ROOT_CAUSE"
                      ? "Top-3 根因池"
                      : "兼容补足池"}
                  </strong>
                </div>
                <div>
                  <span>案例内容哈希</span>
                  <code title={approvedCase.case_content_hash}>
                    {approvedCase.case_content_hash.slice(0, 12)}
                  </code>
                </div>
              </div>

              <div className="case-detail-grid">
                <section>
                  <h4>关键特征差异</h4>
                  <ol className="feature-difference-list">
                    {approvedCase.key_feature_differences.map((difference) => (
                      <li key={difference.feature_index}>
                        <div>
                          <strong>{difference.feature_name}</strong>
                          <code>Δz {difference.standardized_absolute_difference}</code>
                        </div>
                        <small>
                          当前 {difference.query_value} · 案例 {difference.case_value}
                        </small>
                      </li>
                    ))}
                  </ol>
                </section>
                <section>
                  <h4>历史处理动作</h4>
                  <p>{approvedCase.historical_action.summary}</p>
                  <h4 className="historical-result-label">
                    {approvedCase.historical_simulated_result.context_label}
                  </h4>
                  <p>{approvedCase.historical_simulated_result.summary}</p>
                </section>
                <section>
                  <h4>适用条件</h4>
                  <ul className="case-condition-list">
                    {approvedCase.applicability_conditions.map((condition) => (
                      <li key={condition}>{condition}</li>
                    ))}
                  </ul>
                  <dl className="case-source-versions">
                    <div>
                      <dt>来源数据</dt>
                      <dd>{approvedCase.source_version_summary.source_dataset_version}</dd>
                    </div>
                    <div>
                      <dt>案例结构</dt>
                      <dd>{approvedCase.source_version_summary.case_schema_version}</dd>
                    </div>
                  </dl>
                </section>
              </div>
            </li>
          ))}
        </ol>
      )}

      <p className="case-retrieval-disclaimer" role="note">
        距离仅衡量固定可观测批次特征的结构化接近程度，不表示根因真实性、因果关系或真实设备适用概率。
        历史结果仅指规则约束模拟环境中的离线回放，不代表真实产线良率改善。
      </p>
    </div>
  );
}

function ParameterPlanningResultView({
  result,
  actor,
  selectedCandidateId,
  onSelectCandidate,
  onConfirm,
  confirmationState,
  confirmedPlan,
  invalidCandidateIds,
  confirmationContextInvalid,
}: {
  result: ParameterPlanningResult;
  actor: Task["actor"];
  selectedCandidateId: string | null;
  onSelectCandidate: (candidateId: string) => void;
  onConfirm: () => void;
  confirmationState: PlanConfirmationState;
  confirmedPlan?: ConfirmedPlan | null;
  invalidCandidateIds: ReadonlySet<string>;
  confirmationContextInvalid: boolean;
}) {
  const constraints = Object.fromEntries(
    result.parameter_constraints.map((constraint) => [constraint.parameter_name, constraint]),
  );

  return (
    <div className="parameter-planning-result">
      <div
        className={`planning-status planning-status-${result.planning_status.toLowerCase()}`}
        role="status"
      >
        <div>
          <span>规划状态</span>
          <strong>{result.planning_status}</strong>
          {result.refusal_message && <p>{result.refusal_message}</p>}
        </div>
        {result.refusal_code && <code>{result.refusal_code}</code>}
      </div>

      {result.supporting_evidence.length > 0 && (
        <section className="planning-evidence-summary" aria-labelledby="planning-evidence-summary-title">
          <h3 id="planning-evidence-summary-title">规划依据摘要</h3>
          <ul>
            {result.supporting_evidence.map((evidence) => (
              <li key={evidence}>{evidence}</li>
            ))}
          </ul>
        </section>
      )}

      {result.direction_evidence.length > 0 && (
        <section className="direction-evidence-section" aria-labelledby="direction-evidence-title">
          <h3 id="direction-evidence-title">参数方向证据</h3>
          <div className="direction-evidence-grid">
            {result.direction_evidence.map((evidence) => (
              <article key={evidence.parameter_name} className="direction-evidence-card">
                <header>
                  <strong>{parameterLabels[evidence.parameter_name] ?? evidence.parameter_name}</strong>
                  <span className={`conflict-${evidence.conflict_status.toLowerCase()}`}>
                    {evidence.conflict_status}
                  </span>
                </header>
                <dl>
                  <div><dt>当前值</dt><dd>{evidence.current_value} · {evidence.current_tick} ticks</dd></div>
                  <div><dt>标称值</dt><dd>{evidence.nominal_value} · {evidence.nominal_tick} ticks</dd></div>
                  <div><dt>方向</dt><dd>{evidence.recommended_direction}</dd></div>
                </dl>
                <p>{evidence.supporting_features.join("；") || "无充分空间轴支持"}</p>
                {evidence.conflicting_features.length > 0 && (
                  <p className="direction-conflict">
                    冲突或不足：{evidence.conflicting_features.join("；")}
                  </p>
                )}
                <small title={evidence.evidence_hash}>
                  证据哈希 {evidence.evidence_hash.slice(0, 12)}
                </small>
              </article>
            ))}
          </div>
        </section>
      )}

      {result.ordered_candidates.length > 0 && (
        <section className="planning-candidates" aria-labelledby="planning-candidates-title">
          <h3 id="planning-candidates-title">通过当前证据和安全规则生成的候选方案</h3>
          <p className="planning-readonly-note">
            候选参数为服务端只读内容；请选择一组 PASSED 候选进行人工确认。
          </p>
          <ol className="planning-candidate-list">
            {result.ordered_candidates.map((candidate, index) => {
              const changedParameters = Object.keys(candidate.delta_ticks);
              return (
                <li
                  key={candidate.candidate_id}
                  className="planning-candidate-card"
                  aria-label={`安全参数候选 ${index + 1}`}
                >
                  <header>
                    <span className="candidate-order">{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <strong>{candidate.generation_type}</strong>
                      <small>{candidate.candidate_id}</small>
                    </div>
                    <span>{candidate.total_absolute_delta_ticks} total ticks</span>
                    <span>支持案例 {candidate.supporting_case_count}</span>
                  </header>

                  {!confirmedPlan && (
                    <label className="candidate-selection">
                      <input
                        type="radio"
                        name="parameter-plan-candidate"
                        value={candidate.candidate_id}
                        checked={selectedCandidateId === candidate.candidate_id}
                        disabled={
                          candidate.validation_status !== "PASSED" ||
                          confirmationContextInvalid ||
                          invalidCandidateIds.has(candidate.candidate_id) ||
                          confirmationState.kind === "loading"
                        }
                        onChange={() => onSelectCandidate(candidate.candidate_id)}
                      />
                      <span>
                        {invalidCandidateIds.has(candidate.candidate_id)
                          ? "该候选已失效"
                          : `选择 ${candidate.generation_type} 候选`}
                      </span>
                    </label>
                  )}

                  <div className="candidate-parameter-grid">
                    {changedParameters.map((parameterName) => {
                      const constraint = constraints[parameterName];
                      return (
                        <section key={parameterName}>
                          <h4>{parameterLabels[parameterName] ?? parameterName}</h4>
                          <dl>
                            <div><dt>当前值</dt><dd>{candidate.current_values[parameterName]}</dd></div>
                            <div><dt>建议值</dt><dd>{candidate.proposed_values[parameterName]}</dd></div>
                            <div>
                              <dt>变化量</dt>
                              <dd>{candidate.deltas[parameterName]} · {candidate.delta_ticks[parameterName]} ticks</dd>
                            </div>
                          </dl>
                          {constraint && (
                            <p className="constraint-summary">
                              <span>[{constraint.minimum}, {constraint.maximum}]</span>
                              <span>步长 {constraint.step}</span>
                              <span>最大变化 {constraint.maximum_single_plan_delta}</span>
                            </p>
                          )}
                        </section>
                      );
                    })}
                  </div>

                  {candidate.supporting_case_ids.length > 0 && (
                    <p className="supporting-cases">
                      <strong>参与计算的案例</strong> {candidate.supporting_case_ids.join("、")}
                    </p>
                  )}

                  <details className="validation-details">
                    <summary>逐项安全校验 · {candidate.validation_status}</summary>
                    <ul>
                      {candidate.validation_checks.map((check) => (
                        <li key={check.check_code}>
                          <code>{check.check_code}</code>
                          <strong>{check.status}</strong>
                          <span>{check.detail}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                  <p className="candidate-hash" title={candidate.candidate_hash}>
                    候选哈希 {candidate.candidate_hash.slice(0, 16)}
                  </p>
                </li>
              );
            })}
          </ol>

          {!confirmedPlan && (
            <section
              className="confirmation-panel"
              aria-labelledby="confirmation-title"
              aria-live="polite"
            >
              <div>
                <p className="section-kicker">固定身份 · 显式人工动作</p>
                <h3 id="confirmation-title">人工确认候选方案</h3>
                <p>
                  确认身份：{actor.display_name} · {actor.actor_role}
                </p>
                {selectedCandidateId ? (
                  <p className="confirmation-selection-summary">
                    已选择 {selectedCandidateId}
                  </p>
                ) : (
                  <p className="confirmation-selection-summary">请先选择一组 PASSED 候选。</p>
                )}
              </div>
              <button
                className="primary-action confirmation-action"
                type="button"
                disabled={
                  confirmationContextInvalid ||
                  !selectedCandidateId ||
                  confirmationState.kind === "loading"
                }
                onClick={onConfirm}
              >
                人工确认候选方案
              </button>
              {confirmationState.kind === "loading" && (
                <div className="confirmation-progress" role="status">
                  <span className="inline-loader" />
                  <span>正在冻结候选并执行服务端安全复核…</span>
                </div>
              )}
              {confirmationState.kind === "error" && (
                <div className="inline-error confirmation-error" role="alert">
                  <div>
                    <strong>人工确认已拒绝</strong>
                    <p>{confirmationState.message}</p>
                  </div>
                  <code>{confirmationState.code}</code>
                </div>
              )}
            </section>
          )}
        </section>
      )}

      {confirmedPlan && (
        <section
          className={`confirmed-plan confirmed-plan-${confirmedPlan.status.toLowerCase()}`}
          aria-labelledby="confirmed-plan-title"
          aria-live="polite"
        >
          {confirmedPlan.status === "STALE" ? (
            <>
              <p className="section-kicker">STALE · 不可用于未来回放</p>
              <h3 id="confirmed-plan-title">方案已过期，需要重新生成并确认</h3>
              <ul className="stale-reasons">
                {confirmedPlan.stale_reason_codes.map((reason) => (
                  <li key={reason}><code>{reason}</code></li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <p className="section-kicker">VALID · 不可变 ConfirmedPlan</p>
              <h3 id="confirmed-plan-title">方案已人工确认并冻结</h3>
              <div className="confirmed-plan-grid">
                <dl>
                  <div><dt>候选</dt><dd>{confirmedPlan.candidate_id}</dd></div>
                  <div><dt>参数族</dt><dd>{confirmedPlan.parameter_family}</dd></div>
                  <div><dt>生成类型</dt><dd>{confirmedPlan.generation_type}</dd></div>
                </dl>
                <dl>
                  <div>
                    <dt>确认身份</dt>
                    <dd>
                      {confirmedPlan.display_name} · {confirmedPlan.actor_id} · {confirmedPlan.actor_role}
                    </dd>
                  </div>
                  <div><dt>确认时间</dt><dd>{confirmedPlan.confirmed_at}</dd></div>
                  <div>
                    <dt>确认方案哈希</dt>
                    <dd title={confirmedPlan.confirmed_plan_hash}>
                      {confirmedPlan.confirmed_plan_hash.slice(0, 16)}
                    </dd>
                  </div>
                </dl>
              </div>
              <p className="confirmation-disclaimer">
                此操作只冻结离线候选方案；尚未进行模拟回放；未向真实设备写入任何参数。
              </p>
            </>
          )}
        </section>
      )}

      {result.recommended_inspection_actions.length > 0 && (
        <section className="inspection-actions" aria-labelledby="inspection-actions-title">
          <h3 id="inspection-actions-title">版本化排查建议</h3>
          <ul>
            {result.recommended_inspection_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </section>
      )}

      <dl className="planning-version-grid">
        <div><dt>方向规则</dt><dd>{result.direction_rule_version}</dd></div>
        <div><dt>安全规则</dt><dd>{result.safety_rule_version}</dd></div>
        <div><dt>约束快照</dt><dd>{result.constraint_snapshot_version}</dd></div>
        <div><dt>规划规则</dt><dd>{result.planning_rule_version}</dd></div>
        <div><dt>结果哈希</dt><dd title={result.result_hash}>{result.result_hash.slice(0, 16)}</dd></div>
      </dl>
    </div>
  );
}

function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [importState, setImportState] = useState<ImportState>({ kind: "idle" });
  const [detectionState, setDetectionState] = useState<DetectionState>({
    kind: "idle",
  });
  const [diagnosisState, setDiagnosisState] = useState<DiagnosisState>({ kind: "idle" });
  const [caseRetrievalState, setCaseRetrievalState] = useState<CaseRetrievalState>({
    kind: "idle",
  });
  const [parameterPlanningState, setParameterPlanningState] =
    useState<ParameterPlanningState>({ kind: "idle" });
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [invalidCandidateIds, setInvalidCandidateIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [confirmationContextInvalid, setConfirmationContextInvalid] =
    useState(false);
  const [confirmationState, setConfirmationState] =
    useState<PlanConfirmationState>({ kind: "idle" });

  useEffect(() => {
    let active = true;
    createInitialTask()
      .then((task) => {
        if (active) setState({ kind: "ready", task });
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof TaskCreationError) {
          setState({ kind: "error", code: error.code, message: error.message });
          return;
        }
        setState({
          kind: "error",
          code: "LOCAL_APP_UNAVAILABLE",
          message: "本地应用服务暂时不可用。",
        });
      });
    return () => {
      active = false;
    };
  }, []);

  if (state.kind === "loading") {
    return (
      <main className="centered-state" aria-live="polite">
        <span className="loader" />
        <p>正在校验本地版本资产并创建任务…</p>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="centered-state error-state" role="alert">
        <span className="error-mark">!</span>
        <p className="eyebrow">任务创建已拒绝</p>
        <h1>{state.message}</h1>
        <code>{state.code}</code>
        <p className="error-help">请恢复交付包中的公共版本资产后重新启动。</p>
      </main>
    );
  }

  const { task } = state;
  const dataImport = task.data_import;
  const currentStageIndex = task.stages.findIndex(
    (stage) => stage.availability === "current",
  );

  async function handlePresetImport() {
    setImportState({ kind: "loading" });
    try {
      const importedTask = await importPresetAsset(task.task_id);
      setState({ kind: "ready", task: importedTask });
      setImportState({ kind: "idle" });
      setDetectionState({ kind: "idle" });
      setDiagnosisState({ kind: "idle" });
      setCaseRetrievalState({ kind: "idle" });
      setParameterPlanningState({ kind: "idle" });
      setSelectedCandidateId(null);
      setInvalidCandidateIds(new Set());
      setConfirmationContextInvalid(false);
      setConfirmationState({ kind: "idle" });
    } catch (error: unknown) {
      if (error instanceof TaskCreationError) {
        setImportState({ kind: "error", code: error.code, message: error.message });
        return;
      }
      setImportState({
        kind: "error",
        code: "DATA_IMPORT_FAILED",
        message: "本地数据导入服务暂时不可用。",
      });
    }
  }

  async function handleDetection() {
    setDetectionState({ kind: "loading" });
    try {
      const response = await runAnomalyDetection(
        task.task_id,
        task.versions.dataset_version,
      );
      setState({ kind: "ready", task: response.task });
      setDetectionState({ kind: "idle" });
      setDiagnosisState({ kind: "idle" });
      setCaseRetrievalState({ kind: "idle" });
      setParameterPlanningState({ kind: "idle" });
      setSelectedCandidateId(null);
      setInvalidCandidateIds(new Set());
      setConfirmationContextInvalid(false);
      setConfirmationState({ kind: "idle" });
    } catch (error: unknown) {
      if (error instanceof TaskCreationError) {
        setDetectionState({
          kind: "error",
          code: error.code,
          message: error.message,
        });
        return;
      }
      setDetectionState({
        kind: "error",
        code: "ANOMALY_DETECTION_FAILED",
        message: "本地异常检测服务暂时不可用。",
      });
    }
  }

  async function handleDiagnosis() {
    if (!task.anomaly_detection) return;
    setDiagnosisState({ kind: "loading" });
    try {
      const response = await runRootCauseDiagnosis(
        task.task_id,
        task.anomaly_detection.detection_result_id,
      );
      setState({ kind: "ready", task: response.task });
      setDiagnosisState({ kind: "idle" });
      setCaseRetrievalState({ kind: "idle" });
      setParameterPlanningState({ kind: "idle" });
      setSelectedCandidateId(null);
      setInvalidCandidateIds(new Set());
      setConfirmationContextInvalid(false);
      setConfirmationState({ kind: "idle" });
    } catch (error: unknown) {
      if (error instanceof TaskCreationError) {
        setDiagnosisState({ kind: "error", code: error.code, message: error.message });
        return;
      }
      setDiagnosisState({
        kind: "error",
        code: "ROOT_CAUSE_DIAGNOSIS_FAILED",
        message: "本地根因诊断服务暂时不可用。",
      });
    }
  }

  async function handleCaseRetrieval() {
    if (!task.diagnostic_result) return;
    setCaseRetrievalState({ kind: "loading" });
    try {
      const response = await retrieveApprovedCases(
        task.task_id,
        task.diagnostic_result.diagnostic_result_id,
      );
      setCaseRetrievalState({ kind: "success", result: response.retrieval });
    } catch (error: unknown) {
      if (error instanceof TaskCreationError) {
        setCaseRetrievalState({
          kind: "error",
          code: error.code,
          message: error.message,
        });
        return;
      }
      setCaseRetrievalState({
        kind: "error",
        code: "APPROVED_CASE_RETRIEVAL_FAILED",
        message: "本地案例检索服务暂时不可用。",
      });
    }
  }

  async function handleParameterPlanning() {
    if (!task.diagnostic_result) return;
    setParameterPlanningState({ kind: "loading" });
    try {
      const response = await generateParameterPlans(
        task.task_id,
        task.diagnostic_result.diagnostic_result_id,
        caseRetrievalState.kind === "success"
          ? caseRetrievalState.result.retrieval_result_id
          : null,
      );
      setState({ kind: "ready", task: response.task });
      setParameterPlanningState({ kind: "success", result: response.planning });
      setSelectedCandidateId(null);
      setInvalidCandidateIds(new Set());
      setConfirmationContextInvalid(false);
      setConfirmationState({ kind: "idle" });
    } catch (error: unknown) {
      if (error instanceof TaskCreationError) {
        setParameterPlanningState({
          kind: "error",
          code: error.code,
          message: error.message,
        });
        return;
      }
      setParameterPlanningState({
        kind: "error",
        code: "PARAMETER_PLANNING_FAILED",
        message: "本地参数规划服务暂时不可用。",
      });
    }
  }

  async function handlePlanConfirmation() {
    const planning =
      parameterPlanningState.kind === "success"
        ? parameterPlanningState.result
        : task.parameter_planning_result;
    if (!planning || !selectedCandidateId || task.confirmed_plan) return;
    const candidate = planning.ordered_candidates.find(
      (item) =>
        item.candidate_id === selectedCandidateId &&
        item.validation_status === "PASSED",
    );
    if (!candidate) return;
    setConfirmationState({ kind: "loading" });
    try {
      const response = await confirmParameterPlan(
        task.task_id,
        candidate.candidate_id,
        candidate.candidate_hash,
      );
      setState({ kind: "ready", task: response.task });
      setConfirmationState({ kind: "success", plan: response.confirmed_plan });
    } catch (error: unknown) {
      if (error instanceof TaskCreationError) {
        if (candidateTerminalConfirmationCodes.has(error.code)) {
          setInvalidCandidateIds((current) => {
            const next = new Set(current);
            next.add(candidate.candidate_id);
            return next;
          });
          setSelectedCandidateId(null);
        }
        if (contextTerminalConfirmationCodes.has(error.code)) {
          setConfirmationContextInvalid(true);
          setSelectedCandidateId(null);
        }
        setConfirmationState({
          kind: "error",
          code: error.code,
          message: error.message,
        });
        return;
      }
      setConfirmationState({
        kind: "error",
        code: "PLAN_CONFIRMATION_FAILED",
        message: "本地人工确认服务暂时不可用。",
      });
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        跳到主要内容
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#workspace" aria-label="TuneWise 首页">
            <span className="brand-mark">TW</span>
            <span>
              <strong>TuneWise</strong>
              <small>离线调机决策支持</small>
            </span>
          </a>
          <div className="topbar-context">
            <span>演示身份</span>
            <strong>{task.actor.display_name}</strong>
            <code>{task.actor.actor_role}</code>
          </div>
          <div className="offline-badge" role="status" aria-label="应用运行于本地离线模式">
            <span className="status-dot" />
            本地离线
          </div>
        </div>
      </header>

      <main id="workspace" className="workspace" tabIndex={-1}>
        <section className="task-overview" aria-label="任务概览">
          <div className="task-heading">
            <p className="context-label">AA 工站 / 调机任务</p>
            <div className="title-row">
              <h1>任务与版本状态</h1>
              <span className="readonly-label">只读工作区</span>
            </div>
            <p className="hero-copy">
              {dataImport
                ? "预置 AA 批次已完成版本、格式与内容完整性校验，任务已推进到数据导入阶段。"
                : "本地版本资产已通过完整性校验。请选择冻结的预置 AA 批次完成数据导入。"}
            </p>
          </div>
          <dl className="task-summary">
            <div className="task-state">
              <dt>当前任务状态</dt>
              <dd>{task.status}</dd>
            </div>
            <div>
              <dt>任务 ID</dt>
              <dd>{task.task_id}</dd>
            </div>
            <div>
              <dt>公共资产</dt>
              <dd className="verified-value">
                <span className="status-dot" />
                完整性已验证
              </dd>
            </div>
          </dl>
        </section>

        <section className="import-panel" aria-labelledby="import-title">
          <div className="import-intro">
            <div>
              <p className="section-kicker">版本化演示资产</p>
              <h2 id="import-title">导入 AA 观测批次</h2>
              <p className="import-copy">
                服务端校验冻结字段、DatasetManifest、版本、原始字节哈希与规范化观测哈希。
              </p>
            </div>
            <div className="preset-asset-card">
              <span>预置资产</span>
              <strong>tw-aa-demo-v1</strong>
              <small>AA · TW-AA-PROTOTYPE-V1</small>
            </div>
            <button
              className="primary-action"
              type="button"
              disabled={importState.kind === "loading" || Boolean(dataImport)}
              onClick={handlePresetImport}
            >
              {dataImport ? "导入已完成" : "导入预置 AA 异常批次"}
            </button>
          </div>

          {importState.kind === "loading" && (
            <div className="import-progress" role="status" aria-live="polite">
              <span className="inline-loader" />
              <span>正在校验 CSV、Manifest 与内容哈希…</span>
            </div>
          )}

          {importState.kind === "error" && (
            <div className="inline-error" role="alert">
              <div>
                <strong>导入已拒绝</strong>
                <p>{importState.message}</p>
              </div>
              <code>{importState.code}</code>
            </div>
          )}

          {dataImport && (
            <div className="import-result">
              <div className="result-heading">
                <div>
                  <span className="success-mark">✓</span>
                  <div>
                    <strong>CSV 与 Manifest 校验通过</strong>
                    <small>{dataImport.batch_id}</small>
                  </div>
                </div>
                <span className="sample-badge">{dataImport.sample_count} 条观测</span>
              </div>

              <dl className="validation-grid" aria-label="导入校验摘要">
                <div><dt>CSV 字段</dt><dd>通过</dd></div>
                <div><dt>Manifest</dt><dd>通过</dd></div>
                <div><dt>版本绑定</dt><dd>通过</dd></div>
                <div><dt>原始文件哈希</dt><dd>通过</dd></div>
                <div><dt>规范化哈希</dt><dd>通过</dd></div>
              </dl>

              <div className="metrics-layout">
                <div className="mtf-block">
                  <p className="metric-label">归一化 MTF · 批次均值</p>
                  <div className="mtf-grid">
                    <div className="center-mtf"><span>中心</span><strong>{dataImport.mtf_summary.mtf_center}</strong></div>
                    <div><span>LT</span><strong>{dataImport.mtf_summary.mtf_lt}</strong></div>
                    <div><span>RT</span><strong>{dataImport.mtf_summary.mtf_rt}</strong></div>
                    <div><span>LB</span><strong>{dataImport.mtf_summary.mtf_lb}</strong></div>
                    <div><span>RB</span><strong>{dataImport.mtf_summary.mtf_rb}</strong></div>
                  </div>
                </div>
                <dl className="derived-grid">
                  <div><dt>最差角</dt><dd>{dataImport.mtf_summary.corner_mtf_min}</dd></div>
                  <div><dt>四角极差</dt><dd>{dataImport.mtf_summary.corner_mtf_range}</dd></div>
                  <div><dt>四角标准差</dt><dd>{dataImport.mtf_summary.corner_mtf_std}</dd></div>
                </dl>
              </div>

              <div className="status-hash-grid">
                <div>
                  <p className="metric-label">参数状态 · 归一化原型单位</p>
                  <dl className="compact-metrics">
                    {Object.entries(dataImport.parameter_summary).map(([key, value]) => (
                      <div key={key}><dt>{parameterLabels[key]}</dt><dd>{value}</dd></div>
                    ))}
                  </dl>
                </div>
                <div>
                  <p className="metric-label">平台状态 · 批次均值</p>
                  <dl className="compact-metrics">
                    {Object.entries(dataImport.platform_summary).map(([key, value]) => (
                      <div key={key}><dt>{platformLabels[key]}</dt><dd>{value}</dd></div>
                    ))}
                  </dl>
                </div>
                <div className="hash-summary">
                  <p className="metric-label">数据与哈希</p>
                  <dl>
                    <div><dt>dataset</dt><dd>{task.versions.dataset_version}</dd></div>
                    <div><dt>canonicalizer</dt><dd>{task.versions.canonicalizer_version}</dd></div>
                    <div>
                      <dt>canonical SHA-256</dt>
                      <dd title={dataImport.hashes.canonical_observation_hash}>
                        {dataImport.hashes.canonical_observation_hash.slice(0, 12)}
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>
            </div>
          )}
        </section>

        {dataImport && (
          <section className="detection-panel" aria-labelledby="detection-title">
            <div className="detection-intro">
              <div>
                <p className="section-kicker">版本化 SPC 门控</p>
                <h2 id="detection-title">四角 MTF 异常检测</h2>
                <p className="import-copy">
                  仅由服务端读取当前 Measurement、派生指标、只读控制限与冻结规则快照。
                </p>
              </div>
              <button
                className="primary-action detection-action"
                type="button"
                disabled={
                  detectionState.kind === "loading" ||
                  Boolean(task.anomaly_detection)
                }
                onClick={handleDetection}
              >
                {task.anomaly_detection ? "检测已完成" : "运行异常检测"}
              </button>
            </div>

            {detectionState.kind === "loading" && (
              <div className="import-progress" role="status" aria-live="polite">
                <span className="inline-loader" />
                <span>正在执行版本化 SPC 规则…</span>
              </div>
            )}

            {detectionState.kind === "error" && (
              <div className="inline-error" role="alert">
                <div>
                  <strong>检测已拒绝</strong>
                  <p>{detectionState.message}</p>
                </div>
                <code>{detectionState.code}</code>
              </div>
            )}

            {task.anomaly_detection && (
              <DetectionResultView detection={task.anomaly_detection} />
            )}
          </section>
        )}

        {task.anomaly_detection?.anomaly_result === "TARGET_ANOMALY" && (
          <section className="diagnosis-panel" aria-labelledby="diagnosis-title">
            <div className="detection-intro">
              <div>
                <p className="section-kicker">固定预处理器与逻辑回归</p>
                <h2 id="diagnosis-title">根因诊断与证据充足度</h2>
                <p className="import-copy">
                  服务端按固定特征顺序执行离线推理、Z 类硬门控、稳定 Top-3 与结构化解释。
                </p>
              </div>
              <button
                className="primary-action detection-action"
                type="button"
                disabled={diagnosisState.kind === "loading" || Boolean(task.diagnostic_result)}
                onClick={handleDiagnosis}
              >
                {task.diagnostic_result ? "诊断已完成" : "运行根因诊断"}
              </button>
            </div>
            {diagnosisState.kind === "loading" && (
              <div className="import-progress" role="status" aria-live="polite">
                <span className="inline-loader" />
                <span>正在校验固定诊断资产并计算 Top-3…</span>
              </div>
            )}
            {diagnosisState.kind === "error" && (
              <div className="inline-error" role="alert">
                <div><strong>诊断已拒绝</strong><p>{diagnosisState.message}</p></div>
                <code>{diagnosisState.code}</code>
              </div>
            )}
            {task.diagnostic_result && (
              <>
                <DiagnosisResultView diagnostic={task.diagnostic_result} />
                <section className="case-retrieval-section" aria-labelledby="case-retrieval-title">
                  <div className="case-retrieval-intro">
                    <div>
                      <p className="section-kicker">独立标准化器 · 结构化 KNN</p>
                      <h2 id="case-retrieval-title">相似案例</h2>
                      <p className="import-copy">
                        先检索当前 Top-3 根因池，不足时再由其余兼容案例补足；根因与历史动作不参与距离计算。
                      </p>
                    </div>
                    <span className="approved-only-note">仅检索 APPROVED 案例</span>
                    <button
                      className="primary-action detection-action"
                      type="button"
                      disabled={
                        caseRetrievalState.kind === "loading" ||
                        caseRetrievalState.kind === "success" ||
                        Boolean(task.parameter_planning_result)
                      }
                      onClick={handleCaseRetrieval}
                    >
                      {caseRetrievalState.kind === "success" || task.parameter_planning_result
                        ? "案例检索已完成"
                        : caseRetrievalState.kind === "error"
                          ? "重新检索已审核案例"
                          : "检索已审核案例"}
                    </button>
                  </div>
                  {caseRetrievalState.kind === "loading" && (
                    <div className="import-progress" role="status" aria-live="polite">
                      <span className="inline-loader" />
                      <span>正在校验 APPROVED 案例索引并计算结构化距离…</span>
                    </div>
                  )}
                  {caseRetrievalState.kind === "error" && (
                    <div className="inline-error" role="alert">
                      <div>
                        <strong>案例检索已拒绝</strong>
                        <p>{caseRetrievalState.message}</p>
                      </div>
                      <code>{caseRetrievalState.code}</code>
                    </div>
                  )}
                  {caseRetrievalState.kind === "success" && (
                    <CaseRetrievalResultView result={caseRetrievalState.result} />
                  )}
                </section>
                <section className="parameter-planning-section" aria-labelledby="parameter-planning-title">
                  <div className="parameter-planning-intro">
                    <div>
                      <p className="section-kicker">确定性方向规则 · 统一安全校验</p>
                      <h2 id="parameter-planning-title">安全参数候选</h2>
                      <p className="import-copy">
                        服务端独立形成方向证据，按 tick 生成候选，并由同一安全规则逐项校验。
                      </p>
                    </div>
                    <span className="readonly-label">只读候选</span>
                    <button
                      className="primary-action detection-action"
                      type="button"
                      disabled={
                        parameterPlanningState.kind === "loading" ||
                        parameterPlanningState.kind === "success" ||
                        Boolean(task.parameter_planning_result)
                      }
                      onClick={handleParameterPlanning}
                    >
                      {parameterPlanningState.kind === "success" || task.parameter_planning_result
                        ? "候选生成已完成"
                        : parameterPlanningState.kind === "error"
                          ? "重新生成安全参数候选"
                          : "生成安全参数候选"}
                    </button>
                  </div>
                  {parameterPlanningState.kind === "loading" && (
                    <div className="import-progress" role="status" aria-live="polite">
                      <span className="inline-loader" />
                      <span>正在生成方向证据并执行统一安全校验…</span>
                    </div>
                  )}
                  {parameterPlanningState.kind === "error" && (
                    <div className="inline-error" role="alert">
                      <div>
                        <strong>参数候选生成已拒绝</strong>
                        <p>{parameterPlanningState.message}</p>
                      </div>
                      <code>{parameterPlanningState.code}</code>
                    </div>
                  )}
                  {(parameterPlanningState.kind === "success" || task.parameter_planning_result) && (
                    <ParameterPlanningResultView
                      result={
                        parameterPlanningState.kind === "success"
                          ? parameterPlanningState.result
                          : task.parameter_planning_result as ParameterPlanningResult
                      }
                      actor={task.actor}
                      selectedCandidateId={selectedCandidateId}
                      onSelectCandidate={(candidateId) => {
                        setSelectedCandidateId(candidateId);
                        setConfirmationState({ kind: "idle" });
                      }}
                      onConfirm={handlePlanConfirmation}
                      confirmationState={confirmationState}
                      confirmedPlan={task.confirmed_plan}
                      invalidCandidateIds={invalidCandidateIds}
                      confirmationContextInvalid={confirmationContextInvalid}
                    />
                  )}
                </section>
              </>
            )}
          </section>
        )}

        <section className="stage-panel" aria-labelledby="workflow-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">任务阶段</p>
              <h2 id="workflow-title">任务闭环</h2>
            </div>
            <p className="section-note">
              <span>{String(currentStageIndex + 1).padStart(2, "0")} / 10</span>
              当前阶段：{task.stages[currentStageIndex]?.label}
            </p>
          </div>
          <nav aria-label="任务阶段">
            <ol className="stage-list">
              {task.stages.map((stage, index) => (
                <li
                  key={stage.code}
                  className={`stage stage-${stage.availability}`}
                  aria-label={`阶段 ${stage.label}`}
                  aria-current={stage.availability === "current" ? "step" : undefined}
                  aria-disabled={stage.availability === "locked"}
                >
                  <span className="stage-index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="stage-copy">
                    <strong>{stage.label}</strong>
                    <small>{stage.code}</small>
                  </span>
                  <span className="stage-state">
                    {stage.availability === "current"
                      ? "当前阶段"
                      : stage.availability === "completed"
                        ? "已完成"
                        : "未开放"}
                  </span>
                </li>
              ))}
            </ol>
          </nav>
        </section>

        <div className="details-grid">
          <section className="identity-panel" aria-labelledby="identity-title">
            <div className="section-heading compact">
              <div>
                <p className="section-kicker">演示身份</p>
                <h2 id="identity-title">固定演示身份</h2>
              </div>
              <span className="readonly-label">只读</span>
            </div>
            <dl className="identity-list">
              <div>
                <dt>显示名称</dt>
                <dd>{task.actor.display_name}</dd>
              </div>
              <div>
                <dt>actor_id</dt>
                <dd>{task.actor.actor_id}</dd>
              </div>
              <div>
                <dt>actor_role</dt>
                <dd>{task.actor.actor_role}</dd>
              </div>
            </dl>
          </section>

          <section className="versions-panel" aria-labelledby="versions-title">
            <div className="section-heading compact">
              <div>
                <p className="section-kicker">公共资产</p>
                <h2 id="versions-title">公共版本摘要</h2>
              </div>
              <span className="verified-label">
                <span className="status-dot" />
                完整性已验证
              </span>
            </div>
            <dl className="version-grid">
              {(Object.entries(task.versions) as [keyof Task["versions"], string][]).map(
                ([key, value]) => (
                  <div key={key}>
                    <dt>{versionLabels[key]}</dt>
                    <dd>{value}</dd>
                  </div>
                ),
              )}
            </dl>
          </section>
        </div>
      </main>
      <footer className="app-footer">
        <span>仅用于规则约束模拟环境中的离线比赛原型</span>
        <span>无真实设备连接 · 无在线服务依赖</span>
      </footer>
    </div>
  );
}

export default App;
