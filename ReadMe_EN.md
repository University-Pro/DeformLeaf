> This file is generated automatically by the `readme-translator` subagent; do not edit it by hand. Make changes in `ReadMe.md`.
> Source file: `ReadMe.md` (sha256 `22eb2ac16b3719cfaab61b2b07361ba0b399a513d082fecc8f20822a8d9f46ce`, 2026-10-22)

# DeformLeaf × Multi-3DLLM

This project organizes three-dimensional leaf data and examines Multi-3DLLM's ability to describe leaf shape and deformation. This file is the only maintained project description; third-party repository documentation remains in `BeyondSingleObject/`.

## Common entry points

- [Point cloud and inference result comparison](Compare/index.html): rotate the point clouds on either side and view the single-object descriptions plus the A→B and B→A answers.
- [Organized samples and mask index](DatasetOfficial/index.html): view the companion files numbered consecutively 1–50.
- [Old-to-new numbering map](DatasetOfficial/NumberMap.csv), [unmatched manifest](DatasetOfficial/Unmatched.csv).
- Raw inference: [360 results](DatasetProcessed/Outputs/LeafPairEval/inference.json); prompt experiment: [24 results](DatasetProcessed/Outputs/PromptStudy/inference.json).

## Project structure

```text
Dataset/                 raw data
DatasetOfficial/         the 50 sample sets assembled in the official structure
DatasetProcessed/        point cloud archive, annotations, inspection records, and inference results
BeyondSingleObject/      third-party model code and local weights
Compare/                 comparison web page, template, and BuildCompare.py
Tools/Data/              converting and rebuilding point clouds, organizing the official directory
Tools/Inference/         generating annotations, running the prompt experiment
Tools/Config/            LeafPairPlan.json pairing configuration
Tests/                   sampling, loading, and page data association checks
ReadMe.md                usage instructions for this project
```

`.vscode/` and `.claude/` retain tool configuration. The pairing configuration and the organization script are maintained in `Tools/Config/LeafPairPlan.json` and `Tools/Data/OrganizeOfficialDataset.py` respectively. The hook that automatically generates README translations has been turned off.

## Directories in the original Dataset

`base` denotes the base shape of a leaf after flattening, and `deform` denotes the three-dimensional state after bending, curling, or twisting. The authors reconstructed deformed leaves from multi-angle photography and produced flat meshes from the segmentation masks of the base images. [Official data description](https://github.com/Yrainy0615/NeuraLeaf#dataset)

| Directory | Meaning |
| --- | --- |
| `base_img` | color leaf images in the base state |
| `base_mask` | leaf-region mask, plus auxiliary data such as SDF |
| `base_shape` | base flat OBJ mesh, possibly with MTL and texture images |
| `deform_raw` | understood from the name as the more raw deformed 3D data |
| `deform_raw_denoise` | understood from the name as denoised deformation data, containing both meshes and pure point clouds |
| `deform_train` | deformation data used by the official training program; the current 122 PLY files are in fact all pure point clouds |
| `deform_train_new` | another version of the training data; the exact processing differences are not yet confirmed |
| `deform_raw_new` | currently empty; the intended use is not yet confirmed |
| `base_shape_extra` | supplementary base meshes and companion resources |
| `base_mask_extra` | supplementary masks, images, and distance fields |
| `maple_extra` | judged from the naming to be supplementary maple leaf material, with further image and 3D subdirectories inside |

`extra` does not mean the data is necessarily synthetic, and `new` does not prove better quality. `sdf` is an array describing the distance from a position to the leaf boundary. The `output/` already present inside Dataset existed before this project first processed it and mainly contains historical distance-field products, so it is kept.

Inspection on 2026-10-19: 507 3D files, 530 images, and 152 NPY files are readable, but 93 3D files reference missing materials or textures. There is no official per-file manifest, so it cannot be confirmed whether the published content is complete. Detailed records are kept in [DatasetAudit.json](DatasetProcessed/DatasetAudit.json).

## Organized data and model input

`DatasetOfficial` is a subset paired by name; it does not represent the complete official release package, and leaf identity and registration have not all been verified manually. Each number corresponds to `base_shape/{编号}.obj`, `base_mask/{编号}.png`, and either `deform_train/{编号}_deform.ply` or `{编号}.obj`. 50 sets in total: 28 deformation files are pure point clouds and 22 are meshes; there are also 22 optional SDFs with the same name and matching dimensions that were not recomputed. 33 sets still lack some color resources.

Multiple deformation candidates are selected in the order `deform_train → deform_train_new → deform_raw_denoise → deform_raw`, with `_deform` preferred within the same directory; `_base.ply` is not treated as a deformation. Sources, alternative versions, and checksums are stored in [Manifest.json](DatasetOfficial/Manifest.json). The organization script refuses to overwrite a non-empty target directory.

The model actually reads **point cloud arrays and textual questions**, and does not access `Dataset/` during inference: the annotation [LeafEvalAll.json](DatasetProcessed/LeafEvalAll.json) references arrays in [LeafPointClouds.npz](DatasetProcessed/LeafPointClouds.npz) using `LeafPointClouds.npz::array key`. Meshes are sampled by triangle area and pure point clouds are sampled randomly; each leaf is `(8192, 6)` in float32, six columns of XYZRGB. Colors come from PLY vertex RGB or OBJ textures, with gray filled in where missing; coordinates are neither flattened nor aligned, and are centered per leaf and scaled by the maximum radius at load time, so true physical sizes cannot be compared.

The current archive covers all 507 geometry files under `Dataset/` (162 OBJ, 345 PLY), 47.9 MB after compression, with 0 conversion failures. The OBJ files here are all triangle meshes; the PLY files include both meshes and pure point clouds (`deform_raw_denoise` has 41 meshes and 35 point clouds, `deform_train` is entirely pure point clouds).

`base_shape` and `deform_raw_denoise` are not two groups in one-to-one correspondence: they currently hold 116 and 76 files respectively and share only 43 numbers. Formal pairing exists only for the 50 sets in `DatasetOfficial/` and [LeafPairPlan.json](Tools/Config/LeafPairPlan.json). Another 44 files form 37 groups of "same thing under different names" (the contents are exactly identical, e.g. `deform_train/12_deform.ply` and `deform_train_new/12_deform.ply`); the manifest's `DuplicateGroups` lists them.

Color coverage is limited: 392 of the 507 objects have gray fill-in, and about 77% of sampled points (3.21 million / 4.15 million) have no source color, concentrated mainly in the pure point cloud deformation data.

**Version relationship:** The old archive of 253 point clouds was generated from the then 174 base OBJs and 79 denoised PLYs, of which 126 source paths no longer exist; the new archive was rebuilt from the current directories, and only 127 keys overlap between the two. The old 360 results cannot be treated as test results for the new archive; the old files are kept in `DatasetProcessed/Backup_20261020/`.

## Comparison page

Open [Compare/index.html](Compare/index.html). The page contains only the 50 paired sample sets of the current `DatasetOfficial`: 100 point clouds and 200 answers (100 single-object descriptions + 100 A→B / B→A comparisons), with no historical results mixed in any longer. Each side shows one single-object description, and the two-way comparison is shown below.

The page supports three interface languages, Chinese, Japanese, and English (switched in the upper right; the choice is saved locally in the browser); model answers stay in the original English and are not translated or scored automatically. In the sample overview, clicking a number jumps to that sample; the page supports search, swapping left and right, linked or independent rotation and zoom, viewpoint and RGB switching, hiding answers, and the `←`/`→`, `S`, `1`/`2`/`3`, `R`, and `H` shortcuts. Each leaf displays all 8192 points.

At build time, answers are associated exactly by archive key; answers with missing references are skipped and counted, and old results are not borrowed. The browser must support WebGL and DecompressionStream; the local HTML can be opened directly.

Run the following in the project root:

```bash
conda run -n leaf-env python Compare/BuildCompare.py
conda run -n leaf-env python Tests/TestCompare.py
```

The build only updates `Compare/index.html` and `BuildReport.json` and does not run the model; it reads `DatasetProcessed/Outputs/OfficialEval/inference.json` by default, and generation depends only on NumPy.

## Conversion and inference

The converter reads only the original `Dataset/` and does not read `DatasetOfficial/`. It rebuilds the archive, manifest, and annotations from the current directories, and before overwriting it automatically backs up the old files to `DatasetProcessed/Backup_<date>/`:

```bash
conda run -n leaf-env python Tools/Data/RebuildLeafArchive.py
```

A single run writes `LeafPointClouds.npz`, `LeafManifest.json`, `LeafPair.json`, and `LeafEvalAll.json`. `LeafEvalAll.json` has 607 entries in total: 507 single-object descriptions plus the 100 two-way comparisons of the 50 sets in `DatasetOfficial/`. The old script `ConvertLeafDataset.py --all` is still kept, but 2 sources in `LeafPairPlan.json` have been deleted, so running it directly will abort; `BuildLeafEvalAnnotation.py` is no longer the main path.

A `leaf-env` and local main weights already exist. To rebuild the environment or download the weights, see the [upstream instructions](BeyondSingleObject/README.md). Descriptions and comparisons use `checkpoints/multi-3dllm`; no classification weights or training initialization weights are needed.

`leaf-env` currently has transformers 4.57.6, torch 2.8.0, and timm 1.0.30. The model inherits from `LlamaForCausalLM` and handles the KV cache itself: transformers ≥4.36 passes an empty but truthy `Cache` on the first step, so the upstream `if past_key_values:` cuts off the complete prompt and point cloud features; `prepare_inputs_for_generation` in `pointllm_cvpr.py` and `pointllm.py` has been changed to decide by `get_seq_length()`. This is a local patch, upstream does not have it, and it must be kept before re-cloning. The repository does not pin a transformers version, so after upgrading, verify first with `LIMIT=1`.

Model inference first runs one confirming input, and only `LIMIT=0` runs all annotations; use a new output directory to avoid overwriting old results:

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

The reference answers for free-form descriptions are empty, so `exact_match` and `relaxed_match` are not suitable as the accuracy of this experiment. Basic inference does not need an OpenAI API Key, and human evaluation should focus on outline, deformation, comparison direction, and fabricated details.

The local upstream code contains several kinds of modifications: support for shared NPZ array keys; fixes to `prepare_inputs_for_generation` in the two model variants, deciding whether to truncate by the cache's actual token length so that the complete prompt and point cloud features are not lost on the first step; compatibility handling for the `DropPath` import in timm ≥0.9 and the `weights_only` default in torch ≥2.6. These modifications should be saved before updating or re-cloning upstream.

## Prompt check conclusions

24 GPU inference runs were actually completed: 4 input types × 3 prompts × 2 fixed seeds, separately testing the original question wording, a geometry-only wording, and a leaf-background wording; all used the same point clouds and generation parameters, with a token limit of 128. The original 360-run had a limit of 256, so the two cannot be mixed directly as the same condition.

All three prompts fabricated differences in both runs of the same-file control, 6 times in total; adding "this is a leaf" changed the wording but did not prove that the geometric judgment is more accurate. This is a small-scale check, not an error rate over the whole dataset. When comparing, "same" or "uncertain" should be allowed rather than forcing a search for differences.

The point encoder's FPS uses a random starting point, and `temperature=0` does not fix it. The experiment resets the random seed before each input, but the two inputs of the same object may still draw different centers; factors such as numerical nondeterminism have not been ruled out separately, so the cause cannot be attributed to the prompt alone.

Results and parameters are kept in [PromptStudy](DatasetProcessed/Outputs/PromptStudy/); see [Results.csv](DatasetProcessed/Outputs/PromptStudy/Results.csv) and [Method.json](DatasetProcessed/Outputs/PromptStudy/Method.json). To redo the experiment, use:

```bash
# Without --run, only annotations are generated; with --run, the model is loaded. Both replace the corresponding output of this experiment.
conda run -n leaf-env python Tools/Inference/EvaluateLeafPrompts.py --run
```
