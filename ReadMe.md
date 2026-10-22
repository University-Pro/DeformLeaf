# DeformLeaf × Multi-3DLLM

本项目整理叶片三维数据，并检查 Multi-3DLLM 对叶片外形和形变的描述能力。本文件是唯一维护的项目说明；第三方仓库文档保留在 `BeyondSingleObject/`。

## 常用入口

- [点云与推理结果对比](Compare/index.html)：左右旋转点云，查看单片描述及 A→B、B→A 回答。
- [整理样本与 mask 索引](DatasetOfficial/index.html)：查看连续编号 1–50 的配套文件。
- [新旧编号对照](DatasetOfficial/NumberMap.csv)、[未配套清单](DatasetOfficial/Unmatched.csv)。
- 原始推理：[360 条结果](DatasetProcessed/Outputs/LeafPairEval/inference.json)；提示词实验：[24 条结果](DatasetProcessed/Outputs/PromptStudy/inference.json)。

## 项目结构

```text
Dataset/                 原始数据
DatasetOfficial/         按官方结构配套的 50 套样本
DatasetProcessed/        点云归档、标注、检查记录和推理结果
BeyondSingleObject/      第三方模型代码与本地权重
Compare/                 对比网页、模板和 BuildCompare.py
Tools/Data/              转换与重建点云、整理官方目录
Tools/Inference/         生成标注、运行提示词实验
Tools/Config/            LeafPairPlan.json 配对配置
Tests/                   采样、加载及页面数据关联检查
ReadMe.md                本项目使用说明
```

`.vscode/` 和 `.claude/` 保留工具配置。配对配置与整理脚本分别维护在 `Tools/Config/LeafPairPlan.json`、`Tools/Data/OrganizeOfficialDataset.py`。自动生成 README 译文的钩子已关闭。

## 原始 Dataset 各目录

`base` 表示叶片摊平后的基础外形，`deform` 表示弯曲、卷曲或扭转后的三维状态。作者通过多角度摄影重建形变叶片，并从基础图片的分割掩膜制作平面网格。[官方数据说明](https://github.com/Yrainy0615/NeuraLeaf#dataset)

| 目录 | 含义 |
| --- | --- |
| `base_img` | 基础状态的彩色叶片图片 |
| `base_mask` | 叶片区域掩膜，以及 SDF 等辅助数据 |
| `base_shape` | 基础平面 OBJ 网格，可能配有 MTL 和纹理图片 |
| `deform_raw` | 按名称理解为较原始的形变三维数据 |
| `deform_raw_denoise` | 按名称理解为去噪后的形变数据，既有网格也有纯点云 |
| `deform_train` | 官方训练程序使用的形变数据；当前 122 个 PLY 实际均为纯点云 |
| `deform_train_new` | 另一版训练数据，具体处理差异尚未确认 |
| `deform_raw_new` | 当前为空，具体用途尚未确认 |
| `base_shape_extra` | 补充基础网格及配套资源 |
| `base_mask_extra` | 补充掩膜、图片及距离场 |
| `maple_extra` | 按命名判断为枫叶补充资料，内部还有图片和三维子目录 |

`extra` 不代表一定是合成数据，`new` 也不证明质量更好。`sdf` 是描述位置到叶片边界距离的数组。Dataset 内已有的 `output/` 在本项目首次处理前就已存在，主要包含历史距离场产物，因此保留。

2026-10-19 检查：507 个三维文件、530 张图片、152 个 NPY 可读取，但有 93 个三维文件引用缺失材质或纹理。没有官方逐文件清单，不能确认发布内容是否齐全。详细记录保留在 [DatasetAudit.json](DatasetProcessed/DatasetAudit.json)。

## 整理数据与模型输入

`DatasetOfficial` 是按名称配套的子集，不代表完整官方发布包，也未全部人工核实叶片身份和配准。每个编号对应 `base_shape/{编号}.obj`、`base_mask/{编号}.png`，以及 `deform_train/{编号}_deform.ply` 或 `{编号}.obj`。共 50 套：28 个形变文件是纯点云，22 个是网格；另有 22 个同名、尺寸相符但未重算的可选 SDF。33 套仍缺部分颜色资源。

多个形变候选按 `deform_train → deform_train_new → deform_raw_denoise → deform_raw` 选择，同目录优先 `_deform`；`_base.ply` 不作为形变。来源、替代版本和校验值保存在 [Manifest.json](DatasetOfficial/Manifest.json)。整理脚本拒绝覆盖非空目标目录。

模型实际读取 **点云数组与文字问题**，推理时不访问 `Dataset/`：标注 [LeafEvalAll.json](DatasetProcessed/LeafEvalAll.json) 用 `LeafPointClouds.npz::数组键` 引用 [LeafPointClouds.npz](DatasetProcessed/LeafPointClouds.npz) 中的数组。网格按三角面面积采样，纯点云随机抽点；每片 `(8192, 6)`、float32，六列 XYZRGB。颜色取自 PLY 顶点 RGB 或 OBJ 纹理，缺失处补灰色；坐标不压平、不对齐，加载时再逐片居中并按最大半径缩放，因此不能比较真实物理尺寸。

当前归档覆盖 `Dataset/` 下全部 507 个几何文件（162 个 OBJ、345 个 PLY），压缩后 47.9 MB，转换失败 0 个。OBJ 在此都是三角网格；PLY 既有网格也有纯点云（`deform_raw_denoise` 为 41 网格、35 点云，`deform_train` 全部为纯点云）。

`base_shape` 与 `deform_raw_denoise` 不是一一对应的两组：当前分别为 116 个和 76 个文件，仅共享 43 个编号。正式配对只存在于 `DatasetOfficial/` 的 50 套与 [LeafPairPlan.json](Tools/Config/LeafPairPlan.json)。另有 44 个文件构成 37 组“异名同物”（内容完全相同，如 `deform_train/12_deform.ply` 与 `deform_train_new/12_deform.ply`），清单的 `DuplicateGroups` 已列出。

颜色覆盖有限：507 个对象中 392 个存在灰色回填，采样点中约 77%（321 万 / 415 万）没有来源颜色，主要集中在纯点云的形变数据。

**版本关系：**旧 253 个点云的归档由当时的 174 个基础 OBJ 与 79 个去噪 PLY 生成，其中 126 个来源路径现已不存在；新归档按当前目录重建，两者只有 127 个键重合。旧 360 条结果不能当作新归档的测试结果，旧文件保留在 `DatasetProcessed/Backup_20261020/`。

## 对比页面

打开 [Compare/index.html](Compare/index.html)，页面只包含当前 `DatasetOfficial` 的 50 套配对样本：100 个点云、200 条回答（100 条单片描述 + 100 条 A→B / B→A 比较），不再混入历史结果。左右各展示单片描述，下方展示双向比较。

页面支持中文、日语、英语三种界面语言（右上角切换，选择会保存在浏览器本地）；模型回答保持英文原文，不自动翻译或评分。样本总览可点击编号跳转，支持搜索、交换左右、联动或独立旋转缩放、视角与 RGB 切换、隐藏回答，以及 `←`/`→`、`S`、`1`/`2`/`3`、`R`、`H` 快捷键。每片显示全部 8192 点。

构建时按归档键精确关联回答；引用缺失的回答会跳过并计数，不会借用旧结果。浏览器需支持 WebGL 和 DecompressionStream，可直接打开本地 HTML。

在项目根目录执行：

```bash
conda run -n leaf-env python Compare/BuildCompare.py
conda run -n leaf-env python Tests/TestCompare.py
```

构建只更新 `Compare/index.html` 与 `BuildReport.json`，不运行模型；默认读取 `DatasetProcessed/Outputs/OfficialEval/inference.json`，生成仅依赖 NumPy。

## 转换与推理

转换器只读原始 `Dataset/`，不读取 `DatasetOfficial/`。按当前目录重建归档、清单与标注，覆盖前会自动备份旧文件到 `DatasetProcessed/Backup_<日期>/`：

```bash
conda run -n leaf-env python Tools/Data/RebuildLeafArchive.py
```

一次写出 `LeafPointClouds.npz`、`LeafManifest.json`、`LeafPair.json`、`LeafEvalAll.json`。`LeafEvalAll.json` 共 607 条：507 条单片描述，加 `DatasetOfficial/` 50 套的双向比较 100 条。旧脚本 `ConvertLeafDataset.py --all` 仍保留，但 `LeafPairPlan.json` 有 2 个来源已被删除，直接运行会中断；`BuildLeafEvalAnnotation.py` 已不是主路径。

已有 `leaf-env` 和本地主权重。若需重建环境或下载权重，参考 [上游说明](BeyondSingleObject/README.md)。用于描述和比较的是 `checkpoints/multi-3dllm`，无需分类权重或训练初始化权重。

`leaf-env` 当前为 transformers 4.57.6、torch 2.8.0、timm 1.0.30。模型继承 `LlamaForCausalLM` 并自行处理 KV cache：transformers ≥4.36 会在首步传入一个空但判真的 `Cache`，上游 `if past_key_values:` 因而截掉完整提示与点云特征；`pointllm_cvpr.py`、`pointllm.py` 中的 `prepare_inputs_for_generation` 已改为按 `get_seq_length()` 判断。这是本地补丁，上游没有，重新克隆前必须保留。仓库未固定 transformers 版本，升级后先用 `LIMIT=1` 验证。

模型推理先运行一条确认输入，`LIMIT=0` 才会运行全部标注；新输出目录避免覆盖旧结果：

```bash
cd BeyondSingleObject
CUDA_VISIBLE_DEVICES=0 \
MODEL_PATH=checkpoints/multi-3dllm \
ANNO_PATH=../DatasetProcessed/LeafEvalAll.json \
DATA_PATH=../DatasetProcessed \
OUTPUT_DIR=../DatasetProcessed/Outputs/LeafPairEvalNew \
LIMIT=1 MAX_NEW_TOKENS=256 TEMPERATURE=0 \
conda run --no-capture-output -n leaf-env bash scripts/eval/infer.sh
```

自由描述的参考答案为空，`exact_match`、`relaxed_match` 不适合当作本实验准确率。基本推理不需要 OpenAI API Key，人工评价应关注轮廓、形变、比较方向和虚构细节。

本地上游代码含多类修改：支持共享 NPZ 数组键；修正两个模型变体的 `prepare_inputs_for_generation`，按缓存实际 token 长度判断是否截断，避免首步丢失完整提示和点云特征；为 timm ≥0.9 的 `DropPath` 导入和 torch ≥2.6 的 `weights_only` 默认值加兼容处理。更新或重新克隆上游前应保存这些修改。

## 提示词检查结论

实际完成了 4 种输入 × 3 种 prompt × 2 个固定种子的 24 条 GPU 推理，分别测试原问法、仅几何问法和叶片背景问法；均使用相同点云与生成参数，token 上限 128。原 360 条运行的上限为 256，不能直接混为同一条件。

三种提示在同文件对照的两次运行中都编造差异，共 6 次；加入“这是叶片”改变了措辞，但没有证明几何判断更准。这是小规模检查，不是全数据集错误率。比较时应允许“相同”或“不确定”，而不是强制寻找差异。

点编码器的 FPS 使用随机起点，`temperature=0` 不会固定它。实验在每条输入前重置随机种子，但同物体的两个输入仍可能分别抽到不同中心；数值不确定性等因素尚未单独排除，不能只归因于 prompt。

结果和参数保留在 [PromptStudy](DatasetProcessed/Outputs/PromptStudy/)，可查看 [Results.csv](DatasetProcessed/Outputs/PromptStudy/Results.csv) 和 [Method.json](DatasetProcessed/Outputs/PromptStudy/Method.json)。重做实验使用：

```bash
# 不带 --run 仅生成标注；带 --run 加载模型。均会替换本实验的对应输出。
conda run -n leaf-env python Tools/Inference/EvaluateLeafPrompts.py --run
```
