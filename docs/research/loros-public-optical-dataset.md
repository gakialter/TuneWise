# LOROS 公开光学数据集一手资料核验

核验日期：2026-08-11

## 范围与结论摘要

本文只核验 LOROS 公开数据集的身份、来源、实验真实性、许可、可下载文件和公开字段语义，不把该数据称为舜宇数据、AA production data 或 TuneWise 分类器标签数据，也不推导任何 root-cause ground truth、推荐准确率或因果效果。

一手证据支持以下结论：

- 这是 Rikkyo University 研究者发布、用于表征 Laboratory OROCHI Simulator（LOROS）的公开实验数据集；LOROS 是用商用现成部件搭建的实验室相机系统，不是舜宇或 AA 产线设备。
- MTF A 子集来自真实的 slanted-edge 光学实验采集，但公开的 MTF ROI TIFF 已经过 25 帧平均、暗场扣除和 12-bit 到 8-bit 转换，不是逐帧原始图像。
- MTF A 子集有真实测量 MTF、ROI TIFF、MTF Mapper 派生 MTF/SFR 文本和有限的采集上下文，但没有 TuneWise 所需的装调参数、五点空间 MTF、逐样本时间戳、root-cause/review 标签或干预前后结果。
- 官方说明与论文称随机方向测量为 5 次/5 个方向，实际 ZIP 却包含 `_0` 至 `_5` 六个方向目录，汇总 CSV 也包含 `Pos 0` 至 `Pos 5`。在任何下游使用前必须将其作为 provenance/data-quality discrepancy 保留，不能静默改写。

## 1. 正式身份、来源与 DOI

| 项目 | 核验结果 | 一手来源 |
| --- | --- | --- |
| 数据集正式标题 | `Dataset for "LOROS: Laboratory Simulations of the Optical RadiOmeter composed of CHromatic Imagers (OROCHI) Experiment of the Martian Moons eXploration (MMX) Mission"` | [Zenodo 当前记录](https://zenodo.org/records/17493261)，[Zenodo API 元数据](https://zenodo.org/api/records/17493261) |
| 作者/机构 | Roger Stabbins、Shingo Kameda；Rikkyo University | [Zenodo 当前记录](https://zenodo.org/records/17493261) 的 Authors/Creators |
| 概念 DOI（全部版本） | `10.5281/zenodo.14028647` | [Zenodo API 元数据](https://zenodo.org/api/records/17493261) 的 `conceptdoi` |
| 论文明确引用的数据版本 | `10.5281/zenodo.14028648`，Zenodo v0.1，发布日期 2024-11-02 | [论文 Data availability](https://link.springer.com/article/10.1186/s40645-025-00783-7#data-availability)，[v0.1 记录](https://zenodo.org/records/14028648) |
| 当前最新记录 DOI | `10.5281/zenodo.17493261`，发布日期 2025-10-31 | [Zenodo 当前记录](https://zenodo.org/records/17493261)，[Zenodo API 元数据](https://zenodo.org/api/records/17493261) |
| 配套论文 DOI | `10.1186/s40645-025-00783-7` | [Progress in Earth and Planetary Science 论文](https://doi.org/10.1186/s40645-025-00783-7) |

论文在 “Availability of data and material” 中明确把研究生成/分析的数据指向 Zenodo v0.1 DOI。当前最新记录和 v0.1 属于同一 Zenodo concept；为可复现性，实际实验应同时固化具体 record DOI、文件 checksum 和下载日期，不能只写概念 DOI。

## 2. 是否为真实实验采集

是，但必须准确描述为“LOROS 实验室模拟器的真实光学测量”，不能描述为 AA 产线或量产调机数据。

论文 §3.2 “Spatial sampling” 给出完整实验链路：在距相机 0.8 m 的物平面放置背照明 razorblade slanted edge；每个光谱通道采集 25 张照明图和 25 张匹配暗场；暗场扣除、flat-field、平均并转为 8-bit 灰度后，从 40×40 pixel ROI 通过 MTF Mapper 推导 line-spread function 与 MTF；论文还称该测量以随机重新定向的 knife edge 重复 5 次。[论文 §3.2](https://link.springer.com/article/10.1186/s40645-025-00783-7#Sec12)

Zenodo 数据说明与 A 子集 README 独立确认：ROI 图像由 25 个 repeat images 平均、已做 dark-frame subtraction，并从 12-bit 转为 8-bit；MTF 与 SFR diagnostics 是 MTF Mapper 生成的派生输出。[Zenodo 数据说明，Dataset A](https://zenodo.org/records/17493261)，[A 子集 README](https://zenodo.org/api/records/17493261/files/dataset.zip/container/dataset/A_modulation_transfer_function/README.md)

因此各文件的真实性层级应区分为：

- 实验观测来源：真实 LOROS 相机系统与真实 slanted-edge target；
- `img/*.tif`：处理后的 40×40 ROI 平均图，不是 25 张逐帧原始曝光；
- `*_annotated.jpg`、`*_edge_mtf_values.txt`、`*_edge_sfr_values.txt` 与汇总 CSV：由上述 ROI 经 MTF Mapper/研究者脚本派生；
- 论文中的全局实验配置可以作为方法上下文，但不能填补数据文件中不存在的逐样本 acquisition metadata。

## 3. License

当前记录与 v0.1 记录均标记为 **Creative Commons Attribution 4.0 International (`CC-BY-4.0`)**。[Zenodo 当前记录 Rights](https://zenodo.org/records/17493261#rights)，[CC BY 4.0 法律文本](https://creativecommons.org/licenses/by/4.0/legalcode)

允许在正确署名的条件下复用和再分发。当前 ZIP 内未见独立 `LICENSE` 文件；因此 provenance 至少应保留作者、数据集标题、具体 record DOI、`CC-BY-4.0`、原始 checksum、访问日期以及是否做过转换。该许可不改变数据的设备身份，也不授权把 LOROS 伪称为其他企业或产线数据。

## 4. 可下载文件与 MTF A 子集清单

Zenodo record 顶层只发布一个文件：

| 文件 | 大小 | checksum | 下载/索引 |
| --- | ---: | --- | --- |
| `dataset.zip` | 3,428,226,096 bytes | `md5:116a33dccecaba6a770c68e469099a6b` | [整包下载](https://zenodo.org/api/records/17493261/files/dataset.zip/content)，[容器成员索引](https://zenodo.org/api/records/17493261/files/dataset.zip/container) |

官方容器索引显示 `dataset/A_modulation_transfer_function/` 下共 195 个成员：

- `mtf_results_07122023.csv`：1 个，1,666 bytes；
- `README.md`：1 个；
- `mtf_measurements_processing_0712023.ipynb`：1 个，58,456,833 bytes；
- 6 个方向目录（`..._0` 到 `..._5`）× 8 个 LOROS channel：48 个 ROI TIFF、48 个 annotated JPG、48 个 MTF summary TXT、48 个 SFR TXT。

可直接读取的小文件示例：

- [MTF 汇总 CSV](https://zenodo.org/api/records/17493261/files/dataset.zip/container/dataset/A_modulation_transfer_function/mtf_results_07122023.csv)
- [850 nm、Pos 0 的 ROI TIFF](https://zenodo.org/api/records/17493261/files/dataset.zip/container/dataset/A_modulation_transfer_function/mtf_measurements_07122023/mtf_knifeedge_low_07122023_0/img/0_850_img_ave.tif)
- [对应 MTF summary](https://zenodo.org/api/records/17493261/files/dataset.zip/container/dataset/A_modulation_transfer_function/mtf_measurements_07122023/mtf_knifeedge_low_07122023_0/results/0_850_img_ave_edge_mtf_values.txt)
- [对应 SFR values](https://zenodo.org/api/records/17493261/files/dataset.zip/container/dataset/A_modulation_transfer_function/mtf_measurements_07122023/mtf_knifeedge_low_07122023_0/results/0_850_img_ave_edge_sfr_values.txt)

## 5. 文件内容与字段

### 5.1 `mtf_results_07122023.csv`

CSV 由 8 个 channel 行组成，channel/CWL 组合为 `2/400`、`1/475`、`3/550`、`6/550`、`7/650`、`4/725`、`0/850`、`5/950`。顶部记录 sensor Nyquist frequency `85.32423208 lp/mm`，字段为：

- 公共列：`Channel`、`CWL`、`Nyq. Target`、`Mean Targ. Freq. lp/mm`、`Std. Dev. Targ. Freq. lp/mm`、`Mean Nyq. MTF`、`Std. Dev. Nyq. MTF`；
- 每个 `Pos 0` 至 `Pos 5` 的重复列：`Line Angle °`、`Targ. Freq. lp/mm`、`Nyq. MTF`。

`Nyq. MTF` 为归一化 MTF 数值（示例范围约 0.202–0.461）；`Line Angle` 是 slanted edge 在图像中的方向，不是设备装调的 `pitch` 或 `roll`；`CWL` 是 channel 中心波长，不是样本位置。[直接查看 CSV](https://zenodo.org/api/records/17493261/files/dataset.zip/container/dataset/A_modulation_transfer_function/mtf_results_07122023.csv)

### 5.2 ROI TIFF 与 annotated JPG

文件名编码 channel 与名义波长，例如 `0_850_img_ave.tif`。README 只支持把它解释为对应方向、对应 channel 的处理后 ROI 平均图。目录/文件名中的 position 是 knife-edge 重新定向次数，不是成像面的 center/top-left/top-right/bottom-left/bottom-right 位置。

### 5.3 `*_edge_mtf_values.txt`

MTF Mapper `output format version 2` 的九列为：

1. `block_id`
2. edge centroid x (pixels)
3. edge centroid y (pixels)
4. MTF-30 value (lp/mm)
5. nearby corner x (pixels)
6. nearby corner y (pixels)
7. mean CNR
8. effective oversampling factor
9. effective edge length

注意这里的 `nearby corner x/y` 是 MTF Mapper 输出格式中的几何辅助字段，不能据此声称存在 TuneWise 的四角 MTF 观测。[直接查看样例](https://zenodo.org/api/records/17493261/files/dataset.zip/container/dataset/A_modulation_transfer_function/mtf_measurements_07122023/mtf_knifeedge_low_07122023_0/results/0_850_img_ave_edge_mtf_values.txt)

### 5.4 `*_edge_sfr_values.txt`

前 13 列为 `block_id`、edge centroid x/y、slanted-edge orientation、相对 radial line 的方向、mean/dark/bright CNR、dark/bright SNR、contrast、oversampling factor、edge length，后续为 SFR samples。[直接查看样例](https://zenodo.org/api/records/17493261/files/dataset.zip/container/dataset/A_modulation_transfer_function/mtf_measurements_07122023/mtf_knifeedge_low_07122023_0/results/0_850_img_ave_edge_sfr_values.txt)

## 6. Acquisition metadata：存在与缺失

公开材料可提供的上下文包括：LOROS/OROCHI 设备身份、Sony IMX249/DMK 33GX249 相机类型、8 个光谱 channel、名义波长、0.8 m 工作距离、slanted-edge 方法、25 张照明图与 25 张暗场、40×40 pixel ROI、12-bit acquisition 到 8-bit processing、MTF Mapper、sensor Nyquist frequency，以及文件名中的日期/方向编号。[论文设备与方法](https://link.springer.com/article/10.1186/s40645-025-00783-7#Sec4)，[论文 §3.2](https://link.springer.com/article/10.1186/s40645-025-00783-7#Sec12)

MTF A 子集没有逐样本提供：

- 带时区的 acquisition timestamp；文件名 `07122023` 不能无歧义证明日期格式、时刻或时区；
- exposure、gain、offset、aperture、focus position 的逐 ROI 值；
- `x_offset`、`y_offset`、`pitch`、`roll`、`z_offset`；
- vibration RMS、repeat-position error、calibration residual x/y；
- 成像面中心加四角的五点 MTF；
- batch、lot、AA station、生产设备或产线标识；
- reviewed anomaly、root cause、parameter direction、人工 review protocol；
- 参数干预前后配对或生产良率结果。

Zenodo 数据说明提到的 `camera_config.csv` 位于 radiometric-calibration 子集的 photon/dark transfer 实验中，描述对应实验 ROI 坐标和尺寸；它不是 MTF A 子集的逐样本配置，不能跨实验借用来补齐 MTF 记录。[Zenodo Dataset C/D 说明](https://zenodo.org/records/17493261)

## 7. 对 TuneWise 字段映射的证据边界

以下只是字段语义核对，不代表已经生成或批准 mapping manifest。

| LOROS 字段/结构 | 可支持的最窄解释 | 不能解释为 |
| --- | --- | --- |
| `Pos 0..5` | 同一 slanted-edge 实验的重新定向编号，可作为外部 observation identifier 候选 | 生产 `batch/lot`、时间序列、五个成像面空间位置 |
| `Channel` / `CWL` | 光谱 channel 与名义中心波长的 context | TuneWise 参数、根因、位置坐标 |
| 每 Pos 的 `Nyq. MTF` | 中心 sample-region ROI 的归一化 MTF 观测，最多是 `mtf_center` 的语义候选 | `mtf_lt/rt/lb/rb` 或推荐正确性 |
| `Line Angle °` | slanted edge orientation | 设备 `pitch` / `roll` |
| edge centroid x/y | 40×40 ROI 内检测边缘的像素质心 | AA stage `x_offset` / `y_offset` |
| MTF-30 / SFR / CNR / SNR | MTF Mapper 派生的光学质量与处理诊断 | classifier root cause、设备控制参数或参数方向 ground truth |

依照当前仓库文档所列 16 个冻结 observable 字段，LOROS A 子集最多能为 `mtf_center` 提供谨慎候选，无法诚实补齐其余 15 个字段。把一个中心 ROI 的 MTF 复制到四角、把 edge angle 改名为 pitch/roll、把 wavelength 改名为 offset，或从文件日期伪造逐样本 timestamp，都会改变原始语义，不是合法映射。

## 8. Ground truth 与外部验证能力

数据集论文和公开文件的目标是表征/验证 LOROS 光学性能，不是诊断 AA 装调异常。公开字段中没有 TuneWise 冻结异常类别、root-cause 类别、参数方向 review，也没有调参干预结果。因此：

- 可以独立核验真实光学测量、文件 provenance、MTF 数值解析、SFR/ROI 可追溯性和公开数据内部一致性；
- 不能据此计算 TuneWise classifier accuracy、root-cause accuracy、推荐准确率、良率改善、调机时间下降或参数因果效果；
- 不能把 `Nyq. Target` 或论文性能要求转换成 reviewed anomaly/root-cause 标签；
- 若只使用现有 Shadow Data Adapter 且不修改 production code，公开字段不足以构造完整、语义真实的 16-field canonical observation；任何“成功导入”都将依赖伪造/错配字段。

## 9. 已发现的数据质量风险

1. **方向次数矛盾**：Zenodo 描述、A README 和论文均称 5 个随机方向/重复 5 次；实际汇总 CSV 有 `Pos 0..5` 六组，ZIP 有 `_0.._5` 六个目录。应原样报告并在实验 manifest/provenance 中注明，不能擅自删除某一组或把六组写成五组。
2. **处理后而非逐帧原始 MTF ROI**：A 子集 ROI 是 25 帧平均、暗场扣除且量化到 8-bit 的处理产物；不能将其描述为 raw sensor frames。
3. **元数据跨子集风险**：radiometric-calibration 中存在 `camera_config.csv` 不表示它适用于 MTF A 子集；没有明确 join key 和实验契约时不得跨子集合并。
4. **最新 record 与论文引用版本不同**：论文引用 v0.1 DOI，而 Zenodo 现有更新 record。实验必须固定选择的 record DOI/checksum，避免“latest”漂移。

## 10. 一手来源索引

- Zenodo 当前记录与数据说明：[https://zenodo.org/records/17493261](https://zenodo.org/records/17493261)
- Zenodo 当前 API 元数据（DOI、concept DOI、license、文件大小/checksum）：[https://zenodo.org/api/records/17493261](https://zenodo.org/api/records/17493261)
- Zenodo ZIP 成员索引与逐成员下载链接：[https://zenodo.org/api/records/17493261/files/dataset.zip/container](https://zenodo.org/api/records/17493261/files/dataset.zip/container)
- Zenodo v0.1 记录：[https://zenodo.org/records/14028648](https://zenodo.org/records/14028648)
- 配套论文：[https://doi.org/10.1186/s40645-025-00783-7](https://doi.org/10.1186/s40645-025-00783-7)
- CC BY 4.0：[https://creativecommons.org/licenses/by/4.0/legalcode](https://creativecommons.org/licenses/by/4.0/legalcode)
