"""只用 DatasetOfficial 的 50 套重建点云归档与配套标注。

与 RebuildLeafArchive.py 的区别：
- 只收 DatasetOfficial/Manifest.json 中 50 套的 BaseMesh 与 Deform，共 100 个对象；
- 几何从 DatasetOfficial 的整理副本读取（纹理已重定位），
  但归档键与采样种子沿用原始 Dataset 来源路径，保证与全量归档里的同名对象一致；
- 生成 100 条单片描述 + 100 条比较（50 套 × AB/BA），共 200 条。

默认覆盖 DatasetProcessed/LeafPointClouds.npz、LeafManifest.json、LeafPair.json、
LeafEvalAll.json；覆盖前把旧文件复制到 DatasetProcessed/Backup_<时间戳>/。

用法（项目根目录）：
    conda run -n leaf-env python Tools/Data/BuildOfficialArchive.py
    conda run -n leaf-env python Tools/Data/BuildOfficialArchive.py --limit 2 --no-write
"""

import argparse
import hashlib
import json
import shutil
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import numpy as np

Root = Path(__file__).resolve().parents[2]
OutputRoot = Root / "DatasetProcessed"
sys.path.insert(0, str(Root))
from Tools.Data.ConvertLeafDataset import LoadGeometry, SampleGeometry  # noqa: E402

SinglePrompt = (
    "<point>\n"
    "Describe the geometry of the object. Focus on the outline, elongation, bending, "
    "curling, and twisting. Avoid unsupported claims about species, health, or "
    "surface finish."
)
PairPrompt = (
    "<point> <point>\n"
    "Describe the geometry of Object 1 and Object 2, then compare their main shape "
    "differences. Focus on the outline, elongation, bending, curling, and twisting. "
    "Avoid unsupported claims about species, health, or surface finish."
)

ArchiveName = "LeafPointClouds.npz"
BackupFiles = ["LeafPointClouds.npz", "LeafManifest.json", "LeafPair.json", "LeafEvalAll.json"]


def Digest(Path):
    return hashlib.sha256(Path.read_bytes()).hexdigest()


def Identifier(Source):
    return "Leaf" + hashlib.sha256(Source.encode()).hexdigest()[:16]


def Conversation(Prompt):
    return [
        OrderedDict([("from", "human"), ("value", Prompt)]),
        OrderedDict([("from", "gpt"), ("value", "")]),
    ]


def CommonMetadata(Records, Subset, PairKind, PairingStatus, Order, NameStem):
    return OrderedDict(
        [
            ("source_paths", [Record["Source"] for Record in Records]),
            ("archive_keys", [Record["ArchiveKey"] for Record in Records]),
            ("subset", Subset),
            ("pair_kind", PairKind),
            ("pairing_status", PairingStatus),
            ("order", Order),
            ("reference_status", "Unlabeled"),
            ("name_stem", NameStem),
            ("color_policy", "|".join(sorted({R.get("ColorPolicy", "") for R in Records}))),
            ("gray_fallback_points", [R.get("GrayFallbackPoints") for R in Records]),
        ]
    )


def ArchiveReference(Record):
    return "%s::%s" % (ArchiveName, Record["ArchiveKey"])


def Backup(Stamp):
    Target = OutputRoot / ("Backup_%s" % Stamp)
    Existing = [Name for Name in BackupFiles if (OutputRoot / Name).exists()]
    if not Existing:
        return None
    Target.mkdir(parents=True, exist_ok=False)
    for Name in Existing:
        shutil.copy2(OutputRoot / Name, Target / Name)
    return Target


def WriteJson(Path, Data):
    Temporary = Path.with_suffix(Path.suffix + ".tmp")
    Temporary.write_text(json.dumps(Data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Temporary.replace(Path)


def Main():
    Parser = argparse.ArgumentParser(description="只用 DatasetOfficial 的 50 套重建归档")
    Parser.add_argument("--point-count", type=int, default=8192)
    Parser.add_argument("--seed", type=int, default=20261017)
    Parser.add_argument("--limit", type=int, default=0, help="只处理前 N 套，用于试跑")
    Parser.add_argument("--no-write", action="store_true", help="只转换，不写任何文件")
    Parser.add_argument("--output", type=Path, default=OutputRoot / ArchiveName)
    Args = Parser.parse_args()

    Official = json.loads((Root / "DatasetOfficial" / "Manifest.json").read_text(encoding="utf-8"))
    Samples = Official.get("Samples", [])
    if Args.limit:
        Samples = Samples[: Args.limit]

    Converted = []
    Failed = []
    SeenKeys = {}
    for Sample in Samples:
        for Role, Key in (("Base", "Base"), ("Deform", "Deform")):
            Source = Sample["Sources"][Key]
            Organized = Sample["BaseMesh"] if Role == "Base" else Sample["Deform"]
            KeyValue = Identifier(Source)
            if KeyValue in SeenKeys:
                Failed.append({
                    "OfficialId": Sample.get("Id"),
                    "Role": Role,
                    "Source": Source,
                    "Error": "Duplicate archive key with %s" % SeenKeys[KeyValue],
                })
                continue
            SeenKeys[KeyValue] = "%s/%s" % (Sample.get("Id"), Role)
            try:
                CurrentDigest = Digest(Root / Source)
                StoredDigest = Sample["SourceSha256"][Key]
                SeedText = f"{Args.seed}:{Source}:{CurrentDigest}"
                RandomSeed = int.from_bytes(
                    hashlib.sha256(SeedText.encode()).digest()[:8], "little"
                )
                Vertices, Faces, Attributes = LoadGeometry(Root / Organized)
                Points, Details = SampleGeometry(
                    Vertices, Faces, Args.point_count,
                    np.random.default_rng(RandomSeed), Attributes,
                )
                Record = OrderedDict(
                    [
                        ("Id", KeyValue),
                        ("ArchiveKey", KeyValue),
                        ("Output", Args.output.relative_to(Root).as_posix()),
                        ("Source", Source),
                        ("File", Organized),
                        ("OfficialId", Sample.get("Id")),
                        ("Role", Role),
                        ("SourceSha256", CurrentDigest),
                        ("StoredSourceSha256", StoredDigest),
                        ("SourceModifiedSinceOfficial", CurrentDigest != StoredDigest),
                        ("Shape", list(Points.shape)),
                        ("Dtype", str(Points.dtype)),
                        ("Seed", RandomSeed),
                        ("PairingStatus", Sample.get("PairingStatus", "")),
                        ("ColorPolicy", "SourceRgbOrTextureWithGrayFallback"),
                        ("MissingColorResources", Attributes.get("MissingColorResources", [])),
                    ]
                )
                Record.update(Details)
                Converted.append((Points.astype("<f4", copy=False), Record))
                print("[OK]   %s %s -> %s" % (Sample.get("Id"), Role, Source), flush=True)
            except Exception as Error:
                Failed.append({
                    "OfficialId": Sample.get("Id"),
                    "Role": Role,
                    "Source": Source,
                    "Error": "%s: %s" % (type(Error).__name__, Error),
                })
                print("[FAIL] %s %s -> %s" % (Sample.get("Id"), Role, Error), flush=True)

    Records = [Record for _, Record in Converted]
    ByOfficial = {(R["OfficialId"], R["Role"]): R for R in Records}

    Samples_out = []
    for Record in Records:
        Samples_out.append(
            OrderedDict(
                [
                    ("id", "LeafSingle%s" % Record["Id"]),
                    ("task_type", "single"),
                    ("object_ids", [ArchiveReference(Record)]),
                    ("conversations", Conversation(SinglePrompt)),
                    ("metadata", CommonMetadata(
                        [Record], "DatasetOfficial50", "SingleObjectDescription",
                        Record.get("PairingStatus", ""), "",
                        "%s-%s" % (Record["OfficialId"], Record["Role"]),
                    )),
                ]
            )
        )

    PairCount = 0
    for Sample in Samples:
        Base = ByOfficial.get((Sample.get("Id"), "Base"))
        Deform = ByOfficial.get((Sample.get("Id"), "Deform"))
        if Base is None or Deform is None:
            continue
        PairCount += 1
        for Order, First, Second in (("AB", Base, Deform), ("BA", Deform, Base)):
            Samples_out.append(
                OrderedDict(
                    [
                        ("id", "LeafOfficial%s%s" % (Sample.get("Id"), Order)),
                        ("task_type", "comparative"),
                        ("object_ids", [ArchiveReference(First), ArchiveReference(Second)]),
                        ("conversations", Conversation(PairPrompt)),
                        ("metadata", CommonMetadata(
                            [First, Second], "DatasetOfficial50", "ShapeComparison",
                            Sample.get("PairingStatus", ""), Order, str(Sample.get("Id")),
                        )),
                    ]
                )
            )

    Manifest = OrderedDict(
        [
            ("PointCount", Args.point_count),
            ("Seed", Args.seed),
            ("NumpyVersion", np.__version__),
            ("GeneratedAt", datetime.now().isoformat(timespec="seconds")),
            ("Scope", "DatasetOfficial/Manifest.json (50 sets, 100 objects)"),
            ("Output", Args.output.relative_to(Root).as_posix()),
            ("RecordCount", len(Records)),
            ("FailedCount", len(Failed)),
            ("OfficialPairs", PairCount),
            ("Failed", Failed),
            ("Records", Records),
        ]
    )

    # 覆盖前先和旧归档比对，确认这 100 个键的数组没有变化。
    Equal = Missing = Different = 0
    OldPath = OutputRoot / ArchiveName
    if OldPath.exists() and not Args.no_write:
        with np.load(OldPath, allow_pickle=False) as Old:
            for Points, Record in Converted:
                if Record["ArchiveKey"] not in Old:
                    Missing += 1
                elif np.array_equal(Old[Record["ArchiveKey"]], Points):
                    Equal += 1
                else:
                    Different += 1

    Summary = OrderedDict(
        [
            ("official_sets", len(Samples)),
            ("objects", len(Records)),
            ("failed", len(Failed)),
            ("singles", len(Records)),
            ("pair_groups", PairCount),
            ("comparative_samples", PairCount * 2),
            ("total_samples", len(Samples_out)),
            ("same_as_previous_archive", Equal),
            ("new_keys", Missing),
            ("changed_keys", Different),
            ("gray_points", sum(R.get("GrayFallbackPoints", 0) for R in Records)),
            ("total_points", len(Records) * Args.point_count),
        ]
    )
    print("[SUMMARY] %s" % json.dumps(Summary, ensure_ascii=False), flush=True)

    if Args.no_write:
        print("[INFO] --no-write：未写入任何文件", flush=True)
        return

    Stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    BackupDir = Backup(Stamp)
    if BackupDir is not None:
        print("[INFO] 旧文件已备份到 %s" % BackupDir.relative_to(Root), flush=True)

    Temporary = Args.output.with_suffix(Args.output.suffix + ".tmp.npz")
    np.savez_compressed(Temporary, **{Record["ArchiveKey"]: Points for Points, Record in Converted})
    Temporary.replace(Args.output)
    print("[INFO] 已写出 %s" % Args.output.relative_to(Root), flush=True)

    WriteJson(OutputRoot / "LeafManifest.json", Manifest)
    Pairs = [Sample for Sample in Samples_out if Sample["task_type"] == "comparative"]
    WriteJson(OutputRoot / "LeafPair.json", Pairs)
    WriteJson(OutputRoot / "LeafEvalAll.json", Samples_out)
    print("[INFO] 已写出 LeafManifest.json / LeafPair.json / LeafEvalAll.json", flush=True)


if __name__ == "__main__":
    Main()