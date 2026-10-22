"""生成全量叶片评测标注：单片描述 + 同名配对比较 + 同文件对照。

输入是 DatasetProcessed/LeafManifest.json（点云来源与归档键）与 Tools/Config/LeafPairPlan.json
（人工维护的配对计划）。输出是 DatasetProcessed/LeafEvalAll.json，供
BeyondSingleObject/pointllm/eval/cvpr/eval_cvpr_patch.py 使用。

标注文件由本脚本生成，不要手工修改；计划有变化时重新运行本脚本。

用法（在项目根目录执行）：
    conda run -n leaf-env python Tools/Inference/BuildLeafEvalAnnotation.py
"""

import argparse
import json
import os
from collections import OrderedDict

DefaultManifest = "DatasetProcessed/LeafManifest.json"
DefaultPlan = "Tools/Config/LeafPairPlan.json"
DefaultOutput = "DatasetProcessed/LeafEvalAll.json"

# 与 LeafPair.json 保持同一套问法，仅把 material 换成 surface finish：
# 任务识别用的是子串匹配，"material" 里的 "mate" 会被误判为 Shape Mating。
PairPrompt = (
    "<point> <point>\n"
    "Describe the geometry of Object 1 and Object 2, then compare their main shape "
    "differences. Focus on the outline, elongation, bending, curling, and twisting. "
    "Avoid unsupported claims about species, health, or surface finish."
)

SinglePrompt = (
    "<point>\n"
    "Describe the geometry of the object. Focus on the outline, elongation, bending, "
    "curling, and twisting. Avoid unsupported claims about species, health, or "
    "surface finish."
)


def LoadManifest(ManifestPath):
    """返回 {ArchiveKey: Record} 与 {SourcePath: Record} 两张索引。"""
    with open(ManifestPath, "r", encoding="utf-8") as Handle:
        Manifest = json.load(Handle, object_pairs_hook=OrderedDict)

    ByKey = OrderedDict()
    BySource = OrderedDict()
    for Record in Manifest["Records"]:
        ByKey[Record["ArchiveKey"]] = Record
        BySource[Record["Source"]] = Record
    return Manifest, ByKey, BySource


def ArchiveReference(Record):
    """模型标注里引用压缩归档中单个数组的写法：<归档文件名>::<数组键>。"""
    ArchiveName = os.path.basename(Record["Output"])
    return "%s::%s" % (ArchiveName, Record["ArchiveKey"])


def SourceGroup(SourcePath):
    Parts = SourcePath.split("/")
    return Parts[1] if len(Parts) > 1 else ""


def NameStem(SourcePath):
    return os.path.basename(SourcePath).rsplit(".", 1)[0]


def CommonMetadata(Records, Subset, PairKind, PairingStatus, Order, NameStemValue):
    ColorPolicies = []
    GrayPoints = []
    for Record in Records:
        Policy = Record.get("ColorPolicy", "")
        if Policy not in ColorPolicies:
            ColorPolicies.append(Policy)
        GrayPoints.append(Record.get("GrayFallbackPoints", None))

    return OrderedDict(
        [
            ("source_paths", [Record["Source"] for Record in Records]),
            ("archive_keys", [Record["ArchiveKey"] for Record in Records]),
            ("subset", Subset),
            ("pair_kind", PairKind),
            ("pairing_status", PairingStatus),
            ("order", Order),
            ("reference_status", "Unlabeled"),
            ("name_stem", NameStemValue),
            ("color_policy", "|".join(Policy for Policy in ColorPolicies if Policy)),
            ("gray_fallback_points", GrayPoints),
        ]
    )


def Conversation(Prompt):
    return [
        OrderedDict([("from", "human"), ("value", Prompt)]),
        OrderedDict([("from", "gpt"), ("value", "")]),
    ]


def BuildSamples(Records, Plan, ManifestBySource):
    Samples = []

    # 1) 单片描述：清单里的每一片叶子各一条。
    for Record in Records:
        Samples.append(
            OrderedDict(
                [
                    ("id", "LeafSingle%s" % Record["Id"]),
                    ("task_type", "single"),
                    ("object_ids", [ArchiveReference(Record)]),
                    ("conversations", Conversation(SinglePrompt)),
                    ("metadata", CommonMetadata(
                        [Record], "Single", "SingleObjectDescription", "NotApplicable", "", "",
                    )),
                ]
            )
        )

    # 2) 同名配对：base_shape 与 deform_raw_denoise 中名称相同的两个点云，双向各一条。
    ByName = OrderedDict()
    for Record in Records:
        Stem = NameStem(Record["Source"])
        Group = SourceGroup(Record["Source"])
        ByName.setdefault(Stem, {})[Group] = Record

    PairCount = 0
    for Stem in sorted(ByName.keys(), key=lambda Item: (len(Item), Item)):
        Groups = ByName[Stem]
        Base = Groups.get("base_shape")
        Deform = Groups.get("deform_raw_denoise")
        if Base is None or Deform is None:
            continue
        PairCount += 1
        for Order, First, Second in (("AB", Base, Deform), ("BA", Deform, Base)):
            Samples.append(
                OrderedDict(
                    [
                        ("id", "LeafPair%s%s" % (Stem, Order)),
                        ("task_type", "comparative"),
                        ("object_ids", [ArchiveReference(First), ArchiveReference(Second)]),
                        ("conversations", Conversation(PairPrompt)),
                        ("metadata", CommonMetadata(
                            [First, Second], "PairSameName", "ShapeComparison",
                            "Unverified", Order, Stem,
                        )),
                    ]
                )
            )

    # 3) 同文件对照：按配对计划里显式标注的 SameObjectControl 生成。
    ControlCount = 0
    for Entry in Plan:
        if Entry.get("Kind") != "SameObjectControl":
            continue
        First = PlanSourceRecord(Entry["SourceA"], ManifestBySource)
        Second = PlanSourceRecord(Entry["SourceB"], ManifestBySource)
        ControlCount += 1
        Samples.append(
            OrderedDict(
                [
                    ("id", "%sAB" % Entry["Id"]),
                    ("task_type", "comparative"),
                    ("object_ids", [ArchiveReference(First), ArchiveReference(Second)]),
                    ("conversations", Conversation(PairPrompt)),
                    ("metadata", CommonMetadata(
                        [First, Second], "SameObjectControl", "SameObjectControl",
                        Entry.get("PairingStatus", "VerifiedSameFile"), "AB",
                        NameStem(Entry["SourceA"]),
                    )),
                ]
            )
        )
        if Entry.get("IncludeReverse"):
            Samples.append(
                OrderedDict(
                    [
                        ("id", "%sBA" % Entry["Id"]),
                        ("task_type", "comparative"),
                        ("object_ids", [ArchiveReference(Second), ArchiveReference(First)]),
                        ("conversations", Conversation(PairPrompt)),
                        ("metadata", CommonMetadata(
                            [Second, First], "SameObjectControl", "SameObjectControl",
                            Entry.get("PairingStatus", "VerifiedSameFile"), "BA",
                            NameStem(Entry["SourceA"]),
                        )),
                    ]
                )
            )

    return Samples, PairCount, ControlCount


def PlanSourceRecord(SourcePath, ManifestBySource):
    """配对计划里的来源路径取自清单，未收录则报错，避免写出指向不存在点云的标注。"""
    Record = ManifestBySource.get(SourcePath)
    if Record is None:
        raise SystemExit("[错误] 配对计划引用了清单中不存在的来源：%s" % SourcePath)
    return Record


def Main():
    Parser = argparse.ArgumentParser(description="生成全量叶片评测标注")
    Parser.add_argument("--manifest", default=DefaultManifest)
    Parser.add_argument("--plan", default=DefaultPlan)
    Parser.add_argument("--out", default=DefaultOutput)
    Args = Parser.parse_args()

    Manifest, ManifestByKey, ManifestBySource = LoadManifest(Args.manifest)
    with open(Args.plan, "r", encoding="utf-8") as Handle:
        Plan = json.load(Handle)

    Samples, PairCount, ControlCount = BuildSamples(
        Manifest["Records"], Plan, ManifestBySource
    )

    with open(Args.out, "w", encoding="utf-8") as Handle:
        json.dump(Samples, Handle, ensure_ascii=False, indent=2)
        Handle.write("\n")

    SingleCount = len(Manifest["Records"])
    print("清单点云数: %d" % SingleCount)
    print("同名配对组数: %d → 双向 %d 条" % (PairCount, PairCount * 2))
    print("同文件对照条数: %d" % ControlCount)
    print("合计样本: %d" % len(Samples))
    print("已写出: %s" % Args.out)


if __name__ == "__main__":
    Main()