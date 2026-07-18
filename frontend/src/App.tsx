import { useEffect, useState } from "react";

import {
  AnomalyDetectionResult,
  createInitialTask,
  importPresetAsset,
  runAnomalyDetection,
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

function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [importState, setImportState] = useState<ImportState>({ kind: "idle" });
  const [detectionState, setDetectionState] = useState<DetectionState>({
    kind: "idle",
  });

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
