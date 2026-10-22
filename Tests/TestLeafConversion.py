"""Check surface sampling, point sampling, provenance, and upstream loading."""
import ast as Ast
import sys as Sys
import hashlib as Hashlib
import json as Json
import os as Os
import unittest as Unittest
import tempfile as Tempfile
from pathlib import Path
from PIL import Image

import numpy as Numpy

Sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Tools.Data.ConvertLeafDataset import Root, SampleGeometry

class LeafConversionTests(Unittest.TestCase):
    def test_SurfaceAreaAndDeterminism(self):
        Vertices = Numpy.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                                [10, 0, 0], [12, 0, 0], [10, 2, 0]], dtype=float)
        Faces = Numpy.array([[0, 1, 2], [3, 4, 5]])
        Points, Details = SampleGeometry(Vertices, Faces, 20000, Numpy.random.default_rng(7))
        Other, _ = SampleGeometry(Vertices, Faces, 20000, Numpy.random.default_rng(7))
        Numpy.testing.assert_array_equal(Points, Other)
        self.assertAlmostEqual(float((Points[:, 0] > 5).mean()), 0.8, delta=0.015)
        Numpy.testing.assert_array_equal(Points[:, 2], 0)
        self.assertEqual(Details['Method'], 'TriangleAreaSampling')

    def test_PointSamplingAndInvalidGeometry(self):
        Vertices = Numpy.array([[0, 0, 0], [1, 1, 1], [Numpy.nan, 0, 0]])
        Points, Details = SampleGeometry(Vertices, Numpy.empty((0, 3), dtype=int), 100,
                                         Numpy.random.default_rng(3))
        self.assertTrue(Details['Replacement'])
        self.assertEqual(Details['RemovedNonfiniteVertices'], 1)
        self.assertTrue(Numpy.isfinite(Points).all())
        Numpy.testing.assert_array_equal(Points[:, 3:], 0.5)
        with self.assertRaises(ValueError):
            SampleGeometry(Numpy.zeros((3, 3)), Numpy.array([[0, 1, 2]]), 10,
                           Numpy.random.default_rng(1))

    def test_TextureCoordinatesAndVertexRgb(self):
        Vertices = Numpy.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        Faces = Numpy.array([[0, 1, 2]])
        with Tempfile.TemporaryDirectory() as Directory:
            Texture = Path(Directory) / 'Texture.png'
            Image.fromarray(Numpy.array([[[0, 255, 0], [255, 255, 0]],
                                          [[0, 0, 0], [255, 0, 0]]], dtype=Numpy.uint8)).save(Texture)
            Attributes = {'Uvs': Vertices[:, :2], 'FaceUvs': Faces,
                          'FaceMaterials': ['Leaf'], 'Textures': {'Leaf': Texture}}
            Points, Details = SampleGeometry(Vertices, Faces, 100, Numpy.random.default_rng(9), Attributes)
            Numpy.testing.assert_allclose(Points[:, 3:5], Points[:, :2], atol=1e-6)
            self.assertEqual(Details['GrayFallbackPoints'], 0)
        Points, Details = SampleGeometry(Vertices, Numpy.empty((0, 3), dtype=int), 100,
                                         Numpy.random.default_rng(2), {'VertexColors': Vertices})
        Numpy.testing.assert_array_equal(Points[:, 3:], Points[:, :3])
        self.assertEqual(Details['ColoredPoints'], 100)

    def test_GeneratedDataAndUpstreamLoader(self):
        # Compile the actual upstream dataset class and normalization function
        # without importing the model stack or loading checkpoint weights.
        ClassTree = Ast.parse((Root / 'BeyondSingleObject/pointllm/eval/cvpr/eval_cvpr_patch.py').read_text())
        UtilsTree = Ast.parse((Root / 'BeyondSingleObject/pointllm/data/utils.py').read_text())
        Nodes = [Ast.ImportFrom(module='__future__', names=[Ast.alias(name='annotations')], level=0)]
        Nodes.extend(Node for Node in UtilsTree.body if isinstance(Node, Ast.FunctionDef) and Node.name == 'pc_norm')
        Nodes.extend(Node for Node in ClassTree.body if isinstance(Node, Ast.ClassDef) and Node.name == 'CVPRPatchEvalDataset')
        Namespace = {'np': Numpy, 'json': Json, 'os': Os, 'hashlib': Hashlib}
        exec(compile(Ast.fix_missing_locations(Ast.Module(body=Nodes, type_ignores=[])),
                     '<upstream loader>', 'exec'), Namespace)
        Data = Namespace['CVPRPatchEvalDataset'](
            str(Root / 'DatasetProcessed/LeafPair.json'),
            str(Root / 'DatasetProcessed'))
        Manifest = Json.loads((Root / 'DatasetProcessed/LeafManifest.json').read_text())
        self.assertGreater(len(Data.samples), 0)
        for Record in Manifest['Records']:
            Source = Root / Record['Source']
            self.assertEqual(Hashlib.sha256(Source.read_bytes()).hexdigest(), Record['SourceSha256'])
            with Numpy.load(Root / Record['Output'], allow_pickle=False) as Archive:
                Array = Archive[Record['ArchiveKey']]
            self.assertEqual(Array.shape, (8192, 6))
            self.assertEqual(Array.dtype, Numpy.float32)
            self.assertTrue(Numpy.isfinite(Array).all())
            self.assertTrue(((Array[:, 3:] >= 0) & (Array[:, 3:] <= 1)).all())
            self.assertEqual(Record['ColoredPoints'] + Record['GrayFallbackPoints'], len(Array))
            if Record['ColoredPoints'] == 0:
                Numpy.testing.assert_array_equal(Array[:, 3:], 0.5)
            for Dependency in Record['ColorDependencies']:
                self.assertEqual(Hashlib.sha256((Root / Dependency['Path']).read_bytes()).hexdigest(), Dependency['Sha256'])
        with self.assertRaises(KeyError):
            Data._load_point_cloud('LeafPointClouds.npz::MissingKey')
        with self.assertRaises(ValueError):
            Data._load_point_cloud('LeafPointClouds.npz::')
        with Tempfile.TemporaryDirectory() as Directory:
            Legacy = Path(Directory) / 'Legacy.npz'
            Expected = Numpy.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=Numpy.float32)
            Numpy.savez_compressed(Legacy, points=Expected)
            Loaded = Data._load_point_cloud(str(Legacy))
            self.assertEqual(Loaded.shape, (8192, 6))
            Numpy.testing.assert_array_equal(Loaded[:, 3:], 0.5)
        CsvCloud = Root / 'BeyondSingleObject/examples/sample_data/sample_point_clouds/object_1.csv'
        self.assertEqual(Data._load_point_cloud(str(CsvCloud)).shape, (8192, 6))
        for Entry in Data.samples:
            Question, Answer = Data._extract_qa(Entry['conversations'])
            self.assertEqual(Question.count('<point>'), len(Entry['object_ids']))
            self.assertEqual(Answer, '')
            for Identifier in Entry['object_ids']:
                Loaded = Data._load_point_cloud(Identifier, Entry)
                self.assertEqual(Loaded.shape, (8192, 6))
                Numpy.testing.assert_allclose(Loaded[:, :3].mean(axis=0), 0, atol=1e-5)
                self.assertAlmostEqual(float(Numpy.linalg.norm(Loaded[:, :3], axis=1).max()), 1, places=5)


if __name__ == '__main__':
    Unittest.main()
