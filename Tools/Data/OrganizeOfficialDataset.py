"""Copy complete filename-matched triples into the official directory layout.

Original Dataset is read only. A matching name is a candidate relationship,
not evidence of verified identity, registration or ground-truth correspondence.
"""
import csv as Csv
import hashlib as Hashlib
import json as Json
import shutil as Shutil
from pathlib import Path

import numpy as Numpy
from PIL import Image

Root = Path(__file__).resolve().parents[2]
SourceRoot = Root / 'Dataset'
Output = Root / 'DatasetOfficial'


def Digest(File):
    return Hashlib.sha256(File.read_bytes()).hexdigest()


def Relative(File):
    return File.relative_to(Root).as_posix()


def NameStem(File):
    return File.stem[:-7] if File.stem.endswith('_deform') else File.stem


def GeometryType(File):
    if File.suffix.lower() == '.obj':
        with File.open() as Stream:
            return 'Mesh' if any(Line.startswith('f ') for Line in Stream) else 'PointCloud'
    with File.open('rb') as Stream:
        while True:
            Line = Stream.readline()
            if not Line:
                raise ValueError(f'Incomplete PLY header: {File}')
            Fields = Line.decode('ascii').split()
            if Fields[:2] == ['element', 'face'] and int(Fields[2]) > 0:
                return 'Mesh'
            if Fields == ['end_header']:
                return 'PointCloud'


def Copy(File, Target):
    Target.parent.mkdir(parents=True, exist_ok=True)
    Shutil.copy2(File, Target)
    if Digest(File) != Digest(Target):
        raise ValueError(f'Copy checksum mismatch: {File}')


def CopyGeometry(File, Target, Prefix):
    """Keep geometry and UV bytes; relocate referenced materials and textures."""
    Dependencies, Missing = [], []
    if File.suffix.lower() != '.obj':
        Copy(File, Target)
        return Dependencies, Missing
    Lines = File.read_text().splitlines(keepends=True)
    MaterialIndex = 0
    TextureIndex = 0
    for Index, Line in enumerate(Lines):
        Fields = Line.split()
        if not Fields or Fields[0] != 'mtllib':
            continue
        NewLibraries = []
        for Name in Fields[1:]:
            MaterialIndex += 1
            Library = File.parent / Name
            LibraryName = f'{Prefix}Material{MaterialIndex:02d}.mtl'
            NewLibraries.append(LibraryName)
            if not Library.is_file():
                Missing.append(str(Library))
                continue
            MaterialLines = Library.read_text().splitlines(keepends=True)
            Dependencies.append({'Source': Relative(Library), 'SourceSha256': Digest(Library),
                                 'Output': Relative(Target.parent / LibraryName)})
            for MaterialLineIndex, MaterialLine in enumerate(MaterialLines):
                TextureFields = MaterialLine.split()
                if not TextureFields or TextureFields[0] != 'map_Kd':
                    continue
                if len(TextureFields) != 2:
                    Missing.append('Unsupported map_Kd options: ' + Relative(Library))
                    continue
                Reference = TextureFields[1].replace('\\', '/')
                Texture = Library.parent / Reference
                if not Texture.is_file():
                    Texture = Library.parent / Path(Reference).name
                TextureIndex += 1
                TextureName = f'{Prefix}Texture{TextureIndex:02d}{Texture.suffix.lower()}'
                MaterialLines[MaterialLineIndex] = f'map_Kd {TextureName}\n'
                if not Texture.is_file():
                    Missing.append(Reference)
                    continue
                Copy(Texture, Target.parent / TextureName)
                Dependencies.append({'Source': Relative(Texture), 'SourceSha256': Digest(Texture),
                                     'Output': Relative(Target.parent / TextureName)})
            (Target.parent / LibraryName).write_text(''.join(MaterialLines))
        Lines[Index] = 'mtllib ' + ' '.join(NewLibraries) + '\n'
    Target.write_text(''.join(Lines))
    return Dependencies, Missing


def MaskValid(File):
    with Image.open(File) as Mask:
        Rgb = Numpy.asarray(Mask.convert('RGB'))
    # A grayscale mask may have antialiased boundary values. Do not threshold
    # or replace its original pixels, and do not mistake RGB photos for masks.
    return bool(Numpy.array_equal(Rgb[:, :, 0], Rgb[:, :, 1])
                and Numpy.array_equal(Rgb[:, :, 1], Rgb[:, :, 2])
                and Rgb[:, :, 0].min() < Rgb[:, :, 0].max())


def Main():
    if Output.exists() and any(Output.iterdir()):
        raise FileExistsError('DatasetOfficial is not empty; refusing to overwrite existing contents')
    for Folder in ['base_shape', 'deform_train', 'base_mask/sdf']:
        (Output / Folder).mkdir(parents=True, exist_ok=True)
    Regions = [
        ('Main', SourceRoot / 'base_shape', SourceRoot / 'base_mask',
         [SourceRoot / Name for Name in ['deform_train', 'deform_train_new', 'deform_raw_denoise', 'deform_raw']]),
        ('Extra', SourceRoot / 'base_shape_extra', SourceRoot / 'base_mask_extra',
         [SourceRoot / Name for Name in ['deform_train', 'deform_train_new', 'deform_raw_denoise', 'deform_raw']]),
        ('MapleExtra', SourceRoot / 'maple_extra/base_shape', SourceRoot / 'maple_extra/base_mask',
         [SourceRoot / 'maple_extra' / Name for Name in ['deform_train', 'deform_raw_denoise']]),
    ]
    Records, Unmatched, UsedNames = [], [], set()
    SeenDeforms, EligibleDeforms, ChosenDeforms = set(), set(), set()
    for Region, BaseFolder, MaskFolder, DeformFolders in Regions:
        Candidates = {}
        for Priority, Folder in enumerate(DeformFolders):
            for File in sorted(Folder.glob('*')):
                if File.suffix.lower() not in ('.obj', '.ply'):
                    continue
                SeenDeforms.add(File)
                if File.stem.endswith('_base'):
                    continue
                Candidates.setdefault(NameStem(File), []).append((Priority, not File.stem.endswith('_deform'), File))
        for Base in sorted(BaseFolder.glob('*.obj')):
            SampleId = Base.stem
            if Region == 'Extra' and SampleId.endswith('_rgb'):
                SampleId = SampleId[:-4]
                Mask = MaskFolder / f'{SampleId}_mask.png'
            else:
                Mask = MaskFolder / f'{SampleId}.png'
            Options = sorted(Candidates.get(SampleId, []))
            EligibleDeforms.update(File for _, _, File in Options)
            Reasons = []
            if not Mask.is_file():
                Reasons.append('MissingMask')
            elif not MaskValid(Mask):
                Reasons.append('MaskNotGrayscaleOrConstant')
            if not Options:
                Reasons.append('MissingDeformation')
            if SampleId in UsedNames:
                Reasons.append('AmbiguousDuplicateSampleId')
            if Reasons:
                Unmatched.append({'Region': Region, 'OriginalId': SampleId, 'Source': Relative(Base),
                                  'Reason': ';'.join(Reasons), 'ExpectedMask': Relative(Mask),
                                  'Candidates': [Relative(File) for _, _, File in Options]})
                continue
            Deform = Options[0][2]
            ChosenDeforms.add(Deform)
            UsedNames.add(SampleId)
            OutputId = str(len(Records) + 1)
            BaseTarget = Output / 'base_shape' / f'{OutputId}.obj'
            DeformName = f'{OutputId}.obj' if Deform.suffix.lower() == '.obj' else f'{OutputId}_deform.ply'
            DeformTarget = Output / 'deform_train' / DeformName
            MaskTarget = Output / 'base_mask' / f'{OutputId}.png'
            BaseDependencies, MissingBase = CopyGeometry(Base, BaseTarget, OutputId + 'Base')
            DeformDependencies, MissingDeform = CopyGeometry(Deform, DeformTarget, OutputId + 'Deform')
            Copy(Mask, MaskTarget)
            Sdf = MaskFolder / 'sdf' / f'{Mask.stem}_sdf.npy'
            SdfTarget = None
            SdfStatus = 'NotAvailable'
            if Sdf.is_file():
                Values = Numpy.load(Sdf, allow_pickle=False)
                with Image.open(Mask) as MaskImage:
                    ExpectedShape = (MaskImage.height, MaskImage.width)
                if Values.shape == ExpectedShape and Numpy.isfinite(Values).all():
                    SdfTarget = Output / 'base_mask/sdf' / f'{OutputId}_sdf.npy'
                    Copy(Sdf, SdfTarget)
                    SdfStatus = 'SameNameAndDimensions_NotRecomputed'
                else:
                    SdfStatus = 'SkippedIncompatibleArray'
            Records.append({'Id': OutputId, 'OriginalId': SampleId, 'Region': Region,
                            'PairingStatus': 'FilenameMatched_NotManuallyVerified',
                            'BaseMesh': Relative(BaseTarget), 'Deform': Relative(DeformTarget),
                            'Mask': Relative(MaskTarget), 'Sdf': Relative(SdfTarget) if SdfTarget else '',
                            'DeformGeometry': GeometryType(Deform), 'SdfStatus': SdfStatus,
                            'Sources': {'Base': Relative(Base), 'Deform': Relative(Deform), 'Mask': Relative(Mask),
                                        'Sdf': Relative(Sdf) if SdfTarget else ''},
                            'SourceSha256': {'Base': Digest(Base), 'Deform': Digest(Deform), 'Mask': Digest(Mask),
                                             'Sdf': Digest(Sdf) if SdfTarget else ''},
                            'Dependencies': BaseDependencies + DeformDependencies,
                            'MissingColorResources': MissingBase + MissingDeform,
                            'AlternativeDeforms': [Relative(File) for _, _, File in Options[1:]],
                            'SelectionRule': 'Directory priority: deform_train > deform_train_new > deform_raw_denoise > deform_raw; explicit _deform preferred within each directory.'})
    for File in sorted(SeenDeforms):
        if File in ChosenDeforms:
            continue
        Reason = 'BaseTagged_NotDeformation' if File.stem.endswith('_base') else 'AlternativeOrIncompleteTriple' if File in EligibleDeforms else 'NoMatchingBaseMesh'
        Unmatched.append({'Region': '', 'OriginalId': NameStem(File), 'Source': Relative(File), 'Reason': Reason,
                          'ExpectedMask': '', 'Candidates': []})
    Manifest = {'MatchingRule': 'Name-based only, with complete nonconstant grayscale masks; no synthetic masks or mesh reconstruction.',
                'Samples': Records, 'Unmatched': Unmatched}
    (Output / 'Manifest.json').write_text(Json.dumps(Manifest, ensure_ascii=False, indent=2) + '\n')
    with (Output / 'SampleIndex.csv').open('w', newline='') as Stream:
        Writer = Csv.DictWriter(Stream, fieldnames=['Id', 'Region', 'BaseMesh', 'Deform', 'Mask', 'Sdf', 'DeformGeometry', 'PairingStatus'])
        Writer.writeheader()
        Writer.writerows({Key: Record[Key] for Key in Writer.fieldnames} for Record in Records)
    with (Output / 'Unmatched.csv').open('w', newline='') as Stream:
        Writer = Csv.DictWriter(Stream, fieldnames=['Region', 'OriginalId', 'Source', 'Reason', 'ExpectedMask', 'Candidates'])
        Writer.writeheader()
        Writer.writerows({**Record, 'Candidates': ';'.join(Record['Candidates'])} for Record in Unmatched)
    with (Output / 'NumberMap.csv').open('w', newline='') as Stream:
        Writer = Csv.writer(Stream)
        Writer.writerow(['Id', 'OriginalId', 'SourceBase', 'SourceDeform', 'SourceMask'])
        Writer.writerows((Record['Id'], Record['OriginalId'], Record['Sources']['Base'],
                          Record['Sources']['Deform'], Record['Sources']['Mask']) for Record in Records)
    print(f'Organized {len(Records)} triples; {len(Unmatched)} exclusion/alternative records.')


if __name__ == '__main__':
    Main()
