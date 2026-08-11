import { useEffect, useState } from "react";

import {
  AnomalyDetectionResult,
  CaseRetrievalResult,
  confirmParameterPlan,
  ConfirmedPlan,
  createInitialTask,
  DeviceExecutionEligibility,
  DeviceExecutionReceipt,
  executeControlledDeviceWrite,
  generateParameterPlans,
  getDeviceExecutionEligibility,
  importPresetAsset,
  ParameterPlanningResult,
  ReplayResult,
  retrieveApprovedCases,
  runAnomalyDetection,
  runPairedReplay,
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

const workflowStageLabels: Record<string, string> = {
  CREATED: "任务创建",
  DATA_IMPORTED: "输入测量数据",
  ANOMALY_DETECTED: "异常检测结果",
  DIAGNOSED: "根因优先级",
  PLAN_READY: "调参候选方案",
  PLAN_CONFIRMED: "工程师确认",
  REPLAYING: "调参方案仿真",
  REPLAYED: "仿真验证结果",
  CLOSED: "复盘关闭",
  CASE_SUBMITTED: "案例提交",
};

function workflowStageLabel(code: string, fallback: string) {
  return workflowStageLabels[code] ?? fallback;
}

const taskStatusLabels: Record<string, string> = {
  CREATED: "等待输入测量数据",
  DATA_IMPORTED: "测量数据已导入",
  ANOMALY_DETECTED: "已发现异常",
  DIAGNOSED: "根因优先级已生成",
  PLAN_READY: "调参候选待确认",
  PLAN_CONFIRMED: "工程师已确认",
  REPLAYING: "仿真验证进行中",
  REPLAYED: "仿真验证已完成",
  CLOSED: "任务已复盘关闭",
  CASE_SUBMITTED: "案例已提交",
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

type ReplayState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; code: string; message: string };

type DeviceExecutionState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "eligibility"; eligibility: DeviceExecutionEligibility }
  | { kind: "executing"; eligibility: DeviceExecutionEligibility }
  | {
      kind: "result";
      eligibility: DeviceExecutionEligibility;
      receipt: DeviceExecutionReceipt;
      idempotentReplay: boolean;
    }
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
  pitch: "pitch（俯仰角）",
  roll: "roll（横滚角）",
  z_offset: "Z 偏移",
};

const candidateTypeLabels: Record<string, string> = {
  CONSERVATIVE: "保守调整方案",
  STANDARD: "标准调整方案",
  CASE_GUIDED: "案例参考方案",
};

function candidateTypeLabel(value: string): string {
  return candidateTypeLabels[value] ?? value;
}

function validationStatusLabel(value: string): string {
  return value === "PASSED" ? "安全校验通过" : value;
}

function replayStatusLabel(value: ReplayResult["replay_status"]): string {
  const labels: Record<ReplayResult["replay_status"], string> = {
    SUCCESS: "仿真验证通过",
    PARTIAL_IMPROVEMENT: "仿真显示部分改善",
    NO_IMPROVEMENT: "仿真未显示改善",
    REGRESSION: "仿真显示指标退化",
  };
  return labels[value];
}

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
          <span className="result-code">异常检测结果</span>
          <h3>{copy.title}</h3>
          <p>{copy.summary}</p>
        </div>
        <details className="detection-binding technical-details" aria-label="检测版本与输入哈希">
          <summary>技术证据</summary>
          <code>内部状态 {detection.anomaly_result}</code>
          <code>规则集 {detection.rule_set_version}</code>
          <code>输入 {detection.input_hash.slice(0, 12)}</code>
        </details>
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
          <span className="result-code">{sufficient ? "证据充足" : "证据不足"}</span>
          <h3>{sufficient ? "诊断证据满足冻结规则" : "诊断证据不足，仅供排查"}</h3>
          <p>
            {sufficient
              ? "Top-1 得分、类别间距、兼容规则与完整性检查均通过。"
              : "仍展示 Top-3 排查顺序；参数候选数量固定为 0，后续流程保持关闭。"}
          </p>
        </div>
        <code title={diagnostic.result_hash}>{diagnostic.evidence_status}</code>
      </div>

      <div className="diagnosis-heading">
        <div>
          <p className="section-kicker">异常诊断结果</p>
          <h2>根因优先级</h2>
        </div>
        <p><strong>相对排序分数，不代表故障概率。</strong></p>
      </div>

      <ol className="root-cause-list">
        {diagnostic.ordered_top3.map((candidate) => (
          <li key={candidate.root_cause} className="root-cause-card">
            <header>
              <span className="root-cause-rank">#{candidate.rank}</span>
              <div>
                <strong>{rootCauseLabels[candidate.root_cause] ?? candidate.root_cause}</strong>
                <small>{candidate.root_cause}</small>
              </div>
              <span className={`adjustability ${candidate.adjustability === "ADJUSTABLE" ? "adjustable" : "inspection-only"}`}>
                {candidate.adjustability === "ADJUSTABLE" ? "可调" : "仅排查"}
              </span>
              <div className="relative-score">
                <span>相对排序分数</span>
                <strong>{candidate.normalized_score}</strong>
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

      <p className="score-boundary" role="note">
        例如 0.997781 是当前候选类别的相对排序分数，不代表 99.7781% 故障概率。
      </p>

      <details className="technical-details">
        <summary>查看诊断技术证据</summary>
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
        <p className="technical-hash" title={diagnostic.result_hash}>
          诊断结果哈希：{diagnostic.result_hash}
        </p>
      </details>
    </div>
  );
}

function CaseRetrievalResultView({ result }: { result: CaseRetrievalResult }) {
  const empty = result.retrieval_status === "NO_RELEVANT_CASE_AVAILABLE";
  return (
    <div className="case-retrieval-result">
      <div className={`case-retrieval-status ${empty ? "case-retrieval-empty" : ""}`} role="status">
        <div>
          <span className="result-code">{empty ? "无当前适用案例" : "历史参考案例"}</span>
          <strong>
            {empty
              ? "暂无符合当前条件的已审核案例"
              : `找到 ${result.returned_count} 个当前可参考的已审核案例`}
          </strong>
          {result.shortfall_message && <p>{result.shortfall_message}</p>}
        </div>
        <code>{result.retrieval_status}</code>
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
                <span className="approved-badge">已审核</span>
                <div className="case-distance">
                  <strong>特征差异距离 {approvedCase.distance}</strong>
                  <small>距离越小，可观测特征越接近</small>
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
              <details className="technical-details compact-technical-details">
                <summary>查看案例技术证据</summary>
                <dl className="case-source-versions">
                  <div><dt>案例内容哈希</dt><dd title={approvedCase.case_content_hash}>{approvedCase.case_content_hash}</dd></div>
                  <div><dt>中性显示值</dt><dd>{approvedCase.similarity_display_value}</dd></div>
                </dl>
              </details>
            </li>
          ))}
        </ol>
      )}

      <p className="case-retrieval-disclaimer" role="note">
        特征差异距离只衡量固定可观测数据的接近程度，不代表根因概率、因果关系或真实设备适用率。
        历史结果仅来自规则约束模拟环境，不代表真实产线良率改善。
      </p>
      <details className="technical-details retrieval-technical-details">
        <summary>查看检索版本与规则</summary>
        <dl className="case-source-versions" aria-label="案例检索版本">
          <div><dt>案例索引</dt><dd>{result.case_index_version}</dd></div>
          <div><dt>检索标准化器</dt><dd>{result.scaler_version}</dd></div>
          <div><dt>适用性规则</dt><dd>{result.compatibility_rule_version}</dd></div>
        </dl>
      </details>
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
  replayCompleted,
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
  replayCompleted: boolean;
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
          <span>调参方案状态</span>
          <strong>{result.planning_status === "CANDIDATES_AVAILABLE" ? "候选方案已生成" : "未生成调参候选"}</strong>
          <code>{result.planning_status}</code>
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
          <h3 id="planning-candidates-title">调参候选方案</h3>
          <p className="planning-readonly-note">
            <strong>AI 给出候选，工程师决定是否采用。</strong>
            候选参数为服务端只读内容，不会在未确认时写入任何设备。
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
                      <strong>{candidateTypeLabel(candidate.generation_type)}</strong>
                      <small><code>{candidate.generation_type}</code><span>{candidate.candidate_id}</span></small>
                    </div>
                    <span>总调整量 {candidate.total_absolute_delta_ticks} ticks</span>
                    <span>参考案例 {candidate.supporting_case_count}</span>
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
                          : `选择${candidateTypeLabel(candidate.generation_type)}`}
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
                    <summary>安全校验详情 · {validationStatusLabel(candidate.validation_status)}</summary>
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
                  <details className="technical-details compact-technical-details">
                    <summary>查看候选方案技术证据</summary>
                    <p className="candidate-hash" title={candidate.candidate_hash}>
                      候选哈希 {candidate.candidate_hash}
                    </p>
                  </details>
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
                <p className="section-kicker">人在回路 · 工程师做决定</p>
                <h3 id="confirmation-title">工程师确认</h3>
                <p>
                  AI 只提供候选；由 {actor.display_name} 确认是否采用。
                </p>
                {selectedCandidateId ? (
                  <p className="confirmation-selection-summary">
                    已选择 {selectedCandidateId}
                  </p>
                ) : (
                  <p className="confirmation-selection-summary">请先选择一组已通过安全校验的候选方案。</p>
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
                工程师确认采用
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
                    <strong>工程师确认未通过</strong>
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
              <p className="section-kicker">STALE · 不可用于仿真验证</p>
              <h3 id="confirmed-plan-title">方案已过期，需要重新生成并确认</h3>
              <ul className="stale-reasons">
                {confirmedPlan.stale_reason_codes.map((reason) => (
                  <li key={reason}><code>{reason}</code></li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <p className="section-kicker">已冻结 · 工程师已确认</p>
              <h3 id="confirmed-plan-title">已确认调参方案</h3>
              <div className="confirmed-plan-grid">
                <dl>
                  <div><dt>候选</dt><dd>{confirmedPlan.candidate_id}</dd></div>
                  <div><dt>参数族</dt><dd>{confirmedPlan.parameter_family}</dd></div>
                  <div><dt>方案类型</dt><dd>{candidateTypeLabel(confirmedPlan.generation_type)}</dd></div>
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
                    <dt>技术证据哈希</dt>
                    <dd title={confirmedPlan.confirmed_plan_hash}>
                      {confirmedPlan.confirmed_plan_hash.slice(0, 16)}
                    </dd>
                  </div>
                </dl>
              </div>
              <p className="confirmation-disclaimer">
                {replayCompleted
                  ? "该已确认方案已用于下方执行前仿真验证；没有向真实设备下发参数。"
                  : "此操作只冻结离线候选方案；尚未进行执行前仿真验证；没有向真实设备下发参数。"}
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

      <details className="technical-details">
        <summary>查看调参规则版本与结果哈希</summary>
        <dl className="planning-version-grid">
        <div><dt>方向规则</dt><dd>{result.direction_rule_version}</dd></div>
        <div><dt>安全规则</dt><dd>{result.safety_rule_version}</dd></div>
        <div><dt>约束快照</dt><dd>{result.constraint_snapshot_version}</dd></div>
        <div><dt>规划规则</dt><dd>{result.planning_rule_version}</dd></div>
        <div><dt>结果哈希</dt><dd title={result.result_hash}>{result.result_hash.slice(0, 16)}</dd></div>
        </dl>
      </details>
    </div>
  );
}

const replayMetricRows: { key: keyof ReplayResult["baseline_metrics"]; label: string }[] = [
  { key: "mtf_center_mean", label: "中心 MTF 均值" },
  { key: "corner_mtf_min", label: "最差角落 MTF" },
  { key: "corner_mtf_range", label: "四角极差" },
  { key: "corner_mtf_std", label: "四角标准差" },
  { key: "center_corner_gap", label: "中心与四角差距" },
];

function ReplayResultView({ result }: { result: ReplayResult }) {
  return (
    <section className="replay-result" aria-labelledby="replay-result-title">
      <div className="replay-result-heading">
        <div>
          <p className="section-kicker">调参方案仿真</p>
          <h2 id="replay-result-title">仿真验证结果</h2>
        </div>
        <strong className={`replay-status replay-status-${result.replay_status.toLowerCase()}`}>
          {replayStatusLabel(result.replay_status)}
          <small>{result.replay_status}</small>
        </strong>
      </div>

      <div className="baseline-reproduction" role="status">
        <strong>基线复现通过</strong>
        <span>导入基线与仿真基线一致；对应技术哈希已校验。</span>
      </div>

      <div className="replay-metric-table-wrap">
        <table className="replay-metric-table">
          <caption>固定模型、场景和扰动下的指标对照</caption>
          <thead>
            <tr><th scope="col">指标</th><th scope="col">调整前</th><th scope="col">调整后</th><th scope="col">变化量</th></tr>
          </thead>
          <tbody>
            {replayMetricRows.map(({ key, label }) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                <td>{String(result.baseline_metrics[key])}</td>
                <td>{String(result.intervention_metrics[key])}</td>
                <td>{result.metric_deltas[key] ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="evaluation-checks" aria-labelledby="evaluation-checks-title">
        <h3 id="evaluation-checks-title">预设评价规则检查</h3>
        <ul>
          {result.evaluation_checks.map((check) => (
            <li key={check.check_id}>
              <div><code>{check.check_id}</code><span>{check.metric}</span></div>
              <strong className={`check-${check.status.toLowerCase()}`}>{check.status}</strong>
              <dl>
                <div><dt>前值</dt><dd>{String(check.before_value)}</dd></div>
                <div><dt>后值</dt><dd>{String(check.after_value)}</dd></div>
                <div><dt>变化量</dt><dd>{check.delta}</dd></div>
                <div><dt>阈值 / 容差</dt><dd>{check.threshold ?? check.tolerance ?? "—"}</dd></div>
              </dl>
            </li>
          ))}
        </ul>
      </div>

      <div className="replay-disclaimer">
        <strong>仅表示该参数方案在当前固定模拟条件下满足预设评价规则，不代表真实产线效果。</strong>
        <p>{result.disclaimer} {result.no_device_write_notice}</p>
      </div>
      <details className="technical-details replay-technical-details">
        <summary>查看仿真版本与结果哈希</summary>
        <div className="replay-result-meta">
          <span>尝试次数 {result.attempt_count}</span>
          <span>仿真器 {result.simulator_version}</span>
          <span>评价规则 {result.replay_evaluation_rule_version}</span>
          <span title={result.result_hash}>仿真结果哈希（ReplayResult SHA-256） {result.result_hash}</span>
        </div>
      </details>
    </section>
  );
}

const deviceExecutionFallbackDisclaimer =
  "当前 OPC-UA 通道连接的是本地模拟设备，不代表已经完成真实设备接入或真实设备安全验证。";

function deviceValue(value: string | null): string {
  return value ?? "—";
}

function tickDelta(value: number | null): string {
  if (value === null) return "—";
  return `${value > 0 ? "+" : ""}${value} tick`;
}

function DeviceExecutionPanel({
  executionState,
  acknowledged,
  onCheckEligibility,
  onAcknowledgedChange,
  onExecute,
}: {
  executionState: DeviceExecutionState;
  acknowledged: boolean;
  onCheckEligibility: () => void;
  onAcknowledgedChange: (checked: boolean) => void;
  onExecute: () => void;
}) {
  const eligibility =
    executionState.kind === "eligibility" ||
    executionState.kind === "executing" ||
    executionState.kind === "result"
      ? executionState.eligibility
      : null;
  const receipt = executionState.kind === "result" ? executionState.receipt : null;
  const idempotentReplay =
    executionState.kind === "result" ? executionState.idempotentReplay : false;
  const busy = executionState.kind === "checking" || executionState.kind === "executing";
  const canExecute =
    executionState.kind === "eligibility" &&
    executionState.eligibility.eligible &&
    acknowledged;
  const succeeded = receipt?.execution_status === "SUCCEEDED";
  const disclaimer =
    receipt?.disclaimer ?? eligibility?.disclaimer ?? deviceExecutionFallbackDisclaimer;
  const connectionStatus = (() => {
    if (executionState.kind === "idle") {
      return "模拟设备连接状态待确认";
    }
    if (executionState.kind === "checking") {
      return "正在检查模拟设备连接与执行资格";
    }
    if (executionState.kind === "error") {
      return executionState.message;
    }
    if (eligibility?.code === "DEVICE_EXECUTION_DISABLED") {
      return "设备执行功能未启用";
    }
    if (eligibility?.device_connected) {
      return "已连接本地 OPC-UA 模拟设备";
    }
    return eligibility?.message ?? "模拟设备不可用";
  })();

  return (
    <section className="device-execution-panel" aria-labelledby="device-execution-title">
      <div className="device-execution-heading">
        <div>
          <p className="section-kicker">OPC-UA Sandbox · 本地模拟环境</p>
          <h2 id="device-execution-title">本地模拟设备执行</h2>
          <p>
            仅在工程师确认和仿真验证通过后，由服务端对本地白名单节点执行写前校验、写入与读回。
          </p>
        </div>
        <span className="sandbox-badge">LOCAL OPC-UA SANDBOX / 本地模拟环境</span>
      </div>

      <dl className="device-status-grid">
        <div>
          <dt>执行模式</dt>
          <dd>{eligibility?.execution_mode ?? "待服务端确认"}</dd>
        </div>
        <div>
          <dt>设备连接</dt>
          <dd className={eligibility?.device_connected ? "device-value-passed" : undefined}>
            {connectionStatus}
          </dd>
        </div>
        <div>
          <dt>安全门禁</dt>
          <dd className={eligibility?.safety_gate_status === "PASSED" ? "device-value-passed" : undefined}>
            {eligibility?.safety_gate_status ?? "待检查"}
          </dd>
        </div>
        <div>
          <dt>仿真验证</dt>
          <dd className="device-value-passed">已通过 <small>{eligibility?.replay_status ?? "SUCCESS"}</small></dd>
        </div>
      </dl>

      {executionState.kind !== "result" && (
        <div className="device-check-action">
          <div>
            <strong>工程师确认后的受控执行</strong>
            <p>设备端点、节点映射和参数值均由服务端固定，页面不能指定。</p>
          </div>
          <button
            className="secondary-action"
            type="button"
            disabled={busy}
            onClick={onCheckEligibility}
          >
            {executionState.kind === "checking"
              ? "正在检查资格…"
              : eligibility
                ? "重新检查执行条件"
                : "检查执行条件"}
          </button>
        </div>
      )}

      {executionState.kind === "checking" && (
        <div className="device-progress" role="status" aria-live="polite">
          <span className="inline-loader" />
          <span>正在检查模拟设备连接与执行资格</span>
        </div>
      )}

      {executionState.kind === "error" && (
        <div className="inline-error device-inline-message" role="alert">
          <div>
            <strong>设备执行请求失败</strong>
            <p>{executionState.message}</p>
          </div>
          <code>{executionState.code}</code>
        </div>
      )}

      {eligibility && (
        <>
          <div
            className={`device-gate-result ${eligibility.eligible ? "device-gate-passed" : "device-gate-rejected"}`}
            role={eligibility.eligible ? "status" : "alert"}
            aria-live="polite"
          >
            <div>
              <strong>{eligibility.eligible ? "本地模拟执行条件已通过" : "本地模拟执行条件未通过"}</strong>
              <p>{eligibility.message}</p>
            </div>
            <code>{eligibility.code}</code>
          </div>

          <dl className="device-parameter-grid">
            <div><dt>参数</dt><dd>{deviceValue(eligibility.parameter_name)}</dd></div>
            <div><dt>计划写入前值</dt><dd>{deviceValue(eligibility.expected_before_value)}</dd></div>
            <div><dt>设备当前值</dt><dd>{deviceValue(eligibility.actual_before_value)}</dd></div>
            <div><dt>目标值</dt><dd>{deviceValue(eligibility.requested_after_value)}</dd></div>
            <div><dt>tick 变化</dt><dd>{tickDelta(eligibility.tick_delta)}</dd></div>
            <div><dt>本地设备端点</dt><dd>{eligibility.endpoint_local_id}</dd></div>
            <div><dt>节点映射版本</dt><dd>{eligibility.node_mapping_version}</dd></div>
            <div><dt>OPC-UA 服务端节点</dt><dd>{deviceValue(eligibility.node_id)}</dd></div>
          </dl>

          {executionState.kind !== "result" && (
            <div className="device-execution-confirmation">
              {eligibility.eligible && (
                <label htmlFor="sandbox-execution-acknowledgement">
                  <input
                    id="sandbox-execution-acknowledgement"
                    type="checkbox"
                    checked={acknowledged}
                    disabled={executionState.kind === "executing"}
                    onChange={(event) => onAcknowledgedChange(event.target.checked)}
                  />
                  <span>
                    我确认当前目标是本地 OPC-UA 模拟设备，并授权执行这一次写入与回读验证。
                  </span>
                </label>
              )}
              <button
                className="primary-action device-execution-action"
                type="button"
                disabled={!canExecute || busy}
                onClick={onExecute}
              >
                {executionState.kind === "executing"
                  ? "正在写入并回读验证…"
                  : "在本地模拟设备上执行"}
              </button>
            </div>
          )}
        </>
      )}

      {executionState.kind === "executing" && (
        <div className="device-progress" role="status" aria-live="polite">
          <span className="inline-loader" />
          <span>正在写入本地模拟设备并读回结果… <small>WRITE_STARTED</small></span>
        </div>
      )}

      {receipt && (
        <div className="device-receipt">
          <div
            className={`device-execution-result ${succeeded ? "device-execution-succeeded" : "device-execution-failed"}`}
            role={succeeded ? "status" : "alert"}
            aria-live="polite"
          >
            <div>
              <strong>
                {succeeded
                  ? "本地模拟设备执行成功"
                  : receipt.execution_status === "REJECTED"
                    ? "受控下发已拒绝"
                    : receipt.execution_status === "UNKNOWN_OUTCOME" ||
                        receipt.execution_status === "RECONCILIATION_REQUIRED"
                      ? "执行结果未知，需要只读核对"
                      : "写入并回读验证明确失败"}
              </strong>
              <p>{receipt.message}</p>
            </div>
            <code>{receipt.failure_code ?? receipt.execution_status}</code>
          </div>
          <dl className="device-receipt-grid">
            <div><dt>执行状态</dt><dd>{succeeded ? "执行成功" : receipt.execution_status} <small>{receipt.execution_status}</small></dd></div>
            <div><dt>写前实际值</dt><dd>{deviceValue(receipt.actual_before_value)}</dd></div>
            <div><dt>请求目标值</dt><dd>{deviceValue(receipt.requested_after_value)}</dd></div>
            <div><dt>执行后读回值</dt><dd>{deviceValue(receipt.actual_after_value)}</dd></div>
            <div><dt>写入次数</dt><dd>{receipt.write_attempt_count}</dd></div>
            <div><dt>幂等结果</dt><dd>{idempotentReplay ? "复用首次凭证" : "首次执行"}</dd></div>
            <div className="device-receipt-hash">
              <dt>执行记录哈希（receipt hash）</dt>
              <dd title={receipt.receipt_hash}>{receipt.receipt_hash}</dd>
            </div>
          </dl>
        </div>
      )}

      <div className="device-disclaimer">
        <strong>
          当前功能仅面向本地 OPC-UA 模拟设备，连接状态以上方服务端检查为准；
          非真实生产设备、非真实安全验证，执行结果不代表真实产线良率改善。
        </strong>
        <p>{disclaimer}</p>
      </div>
    </section>
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
  const [replayState, setReplayState] = useState<ReplayState>({ kind: "idle" });
  const [deviceExecutionState, setDeviceExecutionState] =
    useState<DeviceExecutionState>({ kind: "idle" });
  const [deviceExecutionAcknowledged, setDeviceExecutionAcknowledged] =
    useState(false);

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
      setReplayState({ kind: "idle" });
      setDeviceExecutionState({ kind: "idle" });
      setDeviceExecutionAcknowledged(false);
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
      setReplayState({ kind: "idle" });
      setDeviceExecutionState({ kind: "idle" });
      setDeviceExecutionAcknowledged(false);
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
      setReplayState({ kind: "idle" });
      setDeviceExecutionState({ kind: "idle" });
      setDeviceExecutionAcknowledged(false);
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
      setReplayState({ kind: "idle" });
      setDeviceExecutionState({ kind: "idle" });
      setDeviceExecutionAcknowledged(false);
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
      setReplayState({ kind: "idle" });
      setDeviceExecutionState({ kind: "idle" });
      setDeviceExecutionAcknowledged(false);
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

  async function handleReplay() {
    const plan = task.confirmed_plan;
    if (
      !plan ||
      plan.status !== "VALID" ||
      task.status !== "PLAN_CONFIRMED" ||
      task.replay_result
    ) return;
    setReplayState({ kind: "loading" });
    try {
      const response = await runPairedReplay(
        task.task_id,
        plan.confirmed_plan_id,
        plan.confirmed_plan_hash,
      );
      setState({ kind: "ready", task: response.task });
      setReplayState({ kind: "idle" });
      setDeviceExecutionState({ kind: "idle" });
      setDeviceExecutionAcknowledged(false);
    } catch (error: unknown) {
      if (error instanceof TaskCreationError) {
        setReplayState({ kind: "error", code: error.code, message: error.message });
        return;
      }
      setReplayState({
        kind: "error",
        code: "PAIRED_REPLAY_FAILED",
        message: "本地执行前仿真验证暂时不可用。",
      });
    }
  }

  async function handleDeviceEligibility() {
    const plan = task.confirmed_plan;
    if (!plan || task.replay_result?.replay_status !== "SUCCESS") return;
    setDeviceExecutionAcknowledged(false);
    setDeviceExecutionState({ kind: "checking" });
    try {
      const eligibility = await getDeviceExecutionEligibility(
        task.task_id,
        plan.confirmed_plan_id,
        plan.confirmed_plan_hash,
      );
      setDeviceExecutionState({ kind: "eligibility", eligibility });
    } catch (error: unknown) {
      if (error instanceof TaskCreationError) {
        setDeviceExecutionState({
          kind: "error",
          code: error.code,
          message: error.message,
        });
        return;
      }
      setDeviceExecutionState({
        kind: "error",
        code: "DEVICE_EXECUTION_ELIGIBILITY_FAILED",
        message: "无法读取本地模拟设备执行资格。",
      });
    }
  }

  async function handleDeviceExecution() {
    const plan = task.confirmed_plan;
    if (
      !plan ||
      task.replay_result?.replay_status !== "SUCCESS" ||
      deviceExecutionState.kind !== "eligibility" ||
      !deviceExecutionState.eligibility.eligible ||
      !deviceExecutionAcknowledged
    ) return;
    const eligibility = deviceExecutionState.eligibility;
    setDeviceExecutionState({ kind: "executing", eligibility });
    try {
      const response = await executeControlledDeviceWrite(
        task.task_id,
        plan.confirmed_plan_id,
        plan.confirmed_plan_hash,
      );
      setDeviceExecutionState({
        kind: "result",
        eligibility,
        receipt: response.device_execution,
        idempotentReplay: response.idempotent_replay,
      });
    } catch (error: unknown) {
      setDeviceExecutionAcknowledged(false);
      if (error instanceof TaskCreationError) {
        setDeviceExecutionState({
          kind: "error",
          code: error.code,
          message: error.message,
        });
        return;
      }
      setDeviceExecutionState({
        kind: "error",
        code: "DEVICE_EXECUTION_FAILED",
        message: "本地 OPC-UA 模拟设备通信或执行服务暂时不可用。",
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
              <small>AA 工站 AI 调机决策支持</small>
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
            <p className="context-label">TuneWise · 本地离线比赛原型</p>
            <div className="title-row">
              <h1>AA 工站 AI 调机决策支持</h1>
              <span className="readonly-label">模拟演示</span>
            </div>
            <p className="hero-copy">
              AI 分析 AA（Active Alignment，主动对准）测量异常并提供调参候选，
              工程师确认后先进行执行前仿真验证。
            </p>
            <ol className="judge-flow" aria-label="TuneWise 决策流程">
              <li><span>1</span><strong>输入</strong><small>AA 测量数据</small></li>
              <li><span>2</span><strong>AI 判断</strong><small>异常与根因优先级</small></li>
              <li><span>3</span><strong>AI 推荐</strong><small>调参候选方案</small></li>
              <li><span>4</span><strong>工程师确认</strong><small>决定是否采用</small></li>
              <li><span>5</span><strong>执行前仿真</strong><small>固定模拟条件</small></li>
            </ol>
            <p className="hero-boundary">当前是本地模拟演示，未连接真实生产设备，不代表真实产线效果。</p>
          </div>
          <dl className="task-summary">
            <div className="task-state">
              <dt>当前任务状态</dt>
              <dd>{taskStatusLabels[task.status] ?? "演示流程进行中"} <small>{task.status}</small></dd>
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
              <p className="section-kicker">第 1 步 · 输入</p>
              <h2 id="import-title">导入 AA 测量数据</h2>
              <p className="import-copy">
                使用预置的合成 AA 异常批次，服务端同时校验数据完整性。
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
              </div>
              <details className="technical-details import-technical-details">
                <summary>查看数据版本与完整性哈希</summary>
                <div className="hash-summary">
                  <dl>
                    <div><dt>dataset</dt><dd>{task.versions.dataset_version}</dd></div>
                    <div><dt>canonicalizer</dt><dd>{task.versions.canonicalizer_version}</dd></div>
                    <div><dt>canonical SHA-256</dt><dd title={dataImport.hashes.canonical_observation_hash}>{dataImport.hashes.canonical_observation_hash}</dd></div>
                  </dl>
                </div>
              </details>
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
                <p className="section-kicker">第 3 步 · AI 判断</p>
                <h2 id="diagnosis-title">异常诊断结果</h2>
                <p className="import-copy">
                  AI 对可能根因进行相对排序，并展示支持与冲突证据。
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
                      <p className="section-kicker">决策依据</p>
                      <h2 id="case-retrieval-title">历史参考案例</h2>
                      <p className="import-copy">
                        检索已审核的离线案例，作为调参候选的参考证据。
                      </p>
                    </div>
                    <span className="approved-only-note">仅检索已审核案例</span>
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
                      <p className="section-kicker">第 4 步 · AI 推荐，工程师确认</p>
                      <h2 id="parameter-planning-title">调参候选方案</h2>
                      <p className="import-copy">
                        AI 根据当前证据生成多组参数方案，安全校验通过后交由工程师选择。
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
                          ? "重新生成调参候选方案"
                          : "生成调参候选方案"}
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
                      replayCompleted={Boolean(task.replay_result)}
                    />
                  )}
                </section>
              </>
            )}
          </section>
        )}

        {task.confirmed_plan && (
          <section className="replay-panel" aria-labelledby="replay-panel-title">
            <div className="replay-panel-heading">
              <div>
                <p className="section-kicker">第 5 步 · Simulation Validation (Replay)</p>
                <h2 id="replay-panel-title">执行前仿真验证（Replay）</h2>
                <p>
                  使用已确认调参方案，在相同固定场景与扰动下比较调整前后结果。
                </p>
              </div>
              {!task.replay_result &&
                task.status === "PLAN_CONFIRMED" &&
                task.confirmed_plan.status === "VALID" && (
                  <button
                    className="primary-action replay-action"
                    type="button"
                    disabled={replayState.kind === "loading"}
                    onClick={handleReplay}
                  >
                    运行调参方案仿真
                  </button>
                )}
            </div>

            {!task.replay_result && (
              <>
                <dl className="replay-confirmation-summary">
                  <div><dt>已确认调参方案</dt><dd>{task.confirmed_plan.confirmed_plan_id}</dd></div>
                  <div title={task.confirmed_plan.confirmed_plan_hash}>
                    <dt>确认哈希</dt><dd>{task.confirmed_plan.confirmed_plan_hash.slice(0, 16)}…</dd>
                  </div>
                  <div><dt>模拟器</dt><dd>tw-simulator-v1（服务端固定）</dd></div>
                  <div><dt>评估规则</dt><dd>{task.versions.evaluation_rule_version}</dd></div>
                </dl>
                {task.confirmed_plan.status === "STALE" && (
                  <div className="inline-error" role="status">
                    <div><strong>方案已过期，不能执行仿真验证</strong><p>请重新生成并由工程师确认候选方案。</p></div>
                    <code>CONFIRMED_PLAN_STALE</code>
                  </div>
                )}
                <div className="replay-disclaimer">
                  <strong>仅表示该参数方案在当前固定模拟条件下满足预设评价规则，不代表真实产线效果。</strong>
                  <p>本次仿真未向真实设备写入任何参数。</p>
                </div>
              </>
            )}
            {replayState.kind === "loading" && (
              <div className="replay-progress" role="status" aria-live="polite">
                <span className="inline-loader" />
                <span>正在执行调参方案仿真… <small>REPLAYING</small></span>
              </div>
            )}
            {replayState.kind === "error" && (
              <div className="inline-error" role="alert">
                <div><strong>仿真验证未执行</strong><p>{replayState.message}</p></div>
                <code>{replayState.code}</code>
              </div>
            )}
            {task.replay_result && <ReplayResultView result={task.replay_result} />}
          </section>
        )}

        {task.replay_result?.replay_status === "SUCCESS" && (
          <DeviceExecutionPanel
            executionState={deviceExecutionState}
            acknowledged={deviceExecutionAcknowledged}
            onCheckEligibility={handleDeviceEligibility}
            onAcknowledgedChange={setDeviceExecutionAcknowledged}
            onExecute={handleDeviceExecution}
          />
        )}

        <section className="stage-panel" aria-labelledby="workflow-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">任务阶段</p>
              <h2 id="workflow-title">任务闭环</h2>
            </div>
            <p className="section-note">
              <span>{String(currentStageIndex + 1).padStart(2, "0")} / 10</span>
              当前阶段：{task.stages[currentStageIndex]
                ? workflowStageLabel(
                    task.stages[currentStageIndex].code,
                    task.stages[currentStageIndex].label,
                  )
                : "未知"}
            </p>
          </div>
          <nav aria-label="任务阶段">
            <ol className="stage-list">
              {task.stages.map((stage, index) => (
                <li
                  key={stage.code}
                  className={`stage stage-${stage.availability}`}
                  aria-label={`阶段 ${workflowStageLabel(stage.code, stage.label)}`}
                  aria-current={stage.availability === "current" ? "step" : undefined}
                  aria-disabled={stage.availability === "locked"}
                >
                  <span className="stage-index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="stage-copy">
                    <strong>{workflowStageLabel(stage.code, stage.label)}</strong>
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
        <span>本地合成数据与固定模拟环境中的比赛原型</span>
        <span>非真实产线 · 非真实设备效果验证</span>
      </footer>
    </div>
  );
}

export default App;
