"""Small controlled prompt comparison on archived inputs, preserving old runs.

Four fixed inputs x three prompt variants x two sampling seeds = 24 cases.
Run with --run to load the existing checkpoint and execute actual inference.
"""
import argparse as Argparse
import copy as Copy
import hashlib as Hashlib
import importlib as Importlib
import json as Json
import os as Os
import random as Random
import sys as Sys
from pathlib import Path

Root = Path(__file__).resolve().parents[2]
Output = Root / 'DatasetProcessed/Outputs/PromptStudy'
SingleGeometry = (
    '<point>\nDescribe only observable geometry of this point cloud in at most three short sentences. '
    'Discuss outline, elongation, and out-of-plane bending or twisting only when supported. '
    'Do not infer object identity, function, surrounding objects, or unseen parts. '
    'Say uncertain when evidence is insufficient. Do not compare it with an unseen object.'
)
DoubleGeometry = (
    '<point> <point>\nCompare only the observable geometry of Object 1 and Object 2. '
    'First state whether they appear geometrically identical, similar, or different. '
    'They may be identical. Then give at most three supported similarities or differences. '
    'If no reliable difference is visible, say so. Do not infer object identity, '
    'function, surroundings, or unseen parts.'
)


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument('--run', action='store_true')
    Args = Parser.parse_args()
    OriginalPath = Root / 'DatasetProcessed/Outputs/LeafPairEval/inference.json'
    Original = Json.loads(OriginalPath.read_text())
    Pair = next(Entry for Entry in Original['results'] if Entry['metadata']['subset'] == 'PairSameName')
    Control = next(Entry for Entry in Original['results'] if Entry['metadata']['subset'] == 'SameObjectControl')
    Singles = {Entry['object_ids'][0]: Entry for Entry in Original['results'] if len(Entry['object_ids']) == 1}
    Inputs = [('SingleA', Singles[Pair['object_ids'][0]]), ('SingleB', Singles[Pair['object_ids'][1]]),
              ('DifferentInputs', Pair), ('SameObjectControl', Control)]
    Samples = []
    for Name, Entry in Inputs:
        Geometry = SingleGeometry if len(Entry['object_ids']) == 1 else DoubleGeometry
        Context = 'The input is a point cloud of a plant leaf. ' if len(Entry['object_ids']) == 1 else 'Both inputs are point clouds of plant leaves. '
        ContextGeometry = Geometry.replace('\n', '\n' + Context, 1)
        for Variant, Prompt in [('Original', Entry['question']), ('GeometryOnly', Geometry), ('LeafContext', ContextGeometry)]:
            for Repeat, Seed in enumerate([20261019, 20261020], 1):
                Metadata = Copy.deepcopy(Entry.get('metadata', {}))
                Metadata.update({'study_input': Name, 'prompt_variant': Variant, 'repeat': Repeat, 'sampling_seed': Seed,
                                 'reference_status': 'Unlabeled', 'study_same_object_truth': Name == 'SameObjectControl'})
                Samples.append({'id': Name + Variant + str(Repeat), 'object_ids': Entry['object_ids'],
                                'conversations': [{'from': 'human', 'value': Prompt}, {'from': 'gpt', 'value': ''}],
                                'metadata': Metadata})
    Output.mkdir(parents=True, exist_ok=True)
    Annotation = Output / 'Annotations.json'
    Annotation.write_text(Json.dumps(Samples, ensure_ascii=False, indent=2) + '\n')
    Method = {'Cases': len(Samples), 'Inputs': 4, 'Variants': 3, 'SamplingSeeds': [20261019, 20261020],
              'MaxNewTokens': 128, 'Temperature': 0, 'RawInferenceSha256': Hashlib.sha256(OriginalPath.read_bytes()).hexdigest(),
              'LeafContextCaveat': 'Explicitly supplies the class; improved leaf naming would not demonstrate class recognition.',
              'SamplingControl': 'Reset Python/NumPy/Torch/CUDA RNGs before each input. Same seed across variants within each input. CUDA numerical nondeterminism may remain.'}
    (Output / 'Method.json').write_text(Json.dumps(Method, indent=2) + '\n')
    if not Args.run:
        print('Prepared', len(Samples), 'cases. Add --run to execute.')
        return
    import numpy as Numpy
    import torch as Torch
    Os.chdir(Root / 'BeyondSingleObject')
    Sys.path.insert(0, str(Path.cwd()))
    Module = Importlib.import_module('pointllm.eval.cvpr.eval_cvpr_patch')
    for Entry in Samples:
        if Module.is_shape_mating_task(Entry['conversations'][0]['value']):
            raise ValueError('Prompt would be misrouted to Shape Mating')
    Getter = Module.CVPRPatchEvalDataset.__getitem__

    def GetWithFixedSeed(Self, Index):
        Sample = Getter(Self, Index)
        Seed = Sample.metadata['sampling_seed']
        Random.seed(Seed)
        Numpy.random.seed(Seed)
        Torch.manual_seed(Seed)
        Torch.cuda.manual_seed_all(Seed)
        return Sample

    Module.CVPRPatchEvalDataset.__getitem__ = GetWithFixedSeed
    Sys.argv = ['PromptStudy', '--model_path', 'checkpoints/multi-3dllm', '--anno_path', str(Annotation),
                '--data_path', str(Root / 'DatasetProcessed'), '--output_dir', str(Output),
                '--output_name', 'inference.json', '--limit', '0', '--max_new_tokens', '128',
                '--temperature', '0', '--top_p', '0.9', '--top_k', '40', '--repetition_penalty', '1.0',
                '--no_repeat_ngram_size', '0']
    try:
        Module.main()
    finally:
        Module.CVPRPatchEvalDataset.__getitem__ = Getter
    assert Hashlib.sha256(OriginalPath.read_bytes()).hexdigest() == Method['RawInferenceSha256']


if __name__ == '__main__':
    Main()
