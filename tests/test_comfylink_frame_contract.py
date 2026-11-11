"""CPU graph and tensor evidence for exact AE frame delivery; no model runs."""
import copy
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from fractions import Fraction
from unittest.mock import patch

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink.frame_contract import (apply_frame_contract, contract_rate,
    ltx_model_frames, normalise_frame_contract, prepare_frame_contract_graph, validate_interval)
from comfylink.frame_nodes import ZuraComfyLinkMatchFrames


def contract(count=50, numerator=30000, denominator=1001):
    return {'schemaVersion': 1, 'frameCount': count,
        'frameRate': {'numerator': numerator, 'denominator': denominator},
        'width': 512, 'height': 512, 'modelFrames': max(9, ltx_model_frames(count)),
        'trimFrames': count, 'sessionId': 'a' * 32}


def native_module(module_name="hdr_native_graph"):
    # The graph builder imports no Comfy or GPU runtime. Give it only its
    # relative-import package rather than importing the plugin entry point.
    root = Path(__file__).resolve().parents[1]
    for name, directory in (('frame_contract_fixture', root), ('frame_contract_fixture.artist_studio', root/'artist_studio')):
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(directory)]
            sys.modules[name] = package
    return importlib.import_module('frame_contract_fixture.artist_studio.' + module_name)


class FrameContractTests(unittest.TestCase):
    def test_temporal_camera_retains_ae_interval_and_rejects_rate_or_raster_changes(self):
        camera = native_module('panorama_camera')
        ae = contract(50, 24, 1)
        source = {'sha': 'a' * 64, 'duration': 5, 'fps': 24,
                  'file': 'source.mp4', 'has_audio': True}
        selection = camera.plan(source, {'width': 512, 'height': 512, 'ae_frame_contract': ae})
        self.assertEqual(selection['frames'], 50)
        self.assertEqual(selection['padded'], 57)
        self.assertEqual(selection['ae_frame_contract'], ae)
        graph = camera.build_graph(source, selection, None, 'render', warp='warp.mp4')
        self.assertEqual(graph['source_pad']['inputs']['required_source_frames'], 50)
        self.assertEqual(graph['source_pad']['inputs']['frames'], 57)
        self.assertEqual(graph['trim']['inputs']['length'], 50)
        self.assertEqual(graph['video']['inputs']['fps'], 24)
        with self.assertRaisesRegex(ValueError, '24 fps'):
            camera.plan(source, {'ae_frame_contract': contract(50)})
        with self.assertRaisesRegex(ValueError, 'source raster'):
            camera.plan(source, {'width': 768, 'height': 512, 'ae_frame_contract': ae})

    def test_actual_native_ltx_graphs_request_at_least_all_source_frames(self):
        native = native_module()
        for count in (9, 25, 48, 50):
            with self.subTest(count=count):
                original = native.build_native_video_graph(source='source.mov', start_frame=0,
                    frame_count=count, fps=30000/1001, width=512, height=512, prefix='exact', has_audio=True)
                graph = prepare_frame_contract_graph(original, contract(count), 'hdr')
                self.assertEqual(graph['empty']['inputs']['length'], ltx_model_frames(count))
                self.assertGreaterEqual(graph['empty']['inputs']['length'], count)
                self.assertEqual(graph['source']['inputs']['frame_count'], count)
                self.assertEqual(graph['trim_frames']['inputs']['length'], count)
                self.assertEqual(graph['sample1'], original['sample1'])
                self.assertEqual(graph['lora'], original['lora'])
                self.assertEqual(graph['vae'], original['vae'])
                self.assertTrue(any(node['class_type'] == 'ZuraComfyLinkMatchFrames' for node in graph.values()))

    def test_300_frame_authored_graph_uses_305_and_short_recipe_rejects(self):
        graph = {'latent': {'class_type': 'EmptyLTXVLatentVideo', 'inputs': {'length': 49}},
            'decode': {'class_type': 'VAEDecode', 'inputs': {'samples': ['latent', 0]}},
            'video': {'class_type': 'CreateVideo', 'inputs': {'images': ['decode', 0], 'fps': 24}},
            'save': {'class_type': 'SaveVideo', 'inputs': {'video': ['video', 0]}}}
        desc = {'family': 'ltx', 'output_nodes': ['save']}
        self.assertEqual(apply_frame_contract(graph, contract(300), desc)['latent']['inputs']['length'], 305)
        with self.assertRaisesRegex(ValueError, 'complete 300-frame'):
            apply_frame_contract(graph, contract(300), {**desc, 'max_model_frames': 121})

    def test_guard_preserves_exact_order_hdr_alpha_dtype_and_storage(self):
        guard = ZuraComfyLinkMatchFrames()
        for count in (9, 25, 48, 50, 300):
            with self.subTest(count=count):
                pixels = torch.arange((ltx_model_frames(count))*2*3*4, dtype=torch.float32).reshape(-1, 2, 3, 4)/10-7
                mask = torch.arange(len(pixels)*2*3, dtype=torch.float32).reshape(-1, 2, 3)/7-4
                out, alpha, metadata = guard.match(pixels, count, 3, 2, mask, 'unchanged metadata')
                self.assertEqual(out.shape[0], count)
                self.assertTrue(torch.equal(out, pixels[:count]))
                self.assertTrue(torch.equal(alpha, mask[:count]))
                self.assertEqual(out.dtype, pixels.dtype)
                self.assertEqual(out.untyped_storage().data_ptr(), pixels.untyped_storage().data_ptr())
                self.assertLess(out.min().item(), 0)
                self.assertGreater(out.max().item(), 1)
                self.assertEqual(metadata, 'unchanged metadata')

    def test_short_decode_and_wrong_raster_fail_without_padding(self):
        guard = ZuraComfyLinkMatchFrames()
        with self.assertRaisesRegex(ValueError, 'cannot be repeated'):
            guard.match(torch.zeros(48, 2, 3, 4), 50, 3, 2)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            guard.match(torch.zeros(57, 2, 3, 4), 50, 4, 2)
        with self.assertRaisesRegex(ValueError, 'alpha/mask'):
            guard.match(torch.zeros(57, 2, 3, 4), 50, 3, 2, torch.zeros(49, 2, 3))

    def test_no_contract_preserves_native_graph_identity_and_serialisation(self):
        graph = native_module().build_native_video_graph(source='source.mov', start_frame=7,
            frame_count=50, fps=24, width=512, height=512, prefix='golden')
        before = json.dumps(graph, sort_keys=True)
        self.assertIs(apply_frame_contract(graph, None, {}), graph)
        self.assertIs(prepare_frame_contract_graph(graph, None, 'anything'), graph)
        self.assertEqual(json.dumps(graph, sort_keys=True), before)

    def test_selected_saver_only_no_reference_or_unrelated_branch_changes(self):
        graph = native_module().build_native_video_graph(source='source.mov', start_frame=0,
            frame_count=50, fps=24, width=512, height=512, prefix='selected')
        graph['other_latent'] = {'class_type': 'EmptyLTXVLatentVideo', 'inputs': {'length': 9}}
        graph['other_save'] = {'class_type': 'SaveImage', 'inputs': {'images': ['other_latent', 0]}}
        # An audio preparation video is upstream of the final video, but is
        # not an output encoder. Its image branch must stay native.
        graph['audio_video'] = {'class_type': 'CreateVideo', 'inputs': {'images': ['source', 0], 'fps': 24}}
        graph['audio_components'] = {'class_type': 'GetVideoComponents', 'inputs': {'video': ['audio_video', 0]}}
        graph['zura_hdr_video']['inputs']['audio'] = ['audio_components', 1]
        before = copy.deepcopy(graph)
        patched = apply_frame_contract(graph, contract(), {'family': 'ltx', 'output_nodes': ['zura_hdr_save_video']})
        self.assertEqual(graph, before)
        for name in ('other_save', 'other_latent', 'audio_video', 'zura_hdr_save_preview', 'zura_hdr_archive'):
            self.assertEqual(patched[name], before[name])
        self.assertNotEqual(patched['zura_hdr_video']['inputs']['images'], before['zura_hdr_video']['inputs']['images'])

    def test_actual_encoder_rate_and_audio_trim_use_exact_interval(self):
        graph = native_module().build_native_video_graph(source='source.mov', start_frame=0,
            frame_count=50, fps=24, width=512, height=512, prefix='timing', has_audio=True)
        patched = prepare_frame_contract_graph(graph, contract(), 'hdr')
        self.assertEqual(patched['zura_hdr_video']['inputs']['fps'], 30000/1001)
        self.assertEqual(patched['zura_hdr_save_video']['inputs']['fps'], 30000/1001)
        audio = patched[patched['zura_hdr_video']['inputs']['audio'][0]]
        self.assertEqual(audio['class_type'], 'TrimAudioDuration')
        self.assertEqual(audio['inputs']['start_index'], 0)
        self.assertAlmostEqual(audio['inputs']['duration'], 50*1001/30000, places=15)

    def test_native_h3_non_24_is_rejected_before_queue(self):
        graph = {'latent': {'class_type': 'EmptyMiniMaxH3LatentAV', 'inputs': {'length': 56}},
            'decode': {'class_type': 'VAEDecode', 'inputs': {'samples': ['latent', 0]}},
            'video': {'class_type': 'CreateVideo', 'inputs': {'images': ['decode', 0], 'fps': 24}},
            'save': {'class_type': 'SaveVideo', 'inputs': {'video': ['video', 0]}}}
        value={**contract(),'modelFrames':56}
        with self.assertRaisesRegex(ValueError, 'cannot preserve'):
            prepare_frame_contract_graph(graph, value, 'references')

    def test_actual_outpaint_graph_preserves_rational_source_and_exact_delivery(self):
        native_module()
        outpaint=importlib.import_module('frame_contract_fixture.artist_studio.outpaint_studio')
        source={'sha':'b'*64,'file':'source.mov','width':512,'height':512,
            'duration':20,'fps_num':30000,'fps_den':1001,'has_audio':True}
        for count in (9,25,48,50):
            with self.subTest(count=count):
                args=dict(start=0,duration=count*1001/30000,mode='black',width=512,height=512)
                plain=outpaint.plan(source,**args)
                selected=outpaint.plan(source,**args,ae_frame_contract=contract(count))
                self.assertNotEqual(plain['review_key'],selected['review_key'])
                g=outpaint.build_studio_graph(source,selected,review_key=selected['review_key'],
                    output_prefix='genj/outpaint/exact',pad_delivery=True)
                self.assertNotIn('hold_delivery',g)
                self.assertEqual(g['source_range']['inputs']['expected_frames'],count)
                self.assertEqual(g['empty']['inputs']['length'],ltx_model_frames(count))
                self.assertEqual((g['assemble']['inputs']['fps_num'],g['assemble']['inputs']['fps_den']),(30000,1001))
                self.assertEqual(g[g['assemble']['inputs']['images'][0]]['class_type'],'ZuraComfyLinkMatchFrames')

    def test_long_outpaint_plan_keeps_300_frame_source_interval_without_cap(self):
        native_module()
        module=importlib.import_module('frame_contract_fixture.artist_studio.outpaint_long_runner')
        source={'sha':'b'*64,'file':'source.mov','width':512,'height':512,
            'duration':20,'fps_num':30000,'fps_den':1001}
        selected,parts,subplans=module.plan_long(source,start=0,duration=300*1001/30000,
            mode='black',width=512,height=512,overlap=9,strategy='anchored_masked',ae_frame_contract=contract(300))
        self.assertEqual(selected['frames'],300)
        self.assertEqual(parts[-1].start+parts[-1].count,300)
        self.assertGreater(len(parts),1)
        self.assertTrue(all(plan['frames']==part.count for plan,part in zip(subplans,parts)))
        self.assertTrue(all('ae_frame_contract' not in plan for plan in subplans))
        command=module.ffmpeg_assembly('ffmpeg',parts,[f'part{i}.mp4' for i in range(len(parts))],
            'result.mp4',source='source.mov',pad_tail=False,audio_duration=300*1001/30000,fps=Fraction(30000,1001))
        self.assertEqual(command[command.index('-frames:v')+1],'300')
        self.assertEqual(command[command.index('-r')+1],'30000/1001')
        self.assertNotIn('tpad=',command[command.index('-filter_complex')+1])

    def test_native_custom_savers_retain_own_crop_and_alpha_bookkeeping(self):
        for kind,field in (('ZuraPaintoutUncrop','decoded_crop'),('ZuraAlphaVideoOutput','images')):
            g={'decode':{'class_type':'VAEDecode','inputs':{}},
                'save':{'class_type':kind,'inputs':{field:['decode',0],'info':['source',1]}},
                'source':{'class_type':'Source','inputs':{}}}
            out=prepare_frame_contract_graph(g,contract(),'paintout')
            self.assertEqual(out['save']['inputs'][field],['decode',0])
            self.assertEqual(json.loads(out['save']['inputs']['ae_frame_contract']),contract())
            self.assertNotIn('ae_frame_contract',g['save']['inputs'])

    def test_main_ltx_plan_hash_and_native_decode_bind_ae_contract(self):
        import test_ltx25_studio_runtime as fixture
        project,plain=fixture.example()
        project=copy.deepcopy(project)
        value={**contract(48,24,1),'width':704,'height':1280}
        project['config']['ae_frame_contract']=value
        project['approval']=fixture.studio.prep_key(project)
        basis=plain['basis']
        plan=fixture.ltx.build_plan(project,scenario='replacement',timeline=basis['timeline'],
            models=basis['models'],model_pins=basis['model_pins'],
            text_encoder_inputs=basis['encoder'],approval_key=project['approval'],original_audio_sha='c'*64)
        self.assertEqual(plan['basis']['ae_frame_contract'],value)
        self.assertNotEqual(plan['key'],plain['key'])
        decode=plan['phases']['decode']
        guard=decode[decode['create_video']['inputs']['images'][0]]
        self.assertEqual(guard['class_type'],'ZuraComfyLinkMatchFrames')
        self.assertEqual(guard['inputs']['frame_count'],48)
        self.assertEqual(plan['graph_hashes']['decode'],fixture.ltx.digest(decode))

    def test_obvious_incompatible_native_raster_rejected_before_queue(self):
        g={'scale':{'class_type':'ImageScale','inputs':{'width':640,'height':512}},
            'save':{'class_type':'SaveImage','inputs':{'images':['scale',0]}}}
        with self.assertRaisesRegex(ValueError,'raster differs'):
            prepare_frame_contract_graph(g,contract(1),'image')

    def test_enhancement_collects_all_native_batches_but_verifies_exact_ae_frames(self):
        import test_h3_enhanced1080 as fixture
        case=fixture.ContinuationCollectorTests('test_full_family_records_one_result_once_with_delivered_raster')
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.action.update(expected_frames=48,expected_batch_frames=49)
        case.queue.history=case.family(count=49)
        with patch('folder_paths.get_output_directory',return_value=str(case.output),create=True), \
             patch.object(fixture.enhancement,'inspect_video',return_value={
                 'width':1080,'height':1920,'frames':48,'fps':24,'audio_tracks':1}) as inspect:
            case.obj._collect_h3_enhancement(case.project_record,case.action)
        self.assertEqual(case.project_record['phase'],'done')
        self.assertEqual(len(case.project_record['results']),1)
        self.assertEqual(inspect.call_args.kwargs['expected_frames'],48)

    def test_interval_and_rational_validation_cannot_forge_count(self):
        value = contract()
        self.assertEqual(str(contract_rate(normalise_frame_contract(value))), '30000/1001')
        validate_interval(value, frames=50, fps=30000/1001, width=512, height=512)
        for fields in ({'frames': 49}, {'fps': 30}, {'width': 640}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_interval(value, **{'frames': 50, 'fps': 30000/1001, 'width': 512, 'height': 512, **fields})
        for change in ({'trimFrames': 49}, {'modelFrames': 49}, {'sessionId': 'not a session'}, {'frameCount': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalise_frame_contract({**value, **change})


if __name__ == '__main__':
    unittest.main()
