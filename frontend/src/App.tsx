import { useEffect, useState } from "react";

import { createInitialTask, Task, TaskCreationError } from "./api";

const versionLabels: Record<keyof Task["versions"], string> = {
  public_asset_version: "公共资产",
  application_version: "应用",
  dataset_version: "数据集",
  schema_version: "数据结构",
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

function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

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

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#workspace" aria-label="TuneWise 首页">
          <span className="brand-mark">TW</span>
          <span>
            <strong>TuneWise</strong>
            <small>OFFLINE DECISION SUPPORT</small>
          </span>
        </a>
        <div className="offline-badge">
          <span />
          本地离线
        </div>
        <div className="actor-summary">
          <span className="avatar">AA</span>
          <span>
            <strong>{task.actor.display_name}</strong>
            <small>{task.actor.actor_role}</small>
          </span>
        </div>
      </header>

      <main id="workspace" className="workspace">
        <section className="hero">
          <div>
            <p className="eyebrow">AA 工站 · 调机任务</p>
            <h1>任务与版本状态</h1>
            <p className="hero-copy">
              本地版本资产已通过完整性校验。当前任务仅开放创建阶段，后续闭环等待对应能力就绪。
            </p>
          </div>
          <div className="task-status-card">
            <span>当前任务状态</span>
            <strong>{task.status}</strong>
            <small>{task.task_id}</small>
          </div>
        </section>

        <section className="stage-panel" aria-labelledby="workflow-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">WORKFLOW</p>
              <h2 id="workflow-title">任务闭环</h2>
            </div>
            <span className="readonly-chip">只读导航</span>
          </div>
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
                  {stage.availability === "current" ? "当前阶段" : "未开放"}
                </span>
              </li>
            ))}
          </ol>
        </section>

        <div className="details-grid">
          <section className="detail-panel" aria-labelledby="identity-title">
            <div className="section-heading compact">
              <div>
                <p className="eyebrow">ACTOR</p>
                <h2 id="identity-title">固定演示身份</h2>
              </div>
              <span className="readonly-chip">只读</span>
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

          <section className="detail-panel versions" aria-labelledby="versions-title">
            <div className="section-heading compact">
              <div>
                <p className="eyebrow">VERSION ASSETS</p>
                <h2 id="versions-title">公共版本摘要</h2>
              </div>
              <span className="verified-chip">完整性已验证</span>
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
      <footer>
        <span>仅用于规则约束模拟环境中的离线比赛原型</span>
        <span>无真实设备连接 · 无在线服务依赖</span>
      </footer>
    </div>
  );
}

export default App;
