"""Validate the generated DatasetOfficial comparison page without model inference."""
import base64 as Base64
import gzip as Gzip
import hashlib as Hashlib
import json as Json
import unittest as Unittest
from pathlib import Path

import numpy as Numpy

Root = Path(__file__).resolve().parents[1]
Folder = Root / 'Compare'
InferencePath = Root / 'DatasetProcessed/Outputs/OfficialEval/inference.json'


class CompareTests(Unittest.TestCase):
    @classmethod
    def setUpClass(Class):
        Html = (Folder / 'index.html').read_text()
        Tag = '<script id="Payload" type="application/json">'
        Start = Html.index(Tag) + len(Tag)
        Class.Data = Json.loads(Html[Start:Html.index('</script>', Start)])
        Class.Binary = Numpy.frombuffer(Gzip.decompress(Base64.b64decode(Class.Data['Binary'])), dtype='<f4')
        Class.Inference = Json.loads(InferencePath.read_text())

    def Array(self, Cloud):
        return self.Binary[Cloud['Offset']:Cloud['Offset'] + Cloud['Count'] * 6].reshape(-1, 6)

    def test_PayloadContainsOnlyTheOfficialRun(self):
        self.assertEqual(len(self.Data['Cases']), 50)
        self.assertEqual(len(self.Data['Clouds']), 100)
        self.assertEqual(len(self.Data['Results']), 200)
        self.assertEqual([Case['Number'] for Case in self.Data['Cases']], list(range(1, 51)))
        self.assertEqual({Cloud['Group'] for Cloud in self.Data['Clouds']}, {'Official'})
        self.assertEqual(self.Binary.nbytes, self.Data['Report']['BinaryBytes'])

    def test_CloudsMatchTheSharedArchiveExactly(self):
        with Numpy.load(Root / 'DatasetProcessed/LeafPointClouds.npz', allow_pickle=False) as Archive:
            for Cloud in self.Data['Clouds']:
                Numpy.testing.assert_array_equal(self.Array(Cloud), Archive[Cloud['ArchiveKey']])
                self.assertEqual(Cloud['Count'], 8192)
                self.assertTrue(Numpy.isfinite(self.Array(Cloud)).all())

    def test_AnswersAreTheCurrentOfficialInference(self):
        Expected = Hashlib.sha256(InferencePath.read_bytes()).hexdigest()
        self.assertEqual(self.Data['Report']['InferenceSha256'], Expected)
        self.assertEqual(len(self.Data['Results']), len(self.Inference['results']))
        for Record, Original in zip(self.Data['Results'], self.Inference['results']):
            self.assertEqual(Record['References'], Original['object_ids'])
            self.assertEqual(Record['Prediction'], Original['prediction'])
            self.assertEqual(Record['Question'], Original['question'])
        self.assertEqual(self.Data['Report']['SkippedPredictions'], 0)

    def test_EveryCloudHasOneDescriptionAndEveryCaseBothDirections(self):
        ById = {Record['Id']: Record for Record in self.Data['Results']}
        for Cloud in self.Data['Clouds']:
            self.assertEqual(Cloud['Reference'], Cloud['PredictionReference'])
            self.assertEqual(len(Cloud['SingleResults']), 1)
            self.assertEqual(ById[Cloud['SingleResults'][0]]['References'], [Cloud['Reference']])
        PairReferences = {tuple(Record['References']) for Record in self.Data['Results']
                          if len(Record['References']) == 2}
        self.assertEqual(len(PairReferences), 100)
        for Case in self.Data['Cases']:
            Forward = (self.Data['Clouds'][Case['A']]['Reference'],
                       self.Data['Clouds'][Case['B']]['Reference'])
            self.assertIn(Forward, PairReferences)
            self.assertIn(Forward[::-1], PairReferences)

    def test_SourcesAndMasksExist(self):
        for Cloud in self.Data['Clouds']:
            self.assertTrue((Root / Cloud['Source']).is_file(), Cloud['Source'])
        for Case in self.Data['Cases']:
            if Case['Mask']:
                self.assertTrue((Folder / Case['Mask']).resolve().is_file(), Case['Mask'])


if __name__ == '__main__':
    Unittest.main()