"""Bounded, no-GPU native HDR delivery and provenance checks."""
import copy
import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import v2_bootstrap
from test_ltx25_native_plan import inputs

NAME = 'ComfyUI_zura_nodes.artist_studio'
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT/'artist_studio')]
    sys.modules[NAME] = package
builder = importlib.import_module(NAME+'.ltx25_hdr_plan')
module = importlib.import_module(NAME+'.ltx25_hdr_result')
enhancement = importlib.import_module(NAME+'.enhancement')


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.inspector = patch.object(enhancement, 'inspect_video', side_effect=self.inspect)
        self.inspector.start(); self.addCleanup(self.inspector.stop)
        self.colours = patch.object(module, '_colour_metadata', side_effect=self.colour)
        self.colours.start(); self.addCleanup(self.colours.stop)

    def inspect(self, path, **expected):
        self.calls.append((Path(path).name, expected))
        return {'width': expected['expected_width'], 'height': expected['expected_height'],
                'frames': expected['expected_frames'], 'fps': expected['expected_fps'],
                'audio_tracks': expected['expected_audio_tracks']}

    @staticmethod
    def colour(path):
        if '_preview_' in Path(path).name:
            return {'pixel_format':'yuv420p','transfer':13,'primaries':1,'matrix':1}
        return {'pixel_format':'yuv420p10le','transfer':18,'primaries':9,'matrix':9}

    def fixture(self, output='hlg_and_exr', scenario='original'):
        project, kwargs = inputs(scenario)
        project['config']['resolution'] = 512
        kwargs['timeline'].update(frames=9, width=512, height=512)
        kwargs['models']['video_vae'] = builder.VIDEO_VAE
        endpoint = {'manifest':'verified.json','sha':'d'*64,'colour_space':'acescg',
                    'opening_key':project['opening_key']}
        plan = builder.build_native_hdr_plan(project, hdr_endpoint=endpoint, output=output, **kwargs)
        graph = copy.deepcopy(plan['phases']['decode'])
        graph['load_stage2_video']['inputs']['cache_digest'] = 'e'*64
        prefix = plan['hdr_delivery']['prefix']
        parent = self.root/'genj'/'hdr'; parent.mkdir(parents=True, exist_ok=True)
        (parent/(prefix+'_preview_00001_.mp4')).write_bytes(b'preview')
        outputs = {'save_preview': {'images': [{'filename':prefix+'_preview_00001_.mp4',
                      'subfolder':r'genj\hdr','type':'output'}]}}
        if output != 'acescg_exr':
            (parent/(prefix+'_00001_.mp4')).write_bytes(b'hdr')
            outputs['zura_hdr_save_video'] = {'images':[{'filename':prefix+'_00001_.mp4',
                'subfolder':'genj/hdr','type':'output'}]}
        if output != 'hlg_video':
            image = self.exr_bytes()
            with zipfile.ZipFile(parent/(prefix+'.zip'),'w',compression=zipfile.ZIP_STORED) as archive:
                for i in range(9): archive.writestr(f'frame_{i:05d}.exr',image)
            outputs['zura_hdr_archive'] = {'files':[{'filename':prefix+'.zip',
                'subfolder':'genj/hdr','type':'output'}]}
        history = {'prompt':[1,'decode-prompt',copy.deepcopy(graph)],
            'status':{'status_str':'success','completed':True},'outputs':outputs}
        return plan, graph, history

    def exr_bytes(self, width=512, height=512, space='ACEScg', value=2.):
        import numpy as np
        import OpenImageIO as oiio
        path = self.root/'fixture.exr'
        spec = oiio.ImageSpec(width, height, 3, oiio.HALF)
        spec.attribute('colorSpace', space)
        spec.attribute('chromaticities', oiio.TypeDesc('float[8]'), (.713,.293,.165,.830,.128,.044,.32168,.33767))
        writer = oiio.ImageOutput.create(str(path))
        self.assertTrue(writer.open(str(path), spec))
        self.assertTrue(writer.write_image(np.full((height,width,3), value, dtype=np.float32)))
        writer.close()
        return path.read_bytes()

    def test_archive_requires_real_finite_acescg_images_and_valid_crcs(self):
        for invalid in (b'EXR data', self.exr_bytes(width=256), self.exr_bytes(space='ACEScct'), self.exr_bytes(value=float('nan'))):
            fixture = self.fixture()
            path = self.root/'genj/hdr'/(fixture[0]['hdr_delivery']['prefix']+'.zip')
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as archive:
                for index in range(9): archive.writestr(f'frame_{index:05d}.exr', invalid)
            with self.assertRaises(ValueError): self.collect(fixture)
        fixture = self.fixture()
        path = self.root/'genj/hdr'/(fixture[0]['hdr_delivery']['prefix']+'.zip')
        with zipfile.ZipFile(path) as archive:
            item = archive.infolist()[0]
            offset = item.header_offset + 30 + len(item.filename.encode()) + len(item.extra) + item.file_size - 1
        data = bytearray(path.read_bytes()); data[offset] ^= 1; path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'archive'): self.collect(fixture)

    def collect(self, fixture):
        return module.collect_native_delivery(*fixture, self.root)

    def test_each_delivery_and_audio_choice(self):
        for scenario in ('original','replacement','silent'):
            for output in ('hlg_video','hlg_and_exr','acescg_exr'):
                with self.subTest(scenario=scenario,output=output):
                    self.calls.clear()
                    plan, graph, history = self.fixture(output,scenario)
                    result = self.collect((plan,graph,history))
                    self.assertTrue(result['native_hdr'])
                    self.assertEqual(result['hdr_output'],output)
                    self.assertTrue(result['asset']['filename'].endswith('_preview_00001_.mp4'))
                    self.assertEqual(result['asset']['subfolder'],'genj/hdr')
                    self.assertEqual([f['label'] for f in result['hdr_files']],
                        (['HDR video'] if output!='acescg_exr' else [])+
                        (['ACEScg EXR sequence'] if output!='hlg_video' else []))
                    self.assertEqual(result['sha256'],builder.ltx25.file_digest(
                        self.root/result['asset']['subfolder']/result['asset']['filename']))
                    self.assertEqual(result['output_raster'], {'width':512,'height':512,'frames':9,
                        'fps':24,'audio_tracks':0 if scenario=='silent' else 1})
                    for _, options in self.calls:
                        self.assertEqual(options, {'expected_frames':9,'expected_width':512,
                            'expected_height':512,'expected_fps':24,
                            'expected_audio_tracks':0 if scenario=='silent' else 1})

    def test_changed_plan_graph_binding_or_history_are_rejected(self):
        fixture = self.fixture()
        for mutation in ('plan_key','template','binding','controls','prompt','status','unbound'):
            with self.subTest(mutation=mutation):
                p,g,h = copy.deepcopy(fixture)
                if mutation=='plan_key': p['basis']['seed']+=1
                elif mutation=='template': p['phases']['decode']['delivery_size_size']['inputs']['width']=320
                elif mutation=='binding': g['load_stage2_video']['inputs']['cache_digest']='x'*64;h['prompt'][2]=copy.deepcopy(g)
                elif mutation=='controls': g['trim_frames']['inputs']['length']=8;h['prompt'][2]=copy.deepcopy(g)
                elif mutation=='prompt': h['prompt'][2]['trim_frames']['inputs']['length']=8
                elif mutation=='status': h['status']['completed']=False
                else: g['load_stage2_video']['inputs']['cache_digest']='__UNBOUND__';h['prompt'][2]=copy.deepcopy(g)
                with self.assertRaises(ValueError): self.collect((p,g,h))

    def test_wrong_file_provenance_and_duplicates_are_rejected(self):
        fixture = self.fixture()
        for mutation in ('outside','other_prefix','duplicates','input','missing','wrong_folder','malformed'):
            with self.subTest(mutation=mutation):
                p,g,h=copy.deepcopy(fixture)
                refs=h['outputs']['save_preview']['images']
                if mutation=='outside': refs[0]['subfolder']='../genj/hdr'
                elif mutation=='other_prefix': refs[0]['filename']='other_preview_00001_.mp4'
                elif mutation=='duplicates': refs.append(copy.deepcopy(refs[0]))
                elif mutation=='input': refs[0]['type']='input'
                elif mutation=='missing': refs.clear()
                elif mutation=='wrong_folder': refs[0]['subfolder']='genj/other'
                else: h['outputs']['save_preview'] = None
                with self.assertRaises(ValueError):self.collect((p,g,h))

    def test_missing_or_unsafe_archive_entries_are_rejected(self):
        for entries, compression in [([f'frame_{i:05d}.exr' for i in range(8)],zipfile.ZIP_STORED),
                ([f'frame_{i:05d}.exr' for i in range(8)]+['../frame_00008.exr'],zipfile.ZIP_STORED),
                ([f'frame_{i:05d}.exr' for i in range(9)],zipfile.ZIP_DEFLATED)]:
            with self.subTest(entries=entries,compression=compression):
                fixture=self.fixture()
                path=self.root/'genj'/'hdr'/(fixture[0]['hdr_delivery']['prefix']+'.zip')
                with zipfile.ZipFile(path,'w',compression=compression) as archive:
                    for entry in entries:archive.writestr(entry,b'EXR')
                with self.assertRaisesRegex(ValueError,'archive'):self.collect(fixture)

    def test_sdr_preview_and_hlg_metadata_must_match(self):
        fixture=self.fixture()
        invalids = [
            {'pixel_format':'yuv420p','transfer':18,'primaries':9,'matrix':9},
            {'pixel_format':'yuv420p10le','transfer':18,'primaries':1,'matrix':9},
            {'pixel_format':'yuv420p10le','transfer':16,'primaries':9,'matrix':9},
            {'pixel_format':'yuv420p','transfer':18,'primaries':9,'matrix':9},
        ]
        for index, invalid in enumerate(invalids):
            with self.subTest(index=index):
                def colour(path):
                    preview='_preview_' in Path(path).name
                    return invalid if preview==(index==0) else self.colour(path)
                with patch.object(module,'_colour_metadata',side_effect=colour):
                    with self.assertRaises(ValueError):self.collect(fixture)

    def test_missing_master_or_raster_failure_is_not_published(self):
        fixture=self.fixture()
        path=self.root/'genj'/'hdr'/(fixture[0]['hdr_delivery']['prefix']+'_00001_.mp4')
        path.unlink()
        with self.assertRaisesRegex(ValueError,'missing'): self.collect(fixture)
        fixture=self.fixture()
        with patch.object(enhancement,'inspect_video',side_effect=ValueError('wrong frame count')):
            with self.assertRaisesRegex(ValueError,'wrong frame count'):self.collect(fixture)


if __name__ == '__main__':
    unittest.main()
