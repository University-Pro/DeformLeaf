"""Build a self-contained comparison page for the 50 DatasetOfficial pairs.

Run: conda run -n leaf-env python Compare/BuildCompare.py

The page contains exactly the current official evaluation: 50 paired samples,
100 point clouds and the 200 saved answers (100 single descriptions plus 100
A->B / B->A comparisons). No model inference is performed here. Every cloud is
read from the shared archive and every answer is associated by exact archive
reference, so stale or historical results can never leak into the page.
"""
import argparse as Argparse
import base64 as Base64
import gzip as Gzip
import hashlib as Hashlib
import json as Json
import os as Os
from pathlib import Path

import numpy as Numpy


Root = Path(__file__).resolve().parents[1]
Folder = Path(__file__).resolve().parent


def ParseArgs():
    Parser = Argparse.ArgumentParser(description="Build the DatasetOfficial comparison page")
    Parser.add_argument("--manifest", type=Path,
                        default=Root / "DatasetProcessed/LeafManifest.json")
    Parser.add_argument("--archive", type=Path,
                        default=Root / "DatasetProcessed/LeafPointClouds.npz")
    Parser.add_argument("--official", type=Path,
                        default=Root / "DatasetOfficial/Manifest.json")
    Parser.add_argument("--inference", type=Path,
                        default=Root / "DatasetProcessed/Outputs/OfficialEval/inference.json")
    Parser.add_argument("--output", type=Path, default=Folder / "index.html")
    Parser.add_argument("--report", type=Path, default=Folder / "BuildReport.json")
    return Parser.parse_args()


def Main():
    Args = ParseArgs()
    Manifest = Json.loads(Args.manifest.read_text(encoding="utf-8"))
    Official = Json.loads(Args.official.read_text(encoding="utf-8"))
    Inference = Json.loads(Args.inference.read_text(encoding="utf-8"))
    Archive = Numpy.load(Args.archive, allow_pickle=False)
    ArchiveKeys = set(Archive.keys())
    ArchiveBySource = {Entry["Source"]: Entry for Entry in Manifest["Records"]}

    # Keep only answers whose two / one references still exist in this archive.
    Results, SkippedPredictions = [], 0
    for Index, Entry in enumerate(Inference["results"]):
        References = Entry["object_ids"]
        if any(Reference.split("::", 1)[1] not in ArchiveKeys for Reference in References):
            SkippedPredictions += 1
            continue
        Results.append({"Id": len(Results), "SourceIndex": Index, "References": References,
                        "Question": Entry["question"],
                        "Prediction": Entry.get("prediction", ""),
                        "Reasoning": Entry.get("reasoning"),
                        "Order": Entry.get("metadata", {}).get("order", ""),
                        "PairKind": Entry.get("metadata", {}).get("pair_kind", ""),
                        "PairingStatus": Entry.get("metadata", {}).get("pairing_status", ""),
                        "SampleIndex": Entry.get("sample_index", Index)})

    Singles = {}
    for Entry in Results:
        if len(Entry["References"]) == 1:
            Singles.setdefault(Entry["References"][0], []).append(Entry["Id"])

    Samples = sorted(Official["Samples"], key=lambda Entry: int(Entry["Id"]))
    Arrays, Clouds, Cases = [], [], []
    MissingReferences = 0
    for Sample in Samples:
        Indices = []
        for Role, Key in [("Base", "Base"), ("Deform", "Deform")]:
            Source = Sample["Sources"][Key]
            Record = ArchiveBySource.get(Source)
            if Record is None or Record["ArchiveKey"] not in ArchiveKeys:
                raise ValueError("Official source missing from archive: " + Source)
            ArchiveKey = Record["ArchiveKey"]
            Reference = "LeafPointClouds.npz::" + ArchiveKey
            Points = Archive[ArchiveKey]
            if Points.ndim != 2 or Points.shape[1] != 6 or not Numpy.isfinite(Points).all():
                raise ValueError("Invalid cloud: " + Reference)
            Points = Points.astype("<f4", copy=False)
            SingleResults = Singles.get(Reference, [])
            if not SingleResults:
                MissingReferences += 1
            Indices.append(len(Clouds))
            Arrays.append(Points)
            Clouds.append({"Id": "Official" + Sample["Id"] + Role,
                           "Number": int(Sample["Id"]),
                           "Group": "Official",
                           "Role": Role,
                           "Source": Sample["BaseMesh"] if Role == "Base" else Sample["Deform"],
                           "OriginalSource": Source,
                           "OriginalId": Sample.get("OriginalId", ""),
                           "ArchiveKey": ArchiveKey,
                           "Reference": Reference,
                           "PredictionReference": Reference,
                           "Count": len(Points),
                           "GrayPoints": Record.get("GrayFallbackPoints", 0),
                           "SingleResults": SingleResults})
        Mask = Sample.get("Mask")
        Cases.append({"Id": "Case" + Sample["Id"], "Number": int(Sample["Id"]),
                      "OriginalId": Sample.get("OriginalId", ""),
                      "A": Indices[0], "B": Indices[1],
                      "PairingStatus": Sample.get("PairingStatus", ""),
                      "Mask": ("../" + Mask) if Mask else None})

    # Store a page-relative offset into the concatenated float32 payload.
    Offset = 0
    for Cloud, Points in zip(Clouds, Arrays):
        Cloud["Offset"] = Offset
        Offset += Points.size

    Raw = Numpy.concatenate([Points.reshape(-1) for Points in Arrays]).astype("<f4").tobytes()
    Compressed = Gzip.compress(Raw, compresslevel=6, mtime=0)
    InferenceLink = Os.path.relpath(Args.inference.resolve(),
                                    Args.output.resolve().parent).replace(Os.sep, "/")
    SingleCount = sum(1 for Entry in Results if len(Entry["References"]) == 1)
    PairCount = sum(1 for Entry in Results if len(Entry["References"]) == 2)
    Payload = {
        "Clouds": Clouds,
        "Results": Results,
        "Cases": Cases,
        "Run": {Key: Inference.get(Key) for Key in
                ["model_path", "anno_path", "data_path", "pointnum", "generation_kwargs"]},
        "Report": {"Samples": len(Cases), "Clouds": len(Clouds), "Results": len(Results),
                   "SingleResults": SingleCount, "PairResults": PairCount,
                   "SkippedPredictions": SkippedPredictions,
                   "MissingPredictionReferences": MissingReferences,
                   "PointCount": int(Clouds[0]["Count"]) if Clouds else 0,
                   "BinaryBytes": len(Raw), "CompressedBytes": len(Compressed),
                   "InferenceSha256": Hashlib.sha256(Args.inference.read_bytes()).hexdigest()},
        "Encoding": "gzip-float32-little-endian",
        "Binary": Base64.b64encode(Compressed).decode("ascii"),
    }
    Payload["Run"]["inference_relative"] = InferenceLink

    Template = (Folder / "CompareTemplate.html").read_text(encoding="utf-8")
    Serialized = Json.dumps(Payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    Args.output.parent.mkdir(parents=True, exist_ok=True)
    Args.output.write_text(Template.replace("__PAYLOAD__", Serialized), encoding="utf-8")
    Args.report.parent.mkdir(parents=True, exist_ok=True)
    Args.report.write_text(Json.dumps(Payload["Report"], indent=2) + "\n", encoding="utf-8")
    Expected = len(Samples) * 4
    if len(Results) != Expected:
        print("Warning: expected %d answers (4 per sample), found %d" % (Expected, len(Results)))
    if MissingReferences:
        print("Warning: %d clouds have no single-object answer" % MissingReferences)
    print(Json.dumps(Payload["Report"]))
    print("Open: " + str(Args.output))


if __name__ == "__main__":
    Main()