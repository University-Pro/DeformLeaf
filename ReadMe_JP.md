> 本ファイルは `readme-translator` サブエージェントが自動生成したものです。手作業で編集せず、変更は `ReadMe.md` に加えてください。
> ソースファイル：`ReadMe.md`（sha256 `22eb2ac16b3719cfaab61b2b07361ba0b399a513d082fecc8f20822a8d9f46ce`、2026-10-22）

# DeformLeaf × Multi-3DLLM

本プロジェクトは葉の三次元データを整理し、Multi-3DLLM が葉の外形と変形を記述する能力を検証する。本ファイルが唯一保守されているプロジェクト説明であり、サードパーティリポジトリのドキュメントは `BeyondSingleObject/` に残す。

## よく使う入口

- [点群と推論結果の比較](Compare/index.html)：左右の点群を回転させ、単体の記述および A→B、B→A の回答を確認する。
- [整理済みサンプルと mask 索引](DatasetOfficial/index.html)：連番 1–50 の対応ファイルを確認する。
- [新旧番号対照](DatasetOfficial/NumberMap.csv)、[未対応マニフェスト](DatasetOfficial/Unmatched.csv)。
- 元の推論：[360 件の結果](DatasetProcessed/Outputs/LeafPairEval/inference.json)、プロンプト実験：[24 件の結果](DatasetProcessed/Outputs/PromptStudy/inference.json)。

## プロジェクト構成

```text
Dataset/                 元データ
DatasetOfficial/         公式構造に合わせて対応付けた 50 セットのサンプル
DatasetProcessed/         点群アーカイブ、アノテーション、検査記録、推論結果
BeyondSingleObject/      サードパーティのモデルコードとローカルの重み
Compare/                 比較用ウェブページ、テンプレート、BuildCompare.py
Tools/Data/              点群の変換・再構築、公式ディレクトリの整理
Tools/Inference/         アノテーション生成、プロンプト実験の実行
Tools/Config/            LeafPairPlan.json ペアリング設定
Tests/                   サンプリング、読み込み、ページデータの関連付け検査
ReadMe.md                本プロジェクトの使用説明
```

`.vscode/` と `.claude/` にはツール設定を残している。ペアリング設定と整理スクリプトはそれぞれ `Tools/Config/LeafPairPlan.json`、`Tools/Data/OrganizeOfficialDataset.py` で管理している。README の翻訳を自動生成するフックは無効化した。

## 元の Dataset の各ディレクトリ

`base` は葉を展平した後の基本外形を表し、`deform` は曲げ・巻き・ねじれの後の三次元状態を表す。著者は多角度撮影から変形した葉を再構築し、基本画像のセグメンテーションマスクから平面メッシュを作成した。[公式データ説明](https://github.com/Yrainy0615/NeuraLeaf#dataset)

| ディレクトリ | 意味 |
| --- | --- |
| `base_img` | 基本状態のカラー葉画像 |
| `base_mask` | 葉領域のマスク、および SDF などの補助データ |
| `base_shape` | 基本の平面 OBJ メッシュ。MTL とテクスチャ画像が付く場合がある |
| `deform_raw` | 名前から比較的元のままの変形三次元データと解釈している |
| `deform_raw_denoise` | 名前からノイズ除去後の変形データと解釈している。メッシュと純粋な点群の両方がある |
| `deform_train` | 公式の学習プログラムが使用する変形データ。現在の 122 個の PLY は実際にはすべて純粋な点群 |
| `deform_train_new` | もう一版の学習データ。具体的な処理の違いは未確認 |
| `deform_raw_new` | 現在は空。具体的な用途は未確認 |
| `base_shape_extra` | 補足の基本メッシュと付随リソース |
| `base_mask_extra` | 補足のマスク、画像、距離場 |
| `maple_extra` | 命名からカエデの補足資料と判断している。内部に画像と三次元のサブディレクトリがある |

`extra` は必ずしも合成データであることを意味せず、`new` も品質がより良いことを証明しない。`sdf` は位置から葉の境界までの距離を表す配列である。Dataset 内に既にあった `output/` は本プロジェクトの初回処理前から存在し、主に過去の距離場の生成物を含むため残している。

2026-10-19 の検査：507 個の三次元ファイル、530 枚の画像、152 個の NPY が読み込めるが、93 個の三次元ファイルが存在しないマテリアルやテクスチャを参照している。公式のファイル単位のマニフェストはないため、公開内容が揃っているかは確認できない。詳細な記録は [DatasetAudit.json](DatasetProcessed/DatasetAudit.json) に残している。

## データ整理とモデル入力

`DatasetOfficial` は名前で対応付けたサブセットであり、公式の完全な配布パッケージを意味せず、葉の同一性と位置合わせもすべて人手で確認したわけではない。各番号は `base_shape/{编号}.obj`、`base_mask/{编号}.png`、および `deform_train/{编号}_deform.ply` または `{编号}.obj` に対応する。計 50 セット：28 個の変形ファイルは純粋な点群、22 個はメッシュ。さらに、同名で寸法が一致する未再計算の任意 SDF が 22 個ある。33 セットは依然としていくつかの色リソースを欠いている。

複数の変形候補は `deform_train → deform_train_new → deform_raw_denoise → deform_raw` の順で選択し、同一ディレクトリ内では `_deform` を優先する。`_base.ply` は変形として扱わない。出所、代替バージョン、チェックサムは [Manifest.json](DatasetOfficial/Manifest.json) に保存している。整理スクリプトは空でない出力先ディレクトリへの上書きを拒否する。

モデルが実際に読むのは **点群配列とテキストの質問** であり、推論時に `Dataset/` へアクセスしない。アノテーション [LeafEvalAll.json](DatasetProcessed/LeafEvalAll.json) は `LeafPointClouds.npz::配列キー` を用いて [LeafPointClouds.npz](DatasetProcessed/LeafPointClouds.npz) 内の配列を参照する。メッシュは三角形の面積でサンプリングし、純粋な点群はランダムに点を抽出する。各葉は `(8192, 6)`、float32 で、6 列は XYZRGB。色は PLY の頂点 RGB または OBJ のテクスチャから取得し、欠損部分は灰色で補う。座標は展平も位置合わせもせず、読み込み時に葉ごとに中心化し最大半径でスケーリングするため、実際の物理寸法は比較できない。

現在のアーカイブは `Dataset/` 配下の 507 個すべてのジオメトリファイル（OBJ 162、PLY 345）を対象とし、圧縮後 47.9 MB、変換失敗は 0 件。ここでの OBJ はすべて三角メッシュである。PLY にはメッシュと純粋な点群の両方があり（`deform_raw_denoise` はメッシュ 41、点群 35、`deform_train` はすべて純粋な点群）。

`base_shape` と `deform_raw_denoise` は一対一に対応する 2 組ではない。現在それぞれ 116 個と 76 個のファイルで、共通する番号は 43 個のみ。正式なペアは `DatasetOfficial/` の 50 セットと [LeafPairPlan.json](Tools/Config/LeafPairPlan.json) にのみ存在する。別に 44 個のファイルが 37 組の「異名同物」（内容が完全に同一。例：`deform_train/12_deform.ply` と `deform_train_new/12_deform.ply`）を構成しており、マニフェストの `DuplicateGroups` に列挙している。

色のカバレッジは限られている。507 個のオブジェクトのうち 392 個に灰色の補填があり、サンプリング点の約 77%（321 万 / 415 万）に元の色がない。主に純粋な点群の変形データに集中している。

**バージョンの関係：**旧 253 点群のアーカイブは当時の基本 OBJ 174 個とノイズ除去済み PLY 79 個から生成されたもので、そのうち 126 個の出所パスは現在存在しない。新しいアーカイブは現在のディレクトリから再構築しており、両者で重複するキーは 127 個のみ。旧 360 件の結果を新しいアーカイブのテスト結果とみなすことはできず、旧ファイルは `DatasetProcessed/Backup_20261020/` に残している。

## 比較ページ

[Compare/index.html](Compare/index.html) を開く。ページには現在の `DatasetOfficial` の 50 セットのペア済みサンプルのみが含まれる：100 個の点群、200 件の回答（単体記述 100 件 + A→B / B→A の比較 100 件）で、過去の結果はもはや混入しない。左右にそれぞれ単体記述を表示し、下方に双方向の比較を表示する。

ページは中国語・日本語・英語の 3 種類の表示言語に対応する（右上で切り替え、選択はブラウザのローカルに保存される）。モデルの回答は英語の原文のままで、自動翻訳も採点もしない。サンプル一覧は番号をクリックして移動でき、検索、左右の交換、連動または独立の回転・ズーム、視点と RGB の切り替え、回答の非表示、および `←`/`→`、`S`、`1`/`2`/`3`、`R`、`H` のショートカットに対応する。各単体は 8192 点すべてを表示する。

ビルド時はアーカイブキーで回答を厳密に関連付ける。参照が欠けている回答はスキップして件数を数え、過去の結果を流用しない。ブラウザは WebGL と DecompressionStream に対応している必要があり、ローカルの HTML は直接開ける。

プロジェクトのルートで実行する：

```bash
conda run -n leaf-env python Compare/BuildCompare.py
conda run -n leaf-env python Tests/TestCompare.py
```

ビルドは `Compare/index.html` と `BuildReport.json` のみを更新し、モデルは実行しない。既定では `DatasetProcessed/Outputs/OfficialEval/inference.json` を読み込み、生成は NumPy のみに依存する。

## 変換と推論

変換スクリプトは元の `Dataset/` のみを読み、`DatasetOfficial/` は読まない。現在のディレクトリからアーカイブ、マニフェスト、アノテーションを再構築し、上書き前に旧ファイルを自動で `DatasetProcessed/Backup_<日付>/` にバックアップする：

```bash
conda run -n leaf-env python Tools/Data/RebuildLeafArchive.py
```

1 回の実行で `LeafPointClouds.npz`、`LeafManifest.json`、`LeafPair.json`、`LeafEvalAll.json` を書き出す。`LeafEvalAll.json` は全 607 件：単体記述 507 件に、`DatasetOfficial/` の 50 セット分の双方向比較 100 件を加えたもの。旧スクリプト `ConvertLeafDataset.py --all` も残しているが、`LeafPairPlan.json` の 2 つの出所が削除済みのため、そのまま実行すると中断する。`BuildLeafEvalAnnotation.py` は主要な経路ではなくなった。

`leaf-env` とローカルの主重みは既にある。環境を再構築する場合や重みをダウンロードする場合は [アップストリームの説明](BeyondSingleObject/README.md) を参照。記述と比較に用いるのは `checkpoints/multi-3dllm` で、分類用の重みや学習初期化用の重みは不要。

`leaf-env` は現在 transformers 4.57.6、torch 2.8.0、timm 1.0.30。モデルは `LlamaForCausalLM` を継承し KV cache を自前で扱う。transformers ≥4.36 は最初のステップで空だが真と評価される `Cache` を渡すため、アップストリームの `if past_key_values:` がプロンプト全体と点群特徴を切り捨ててしまう。`pointllm_cvpr.py`、`pointllm.py` の `prepare_inputs_for_generation` は `get_seq_length()` で判定するよう変更した。これはローカルのパッチでありアップストリームには存在しないため、再クローン前に必ず残す必要がある。リポジトリは transformers のバージョンを固定していないので、アップグレード後はまず `LIMIT=1` で検証する。

モデル推論ではまず 1 件の確認用入力を実行し、`LIMIT=0` でのみすべてのアノテーションを実行する。新しい出力ディレクトリを使い、旧結果の上書きを避ける：

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

自由記述の参照回答は空であるため、`exact_match`、`relaxed_match` を本実験の正解率として扱うのは適切でない。基本的な推論に OpenAI API Key は不要で、人手評価では輪郭、変形、比較の方向、架空の細部に注目すべきである。

ローカルのアップストリームコードには複数種類の変更がある。共有 NPZ 配列キーの対応、2 つのモデル変体の `prepare_inputs_for_generation` をキャッシュの実際のトークン長で切り捨てを判定するよう修正し、最初のステップでプロンプト全体と点群特徴が失われるのを避ける、timm ≥0.9 の `DropPath` インポートと torch ≥2.6 の `weights_only` 既定値への互換処理。アップストリームを更新または再クローンする前にこれらの変更を保存すべきである。

## プロンプト検査の結論

4 種の入力 × 3 種のプロンプト × 2 つの固定シードで 24 件の GPU 推論を実際に完了し、それぞれ元の問い方、幾何のみの問い方、葉の背景を添えた問い方を試した。いずれも同じ点群と生成パラメータを用い、トークン上限は 128。元の 360 件の実行は上限 256 であり、同一条件として直接混在させることはできない。

3 種類のプロンプトはいずれも同一ファイル対照の 2 回の実行で差異を捏造し、計 6 回に達した。「これは葉である」を加えると表現は変わったが、幾何判断がより正確になった証明にはならない。これは小規模な検査であり、全データセットの誤り率ではない。比較の際は「同じ」や「不明」を許容すべきで、無理に差異を探すべきではない。

点エンコーダの FPS はランダムな開始点を用い、`temperature=0` でも固定されない。実験では各入力の前に乱数シードをリセットしているが、同一物体の 2 つの入力がそれぞれ異なる中心を引く可能性は残る。数値的な非決定性などの要因は個別に排除しておらず、prompt のみに帰属させることはできない。

結果とパラメータは [PromptStudy](DatasetProcessed/Outputs/PromptStudy/) に残しており、[Results.csv](DatasetProcessed/Outputs/PromptStudy/Results.csv) と [Method.json](DatasetProcessed/Outputs/PromptStudy/Method.json) を参照できる。実験をやり直すには次を使う：

```bash
# --run なしではアノテーションの生成のみ、--run ありではモデルを読み込む。いずれも本実験の対応する出力を置き換える。
conda run -n leaf-env python Tools/Inference/EvaluateLeafPrompts.py --run
```
