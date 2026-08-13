# TuneWise 赛事报名材料

该目录保存 2026 AI先锋未来人才大赛舜宇光学科技命题的报名原始信息与当前提交文本，作为后续需求澄清、产品规格、开发实现和答辩材料的上游事实来源。

## 文件说明

- [`challenge-brief.md`](./challenge-brief.md)：企业命题、赛区和核心要求。
- [`part-1.md`](./part-1.md)：开题报告 Part 1 的报名要求与当前提交文本。
- [`part-2.md`](./part-2.md)：开题报告 Part 2 的报名要求、当前提交文本与方案硬边界。
- [`submission-materials.md`](./submission-materials.md)：以上内容的单文件汇总版。
- [`../validation/aily-v1-validation.md`](../validation/aily-v1-validation.md)：已发布飞书 Aily V1 的人工功能、安全边界与 Hero Demo 验收记录。
- `2026 AI先锋未来人才大赛舜宇光学科技命题深度研究报告.docx`：前期背景研究，不是当前实现状态记录；其中关于 LLM/RAG 的内容只作为选型背景。
- `TuneWise_AI智造调机助手_开题补充材料_Cobalt_v2.pdf`：实现前的历史开题补充稿，尚未包含 Aily V1 发布事实，并仍有“下一步实现”措辞；已由当前 Markdown 比赛叙事取代，不得直接作为最终提交版本。

## 使用规则

1. 后续 PRD、CONTEXT、ADR、任务拆解和代码实现不得与本目录中的命题原文冲突。
2. 如报名页内容发生修改，应先更新本目录，再更新下游文档。
3. 公开事实、合理推断和原型假设必须明确区分。
4. 不得虚构舜宇真实设备、工艺参数、接口、数据或良率效果。
5. 当前状态以 README、`submission-materials.md`、submission 目录和 validation 记录为准；制作最终 PPT/PDF 时必须同步双层 AI 与 Aily V1 事实边界。
