"""Convert original leaf geometry into reproducible Multi-3DLLM inputs.

Requires numpy, plyfile and Pillow. Run from any directory; paths in the plan are
relative to the project root. Dataset is read only; generated files go to
DatasetProcessed. All model-facing schema keys follow upstream.
"""
import argparse as Argparse
import hashlib as Hashlib
import json as Json
from pathlib import Path

import numpy as Numpy
from plyfile import PlyData
from PIL import Image

Root = Path(__file__).resolve().parents[2]
OutputRoot = Root / 'DatasetProcessed'
Question = (
    '<point> <point>\nDescribe the geometry of Object 1 and Object 2, then '
    'compare their main shape differences. Focus on the outline, elongation, '
    'bending, curling, and twisting. Avoid unsupported claims about species, '
    'health, or material.'
)


def LoadGeometry(Source):
    if Source.suffix.lower() == '.obj':
        Vertices, Faces, Uvs, FaceUvs, FaceMaterials = [], [], [], [], []
        Material = None
        Libraries = []
        with Source.open() as Stream:
            for Line in Stream:
                Fields = Line.split()
                if not Fields:
                    continue
                if Fields[0] == 'v':
                    Vertices.append([float(Value) for Value in Fields[1:4]])
                elif Fields[0] == 'mtllib':
                    Libraries.extend(Source.parent / Name for Name in Fields[1:])
                elif Fields[0] == 'usemtl':
                    Material = ' '.join(Fields[1:])
                elif Fields[0] == 'vt':
                    Uvs.append([float(Value) for Value in Fields[1:3]])
                elif Fields[0] == 'f':
                    if len(Fields) != 4:
                        raise ValueError(f'Only triangular OBJ faces supported: {Source}')
                    Face = [int(Field.split('/')[0]) for Field in Fields[1:]]
                    if 0 in Face:
                        raise ValueError(f'Invalid zero OBJ index: {Source}')
                    Faces.append([Index - 1 if Index > 0 else len(Vertices) + Index
                                  for Index in Face])
                    TextureIndices = [Field.split('/')[1] if '/' in Field else '' for Field in Fields[1:]]
                    FaceUvs.append([int(Index) - 1 if int(Index) > 0 else len(Uvs) + int(Index)
                                    for Index in TextureIndices] if all(TextureIndices) else [-1, -1, -1])
                    FaceMaterials.append(Material)
        Vertices = Numpy.asarray(Vertices, dtype=Numpy.float64)
        Faces = Numpy.asarray(Faces, dtype=Numpy.int64).reshape(-1, 3)
        Textures, Dependencies, Missing = {}, [], []
        for Library in Libraries:
            if not Library.is_file():
                Missing.append(str(Library.relative_to(Root)))
                continue
            Dependencies.append(Library)
            CurrentMaterial = None
            for Line in Library.read_text().splitlines():
                Fields = Line.split()
                if Fields and Fields[0] == 'newmtl':
                    CurrentMaterial = ' '.join(Fields[1:])
                elif Fields and Fields[0] == 'map_Kd':
                    if len(Fields) != 2:
                        Missing.append('Unsupported map_Kd options: ' + str(Library))
                        continue
                    TextureReference = Fields[1].replace('\\', '/')
                    Texture = Library.parent / TextureReference
                    if not Texture.is_file():
                        # Some source MTLs still name the original workstation.
                        # Relocate only the explicitly referenced filename.
                        Texture = Library.parent / Path(TextureReference).name
                    if Texture.is_file():
                        Textures[CurrentMaterial] = Texture
                        Dependencies.append(Texture)
                    else:
                        Missing.append(TextureReference)
        Attributes = {'Uvs': Numpy.asarray(Uvs, dtype=float).reshape(-1, 2),
                      'FaceUvs': Numpy.asarray(FaceUvs, dtype=int).reshape(-1, 3),
                      'FaceMaterials': FaceMaterials, 'Textures': Textures,
                      'Dependencies': Dependencies, 'MissingColorResources': Missing}

    elif Source.suffix.lower() == '.ply':
        Data = PlyData.read(Source)
        Attributes = {'Dependencies': [], 'MissingColorResources': []}
        if all(Name in Data['vertex'].data.dtype.names for Name in ('red', 'green', 'blue')):
            Colors = Numpy.column_stack([Data['vertex'][Name] for Name in ('red', 'green', 'blue')])
            if Colors.dtype.kind not in 'ui':
                raise ValueError(f'Floating RGB range requires explicit handling: {Source}')
            Attributes['VertexColors'] = Colors.astype(float) / Numpy.iinfo(Colors.dtype).max
        Vertices = Numpy.column_stack([Data['vertex'][Axis] for Axis in ('x', 'y', 'z')]).astype(Numpy.float64)
        Faces = Numpy.empty((0, 3), dtype=Numpy.int64)
        if 'face' in Data and len(Data['face'].data):
            FaceValues = Data['face']['vertex_indices']
            if any(len(Face) != 3 for Face in FaceValues):
                raise ValueError(f'Only triangular PLY faces supported: {Source}')
            Faces = Numpy.asarray(list(FaceValues), dtype=Numpy.int64)
    else:
        raise ValueError(f'Unsupported geometry: {Source}')
    if Vertices.ndim != 2 or Vertices.shape[1] != 3 or not len(Vertices):
        raise ValueError(f'No valid XYZ array: {Source}')
    if len(Faces) and (Faces.min() < 0 or Faces.max() >= len(Vertices)):
        raise ValueError(f'Face indices out of bounds: {Source}')
    return Vertices, Faces, Attributes


def SampleGeometry(Vertices, Faces, Count, Generator, Attributes=None):
    Attributes = Attributes or {}
    Rgb = Numpy.full((Count, 3), 0.5, dtype=float)
    HasColor = Numpy.zeros(Count, dtype=bool)
    Finite = Numpy.isfinite(Vertices).all(axis=1)
    if len(Faces):
        FaceIndices = Numpy.flatnonzero(Finite[Faces].all(axis=1))
        ValidFaces = Faces[FaceIndices]
        Triangles = Vertices[ValidFaces]
        Areas = Numpy.linalg.norm(Numpy.cross(Triangles[:, 1] - Triangles[:, 0],
                                             Triangles[:, 2] - Triangles[:, 0]), axis=1) / 2
        Valid = Numpy.isfinite(Areas) & (Areas > 0)
        Triangles, Areas, FaceIndices = Triangles[Valid], Areas[Valid], FaceIndices[Valid]
        if not len(Triangles):
            raise ValueError('Mesh has no finite, non-degenerate faces')
        Choices = Generator.choice(len(Triangles), Count, p=Areas / Areas.sum())
        Selected = Triangles[Choices]
        SelectedFaces = FaceIndices[Choices]
        U = Numpy.sqrt(Generator.random((Count, 1)))
        V = Generator.random((Count, 1))
        Points = (1 - U) * Selected[:, 0] + U * (1 - V) * Selected[:, 1] + U * V * Selected[:, 2]
        Weights = Numpy.concatenate([1 - U, U * (1 - V), U * V], axis=1)
        if 'VertexColors' in Attributes:
            Rgb = Numpy.einsum('ni,nij->nj', Weights, Attributes['VertexColors'][Faces[SelectedFaces]])
            HasColor[:] = True
        if Attributes.get('Textures'):
            TextureIndices = Attributes['FaceUvs'][SelectedFaces]
            Uvs = Attributes['Uvs']
            ValidUv = ((TextureIndices >= 0) & (TextureIndices < len(Uvs))).all(axis=1)
            if len(Uvs):
                SafeIndices = Numpy.clip(TextureIndices, 0, len(Uvs) - 1)
                Coordinates = Numpy.einsum('ni,nij->nj', Weights, Uvs[SafeIndices])
                Materials = Numpy.asarray(Attributes['FaceMaterials'], dtype=object)[SelectedFaces]
                for Material, TexturePath in Attributes['Textures'].items():
                    Mask = ValidUv & (Materials == Material) & Numpy.isfinite(Coordinates).all(axis=1)
                    if not Mask.any():
                        continue
                    with Image.open(TexturePath) as TextureImage:
                        Texture = Numpy.asarray(TextureImage.convert('RGB'), dtype=float) / 255
                    TextureUv = Numpy.clip(Coordinates[Mask], 0, 1)
                    X = TextureUv[:, 0] * (Texture.shape[1] - 1)
                    Y = (1 - TextureUv[:, 1]) * (Texture.shape[0] - 1)
                    X0, Y0 = Numpy.floor(X).astype(int), Numpy.floor(Y).astype(int)
                    X1, Y1 = Numpy.minimum(X0 + 1, Texture.shape[1] - 1), Numpy.minimum(Y0 + 1, Texture.shape[0] - 1)
                    Dx, Dy = (X - X0)[:, None], (Y - Y0)[:, None]
                    Rgb[Mask] = ((1 - Dx) * (1 - Dy) * Texture[Y0, X0] + Dx * (1 - Dy) * Texture[Y0, X1]
                                 + (1 - Dx) * Dy * Texture[Y1, X0] + Dx * Dy * Texture[Y1, X1])
                    HasColor[Mask] = True
        Method = 'TriangleAreaSampling'
        ValidCount = len(Triangles)
        Replacement = False
    else:
        ValidVertices = Vertices[Finite]
        if not len(ValidVertices):
            raise ValueError('Point cloud has no finite points')
        Replacement = len(ValidVertices) < Count
        Choices = Generator.choice(len(ValidVertices), Count, replace=Replacement)
        Points = ValidVertices[Choices]
        if 'VertexColors' in Attributes:
            Rgb = Attributes['VertexColors'][Finite][Choices]
            HasColor[:] = True
        Method = 'UniformPointSampling'
        ValidCount = len(ValidVertices)
    if not Numpy.ptp(Points, axis=0).max() > 0:
        raise ValueError('Degenerate sampled point cloud')
    Result = Numpy.full((Count, 6), 0.5, dtype=Numpy.float32)
    Result[:, :3] = Points
    Result[:, 3:] = Rgb
    if not Numpy.isfinite(Result).all():
        raise ValueError('Coordinates overflow float32')
    return Result, {'Method': Method, 'ValidElements': ValidCount, 'Replacement': Replacement,
                    'RemovedNonfiniteVertices': int((~Finite).sum()),
                    'ColoredPoints': int(HasColor.sum()), 'GrayFallbackPoints': int((~HasColor).sum())}


def Convert(SourceName, Count, Seed):
    Source = (Root / SourceName).resolve()
    if not Source.is_relative_to((Root / 'Dataset').resolve()):
        raise ValueError(f'Source must be inside Dataset: {SourceName}')
    Relative = Source.relative_to(Root).as_posix()
    Digest = Hashlib.sha256(Source.read_bytes()).hexdigest()
    Identifier = 'Leaf' + Hashlib.sha256(Relative.encode()).hexdigest()[:16]
    Output = OutputRoot / 'LeafPointClouds.npz'
    GeneratorSeed = int.from_bytes(Hashlib.sha256(f'{Seed}:{Relative}:{Digest}'.encode()).digest()[:8], 'little')
    Vertices, Faces, Attributes = LoadGeometry(Source)
    Points, Details = SampleGeometry(Vertices, Faces, Count, Numpy.random.default_rng(GeneratorSeed), Attributes)
    return Points, {'Id': Identifier, 'Source': Relative, 'SourceSha256': Digest,
            'Output': Output.relative_to(Root).as_posix(), 'ArchiveKey': Identifier, 'Shape': list(Points.shape),
            'Dtype': str(Points.dtype), 'Seed': GeneratorSeed,
            'SourceVertices': len(Vertices), 'SourceFaces': len(Faces),
            'ColorPolicy': 'SourceRgbOrTextureWithGrayFallback',
            'MissingColorResources': Attributes.get('MissingColorResources', []),
            'ColorDependencies': [{'Path': Dependency.relative_to(Root).as_posix(),
                                   'Sha256': Hashlib.sha256(Dependency.read_bytes()).hexdigest()}
                                  for Dependency in Attributes.get('Dependencies', [])], 'Coordinates': 'OriginalNoAlignmentOrScaling',
            'SampleBounds': [Points[:, :3].min(axis=0).tolist(), Points[:, :3].max(axis=0).tolist()],
            **Details}


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument('--plan', type=Path, default=Root / 'Tools' / 'Config' / 'LeafPairPlan.json')
    Parser.add_argument('--point-count', type=int, default=8192)
    Parser.add_argument('--seed', type=int, default=20261017)
    Parser.add_argument('--all', action='store_true', help='Also convert base_shape and deform_raw_denoise, without inventing pairs')
    Args = Parser.parse_args()
    if Args.point_count < 1:
        Parser.error('--point-count must be positive')
    Plan = Json.loads(Args.plan.read_text())
    Names = [Pair['Id'] for Pair in Plan]
    if not Plan or len(Names) != len(set(Names)):
        raise ValueError('Plan must contain unique pair IDs')
    Sources = {Pair[Key] for Pair in Plan for Key in ('SourceA', 'SourceB')}
    if Args.all:
        for Folder in ('base_shape', 'deform_raw_denoise'):
            Sources.update(Source.relative_to(Root).as_posix()
                           for Source in (Root / 'Dataset' / Folder).glob('*')
                           if Source.suffix.lower() in ('.obj', '.ply'))
    Converted = [Convert(Source, Args.point_count, Args.seed) for Source in sorted(Sources)]
    Records = [Record for Points, Record in Converted]
    OutputRoot.mkdir(parents=True, exist_ok=True)
    Temporary = OutputRoot / 'LeafPointClouds.tmp.npz'
    Numpy.savez_compressed(Temporary, **{Record['Id']: Points for Points, Record in Converted})
    Temporary.replace(OutputRoot / 'LeafPointClouds.npz')
    Lookup = {Record['Source']: Record for Record in Records}
    Annotations = []
    for Pair in Plan:
        Orders = [('AB', ['SourceA', 'SourceB'])]
        if Pair.get('IncludeReverse') and Pair['SourceA'] != Pair['SourceB']:
            Orders.append(('BA', ['SourceB', 'SourceA']))
        for Order, Keys in Orders:
            Selected = [Lookup[Pair[Key]] for Key in Keys]
            Annotations.append({
                'id': Pair['Id'] + Order, 'task_type': 'comparative',
                'object_ids': ['LeafPointClouds.npz::' + Record['ArchiveKey'] for Record in Selected],
                'conversations': [{'from': 'human', 'value': Question}, {'from': 'gpt', 'value': ''}],
                'metadata': {'source_paths': [Record['Source'] for Record in Selected],
                             'pairing_status': Pair.get('PairingStatus', 'Unverified'),
                             'pair_kind': Pair.get('Kind', 'ShapeComparison'), 'order': Order,
                             'reference_status': 'Unlabeled', 'color_policy': 'SourceRgbOrTextureWithGrayFallback'}})
    Manifest = {'PointCount': Args.point_count, 'Seed': Args.seed,
                'NumpyVersion': Numpy.__version__, 'Plan': str(Args.plan.resolve().relative_to(Root)),
                'Records': Records}
    (OutputRoot / 'LeafManifest.json').write_text(Json.dumps(Manifest, indent=2) + '\n')
    (OutputRoot / 'LeafPair.json').write_text(Json.dumps(Annotations, indent=2) + '\n')
    print(f'Converted {len(Records)} shapes; generated {len(Annotations)} inference cases.')


if __name__ == '__main__':
    Main()
