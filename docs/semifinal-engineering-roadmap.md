# 复赛优先工程阶段

本阶段插入 `tw-08-complete` 与原 TW-09 之间，优先处理入围反馈中能够在仓库内实现和验证的工程工作。采用独立 `SF-*` 编号，避免覆盖既有 TW-09～TW-13 历史与语义；原路线在本阶段工程冻结前保持 deferred。

| ID | 工作项 | 完成条件 | 本次边界 |
| --- | --- | --- | --- |
| SF-01 | OPC-UA sandbox 受控执行 | 本机 server/client、服务端门禁、单参数写前比较、写后回读、持久幂等、不可变凭证、API/UI 和故障测试通过 | 仅 `OPCUA_SANDBOX`；默认关闭；不连接真实设备 |
| SF-02 | 真实设备 shadow 数据适配 | 版本化 mapping manifest、显式单位转换、来源声明、双哈希、质量报告和只读隔离测试通过 | 不制造真实数据；声明不等于真实性验证 |
| SF-03 | shadow 离线分析与评估协议 | `ShadowEvidenceBundle` 绑定 context、reviewed outcome、provenance 与 review contract；analysis contract 绑定控制限、SPC、模型与安全资产；无合法 review contract 固定 `NOT_EVALUABLE`，声明式审核只报告 reviewed-label consistency | 不称 expert evidence；不写任务库/训练集/案例库；不评估真实良率、调机时间或因果收益 |
| SF-04 | 飞书 AI 能力 | Feishu Aily RAG Engineering Copilot 已配置、发布；7/7 Knowledge Pack、检索、LLM、安全 Hard Gates 与 Hero Demo 问答完成人工验收 | 仅解释版本化知识与固定 Demo Evidence；无 Bridge、Runtime API、荐参、确认、Replay 触发或写入权限 |
| SF-05 | 复赛材料 | SF-01～SF-04 工程、验证与事实边界冻结后更新提交材料 | PPT、答辩稿、视频和完整参赛方案仍需后续制作 |

## 冻结顺序

1. 冻结 OPC-UA namespace、节点映射、执行状态与 receipt canonicalizer。
2. 冻结 shadow mapping、analysis contract、质量状态、来源声明与隔离规则。
3. 完成后端、前端、真实 sandbox 协议测试及全量回归。
4. 记录实际命令、测试数量、资产哈希与未验证边界。
5. SF-04 已按独立生成式 AI 协作层完成并验证；后续可进入 SF-05 或恢复原 TW-09。

SF-04 的发布配置与人工验收证据见 [`docs/validation/aily-v1-validation.md`](validation/aily-v1-validation.md)。该完成状态仅指 Aily RAG 工程解释与固定证据问答，不表示已实现实时工业 Agent 或设备控制 Agent。

## 原路线保留

- TW-09：回放拒绝、幂等、并发与异常恢复；
- TW-10：报告与待审核知识案例；
- TW-11：正式离线评估；
- TW-12：集成演示发布门；
- TW-13：Windows 离线发行。

上述 ticket 未被重命名、覆盖或标记完成。SF-01 的设备执行幂等不代表 TW-09 已完成，SF-03 的 shadow 协议也不代表 TW-11 冻结盲测评估已完成。
