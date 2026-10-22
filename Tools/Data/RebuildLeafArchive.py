"""按当前 Dataset 目录重建点云归档与配套标注。

与 ConvertLeafDataset.py 的区别：
- 收录 Dataset 下全部 .obj/.ply（递归），不再只看 base_shape 与 deform_raw_denoise；
- 单个文件失败时记录并继续，不中断整批；
- 额外写出内容重复分组，便于区分“同名不同物”与“异名同物”；
- 生成单片描述标注，以及 DatasetOfficial/Manifest.json 中 50 套配对的 A→B / B→A 标注。

默认覆盖 DatasetProcessed/LeafPointClouds.npz、LeafManifest.json、LeafPair.json、
LeafEvalAll.json；覆盖前把旧文件复制到 DatasetProcessed/Backup_<YYYYMMDD>/。

用法（项目根目录）：
    conda run -n leaf-env python Tools/Data/RebuildLeafArchive.py
    conda run -n leaf-env python Tools/Data/RebuildLeafArchive.py --limit 3 --no-write
"""

import argparse
import hashlib
import json
import shutil
import sys
import traceback
from collections import OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

Root = Path(__file__).resolve().parents[2]
OutputRoot = Root / "DatasetProcessed"
sys.path.insert(0, str(Root))
from Tools.Data import ConvertLeafDataset as Converter  # noqa: E402

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


def GeometrySources():
    return sorted(
        Path(Item)
        for Item in (Root / "Dataset").rglob("*")
        if Item.is_file() and Item.suffix.lower() in (".obj", ".ply")
    )


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


def NameStem(SourcePath):
    return Path(SourcePath).stem


def Backup(Stamp):
    Target = OutputRoot / ("Backup_%s" % Stamp)
    Existing = [Name for Name in BackupFiles if (OutputRoot / Name).exists()]
    if not Existing:
        return None
    Target.mkdir(parents=True, exist_ok=True)
    for Name in Existing:
        Destination = Target / Name
        if Destination.exists():
            raise SystemExit("[错误] 备份目标已存在，拒绝覆盖：%s" % Destination)
        shutil.copy2(OutputRoot / Name, Destination)
    return Target


def BuildSamples(Records, OfficialManifest, Skipped):
    Samples = []

    # 1) 单片描述：归档里的每个点云各一条。
    for Record in Records:
        Samples.append(
            OrderedDict(
                [
                    ("id", "LeafSingle%s" % Record["Id"]),
                    ("task_type", "single"),
                    ("object_ids", [ArchiveReference(Record)]),
                    ("conversations", Conversation(SinglePrompt)),
                    ("metadata", CommonMetadata(
                        [Record], "Single", "SingleObjectDescription",
                        "NotApplicable", "", NameStem(Record["Source"]),
                    )),
                ]
            )
        )

    # 2) DatasetOfficial 中已配套的 50 套：A→B 与 B→A 各一条。
    BySource = OrderedDict((Record["Source"], Record) for Record in Records)
    PairCount = 0
    for Sample in OfficialManifest.get("Samples", []):
        Base = BySource.get(Sample["Sources"]["Base"])
        Deform = BySource.get(Sample["Sources"]["Deform"])
        if Base is None or Deform is None:
            Missing = [
                Key for Key, Record in (("Base", Base), ("Deform", Deform)) if Record is None
            ]
            Skipped.append({"OfficialId": Sample.get("Id"), "Missing": Missing})
            continue
        PairCount += 1
        for Order, First, Second in (("AB", Base, Deform), ("BA", Deform, Base)):
            Samples.append(
                OrderedDict(
                    [
                        ("id", "LeafOfficial%s%s" % (Sample["Id"], Order)),
                        ("task_type", "comparative"),
                        ("object_ids", [ArchiveReference(First), ArchiveReference(Second)]),
                        ("conversations", Conversation(PairPrompt)),
                        ("metadata", CommonMetadata(
                            [First, Second], "DatasetOfficial50", "ShapeComparison",
                            Sample.get("PairingStatus", "FilenameMatched_NotManuallyVerified"),
                            Order, str(Sample["Id"]),
                        )),
                    ]
                )
            )
    return Samples, PairCount


def WriteJson(Path, Data):
    Temporary = Path.with_suffix(Path.suffix + ".tmp")
    Temporary.write_text(json.dumps(Data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Temporary.replace(Path)


def Main():
    Parser = argparse.ArgumentParser(description="按当前 Dataset 重建点云归档")
    Parser.add_argument("--point-count", type=int, default=8192)
    Parser.add_argument("--seed", type=int, default=20261017)
    Parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个文件，用于试跑")
    Parser.add_argument("--no-write", action="store_true", help="只转换，不写任何文件")
    Parser.add_argument("--output", type=Path, default=OutputRoot / ArchiveName)
    Args = Parser.parse_args()

    Sources = GeometrySources()
    if Args.limit:
        Sources = Sources[: Args.limit]
    print("[INFO] 待转换 %d 个几何文件" % len(Sources), flush=True)

    Converted, Failed = [], []
    for Index, Source in enumerate(Sources, 1):
        Relative = Source.relative_to(Root).as_posix()
        try:
            Points, Record = Converter.Convert(Relative, Args.point_count, Args.seed)
            Converted.append((Points, Record))
            print("[%d/%d] OK   %s" % (Index, len(Sources), Relative), flush=True)
        except Exception as Error:
            Failed.append({
                "Source": Relative,
                "Error": "%s: %s" % (type(Error).__name__, Error),
                "Traceback": traceback.format_exc(limit=2),
            })
            print("[%d/%d] FAIL %s -> %s" % (Index, len(Sources), Relative, Error), flush=True)

    Records = [Record for _, Record in Converted]
    Duplicates = defaultdict(list)
    for Record in Records:
        Duplicates[Record["SourceSha256"]].append(Record["Source"])
    DuplicateGroups = [sorted(Group) for Group in Duplicates.values() if len(Group) > 1]

    Official = json.loads((Root / "DatasetOfficial" / "Manifest.json").read_text(encoding="utf-8"))
    SkippedOfficial = []
    Samples, PairCount = BuildSamples(Records, Official, SkippedOfficial)

    Manifest = OrderedDict(
        [
            ("PointCount", Args.point_count),
            ("Seed", Args.seed),
            ("NumpyVersion", np.__version__),
            ("GeneratedAt", datetime.now().isoformat(timespec="seconds")),
            ("Scope", "Dataset/**/*.{obj,ply}"),
            ("Output", Args.output.relative_to(Root).as_posix()),
            ("RecordCount", len(Records)),
            ("FailedCount", len(Failed)),
            ("DuplicateGroups", DuplicateGroups),
            ("Failed", Failed),
            ("Records", Records),
        ]
    )
    Summary = OrderedDict(
        [
            ("geometry_files", len(Sources)),
            ("converted", len(Records)),
            ("failed", len(Failed)),
            ("duplicate_groups", len(DuplicateGroups)),
            ("official_pairs_used", PairCount),
            ("official_pairs_skipped", SkippedOfficial),
            ("samples", len(Samples)),
        ]
    )
    print("[SUMMARY] %s" % json.dumps(Summary, ensure_ascii=False), flush=True)

    if Args.no_write:
        print("[INFO] --no-write：未写入任何文件", flush=True)
        return

    Stamp = datetime.now().strftime("%Y%m%d")
    BackupDir = Backup(Stamp)
    if BackupDir is not None:
        print("[INFO] 旧文件已备份到 %s" % BackupDir.relative_to(Root), flush=True)

    if Args.output == OutputRoot / ArchiveName:
        Temporary = OutputRoot / (ArchiveName + ".tmp.npz")
        np.savez_compressed(Temporary, **{Record["ArchiveKey"]: Points for Points, Record in Converted})
        Temporary.replace(Args.output)
    else:
        np.savez_compressed(Args.output, **{Record["ArchiveKey"]: Points for Points, Record in Converted})
    print("[INFO] 已写出 %s" % Args.output.relative_to(Root), flush=True)

    WriteJson(OutputRoot / "LeafManifest.json", Manifest)
    # LeafPair.json 只放配对样本；LeafEvalAll.json 放单片 + 配对，供评测脚本读取。
    Pairs = [Sample for Sample in Samples if Sample["task_type"] == "comparative"]
    WriteJson(OutputRoot / "LeafPair.json", Pairs)
    WriteJson(OutputRoot / "LeafEvalAll.json", Samples)
    print("[INFO] 已写出 LeafManifest.json / LeafPair.json / LeafEvalAll.json", flush=True)


if __name__ == "__main__":
    Main()