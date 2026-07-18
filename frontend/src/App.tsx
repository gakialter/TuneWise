import { useEffect, useState } from "react";

import { createInitialTask, importPresetAsset, Task, TaskCreationError } from "./api";

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

function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [importState, setImportState] = useState<ImportState>({ kind: "idle" });

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
