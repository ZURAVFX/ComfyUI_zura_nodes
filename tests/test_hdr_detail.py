"""CPU colour/data proof for SDR detail reconstruction and linear delivery."""
import ast
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

import numpy as np
import OpenImageIO as oiio
import PyOpenColorIO as ocio
import torch
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/folder)];sys.modules[name]=package
detail=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_detail')
sdr=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio')
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_graph')
package=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_package')
chunks=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
adapter=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy')
preview=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_preview_colour')
paint=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


def source_linear(source):
    value=np.ascontiguousarray(source,dtype=np.float32).copy()
    ocio.Config.CreateFromFile('ocio://cg-config-latest').getProcessor('sRGB Encoded Rec.709 (sRGB)','ACEScg').getDefaultCPUProcessor().applyRGB(value)
    return value


def codes(linear):
    # Independent published ACEScct encoding, with no display/data clamp.
    return np.where(linear>.0078125,(np.log2(np.maximum(linear,1e-20))+9.72)/17.52,
                    10.5402377416545*linear+.0729055341958355).astype(np.float32)


def actual_colour_math():
    """Compile installed ImageColorSpace math only; never import GPU runtime."""
    path=Path(sys.executable).resolve().parents[2]/'comfy_extras/nodes_images.py'
    if not path.exists():raise unittest.SkipTest('Installed Comfy ImageColorSpace source is required for actual-node math fixture')
    tree=ast.parse(path.read_text(encoding='utf-8'))
    functions={'srgb_to_linear','hlg_to_linear','_convert_rgb_primaries','_rgb_luminance','_tone_map_luminance','_compress_rgb_gamut'}
    prefixes=('_HLG','_REC709','_REC2020','_ACESCG','_ACESCCT','_SDR_WHITE','_PQ','_LOGC3')
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in functions or
              isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id.startswith(prefixes)
                  for target in ast.walk(ast.Tuple(elts=node.targets,ctx=ast.Load())))]
    klass=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='ImageColorSpace')
    execute=next(node for node in klass.body if isinstance(node,ast.FunctionDef) and node.name=='execute')
    execute.decorator_list=[]; selected.append(execute)
    io=types.SimpleNamespace(NodeOutput=lambda image:(image,))
    scope={'torch':torch,'IO':io,'comfy':types.SimpleNamespace(model_management=types.SimpleNamespace(intermediate_device=lambda:'cpu',intermediate_dtype=lambda:torch.float32))}
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),scope)
    return lambda image,source,destination:scope['execute'](None,image,source,destination)[0]


class HDRDetailTests(unittest.TestCase):
    def test_constant_ltx_exposure_retains_exact_registered_source_structure(self):
        rng=np.random.default_rng(71)
        source=rng.uniform(.02,.8,(64,96,3)).astype(np.float32)
        before=source.copy();prediction=source*4
        result,gain=detail.reconstruct_acescg(source,prediction)
        np.testing.assert_allclose(gain,4,rtol=3e-6,atol=3e-6)
        np.testing.assert_allclose(result,source*4,rtol=3e-6,atol=3e-6)
        np.testing.assert_array_equal(source,before)
        self.assertGreater(float(result.max()),1)

    def test_signed_gamut_black_and_alpha_are_not_clipped_or_recoloured(self):
        rng=np.random.default_rng(81)
        source=rng.uniform(.01,.8,(32,48,4)).astype(np.float32)
        source[0,0,:3]=0;source[4,5,:3]=[-.05,.3,2.5]
        prediction=np.full((32,48,3),2,np.float32)
        before=source.tobytes();result,gain=detail.reconstruct_acescg(source,prediction)
        np.testing.assert_array_equal(result[...,3],source[...,3])
        np.testing.assert_array_equal(result[0,0,:3],np.zeros(3))
        np.testing.assert_array_equal(result[...,:3],source[...,:3]*gain[...,None])
        np.testing.assert_allclose(result[...,:3]/gain[...,None],source[...,:3],rtol=1e-7,atol=1e-7)
        self.assertLess(float(result[4,5,0]),0);self.assertGreater(float(result.max()),1)
        self.assertEqual(source.tobytes(),before);self.assertTrue(np.isfinite(result).all())

    def test_real_source_transform_requires_exact_delivered_raster_and_frame_interval(self):
        rng=np.random.default_rng(90)
        source=rng.uniform(.03,.8,(9,35,67,4)).astype(np.float32)
        expected=source_linear(source[0,:32,:64,:3])*3
        prediction=torch.from_numpy(codes(expected)[None])
        original_source=source.tobytes();original_prediction=prediction.numpy().tobytes()
        for mismatched in (source,source[:1],source[:1,:32],source[:2,:32,:64]):
            with self.assertRaisesRegex(ValueError,'matching NHWC'):
                detail.ZuraHDRSourceDetail().reconstruct(torch.from_numpy(mismatched),prediction)
        output,raw,metadata=detail.ZuraHDRSourceDetail().reconstruct(torch.from_numpy(source[:1,:32,:64]),prediction)
        self.assertEqual(output.shape,(1,32,64,4));self.assertEqual(output.dtype,torch.float32)
        np.testing.assert_allclose(output[0,...,:3],expected,rtol=2e-5,atol=2e-6)
        np.testing.assert_array_equal(output[0,...,3],source[0,:32,:64,3])
        self.assertIs(raw,prediction);self.assertEqual(prediction.numpy().tobytes(),original_prediction)
        self.assertEqual(source.tobytes(),original_source)
        info=json.loads(metadata);self.assertEqual(info['frames'],1);self.assertEqual(info['colour']['encoding'],'acescg')

    def test_comfy_interrupt_mid_batch_stops_before_processing_next_frame(self):
        class Interrupted(Exception):pass
        source=torch.full((3,32,48,3),.5)
        prediction=torch.from_numpy(np.stack([codes(source_linear(source[0].numpy())*2)]*3))
        before_source=source.numpy().tobytes();before_prediction=prediction.numpy().tobytes()
        completed=[]
        original=detail.reconstruct_acescg
        def reconstruct(*args):
            result=original(*args);completed.append(True);return result
        def check():
            if completed:raise Interrupted('cancelled after first CPU frame')
        management=types.SimpleNamespace(throw_exception_if_processing_interrupted=check)
        with patch.dict(sys.modules,{'comfy.model_management':management}),patch.object(detail,'reconstruct_acescg',side_effect=reconstruct):
            with self.assertRaisesRegex(Interrupted,'first CPU frame'):
                detail.ZuraHDRSourceDetail().reconstruct(source,prediction)
        self.assertEqual(len(completed),1)
        self.assertEqual(source.numpy().tobytes(),before_source)
        self.assertEqual(prediction.numpy().tobytes(),before_prediction)

    def test_frames_are_independent_and_parameter_scale_is_frozen(self):
        source=torch.full((3,32,48,3),.5)
        linear=source_linear(source[0].numpy())
        prediction=torch.from_numpy(np.stack([codes(linear*x) for x in (2,4,8)]))
        output,_,_=detail.ZuraHDRSourceDetail().reconstruct(source,prediction)
        for index,multiplier in enumerate((2,4,8)):
            np.testing.assert_allclose(output[index],linear*multiplier,rtol=2e-5,atol=2e-6)
        self.assertEqual(detail.filter_parameters(512,512),{'gaussianSigmaPixels':16.,'guidedRadiusPixels':32,'guidedRegularizationStopsSquared':1.})
        self.assertEqual(detail.filter_parameters(3840,2160)['guidedRadiusPixels'],240)
        with self.assertRaises(ValueError):detail.ZuraHDRSourceDetail().reconstruct(source[:1],prediction)
        with self.assertRaises(ValueError):detail.reconstruct_acescg(np.full((2,2,3),np.nan),np.ones((2,2,3)))

    def test_inverse_matches_actual_comfy_math_including_extended_codes(self):
        convert=actual_colour_math()
        encoded=torch.tensor([[[[-.1,0,.072905534],[.15525114,.5,1.1]]]],dtype=torch.float32)
        expected=convert(encoded,'HDR ACEScct','linear ACEScg')[0].numpy()
        np.testing.assert_allclose(detail.decode_prediction(encoded[0].numpy()),expected,rtol=5e-6,atol=2e-4)
        self.assertLess(float(expected.min()),-.0069);self.assertGreater(float(expected.max()),200)

    def test_linear_master_writer_has_no_second_inverse_or_range_clip(self):
        values=torch.tensor([[[[-.5,.180123,100000.]]]],dtype=torch.float32)
        before=values.numpy().tobytes()
        with tempfile.TemporaryDirectory() as root,patch.dict(sys.modules,{'folder_paths':types.SimpleNamespace(get_output_directory=lambda:root)}):
            archive=package.ZuraHDRPackageACEScg().package(values,'linear','float32')['result'][0]
            with zipfile.ZipFile(archive) as z:Path(root,'read.exr').write_bytes(z.read('frame_00000.exr'))
            inp=oiio.ImageInput.open(str(Path(root,'read.exr')))
            try:
                self.assertEqual(inp.spec().format,oiio.FLOAT)
                self.assertIn(inp.spec().get_string_attribute('oiio:ColorSpace'),('ACEScg','lin_ap1_scene'))
                result=inp.read_image(format=oiio.FLOAT)
            finally:inp.close()
            np.testing.assert_array_equal(result,values[0].numpy())
        self.assertEqual(values.numpy().tobytes(),before)

    def test_linear_staging_overlap_preserves_range_colour_and_total_frames(self):
        plan=[chunks.HDRChunk(0,3,0),chunks.HDRChunk(2,3,1)]
        first=torch.tensor([-.1,.5,10.]).expand(3,2,2,3).clone()
        second=first*2
        with tempfile.TemporaryDirectory() as root:
            store=storage.HDRChunkStore(root,'a'*32,plan,2,2,create=True,colour_space='acescg')
            store.write(0,first);store.write(1,second)
            output=torch.cat(list(store.stitched()))
            self.assertEqual(len(output),5)
            torch.testing.assert_close(output[2],(first[2]+second[0])/2)
            self.assertLess(float(output.min()),0);self.assertGreater(float(output.max()),10)
            wrong=storage.HDRChunkStore(root,'a'*32,plan,2,2)
            with self.assertRaisesRegex(ValueError,'colour space'):wrong.read(0)

    def test_actual_sdr_chunk_staging_uses_sdr_capacity_and_pins_planning_mode(self):
        # SDR pads to 512x672 (113 frames), native to 512x704 (105).
        # Execute the real disk writer and reader on the 106-frame case.
        self.assertEqual(chunks.chunk_capacity(512,642,mode='sdr'),113)
        self.assertEqual(chunks.chunk_capacity(512,642,mode='native'),105)
        plan=chunks.plan_chunks(0,106,512,642,mode='sdr')
        with tempfile.TemporaryDirectory() as root,patch.object(adapter,'staging_root',return_value=root):
            store=storage.HDRChunkStore(root,'b'*32,plan,512,642,create=True,colour_space='acescg',planning_mode='sdr')
            graph=sdr.build_hdr_graph(source='source.mp4',start_frame=0,frame_count=106,fps=24,prefix='capacity')
            staged=adapter.chunk_graph(graph,store,0,'hdr_unpad_raster')
            inputs=staged['zura_hdr_stage_chunk']['inputs'].copy();inputs.pop('images')
            frames=torch.tensor(2.,dtype=torch.float32).expand(106,642,512,3)
            adapter.ZuraHDRWriteChunk().write(frames,**inputs)
            actual=store.read(0)
            self.assertEqual(tuple(actual.shape),(106,642,512,3));self.assertEqual(float(actual[-1,-1,-1,2]),2.)
            del actual
            metadata=json.loads((store.directory/'000000.json').read_text())
            self.assertEqual(metadata['planning_mode'],'sdr')
            wrong=storage.HDRChunkStore(root,'b'*32,plan,512,642,colour_space='acescg')
            with self.assertRaisesRegex(ValueError,'planning mode'):wrong.read(0)

    def test_actual_over_2048_sdr_write_reanchor_and_padding_use_same_plan(self):
        convert=actual_colour_math()
        plan=chunks.plan_chunks(0,122,2050,32,mode='sdr')
        with tempfile.TemporaryDirectory() as root,patch.object(adapter,'staging_root',return_value=root):
            store=storage.HDRChunkStore(root,'c'*32,plan,2050,32,create=True,colour_space='acescg',planning_mode='sdr')
            for index,part in enumerate(plan):
                graph=sdr.build_hdr_graph(source='wide.mp4',start_frame=part.start,frame_count=part.count,fps=24,prefix='wide')
                staged=adapter.chunk_graph(graph,store,index,'hdr_unpad_raster',anchor_strength=.75,anchor_mode='i2v')
                inputs=staged['zura_hdr_stage_chunk']['inputs'].copy();inputs.pop('images')
                adapter.ZuraHDRWriteChunk().write(torch.tensor(float(index+2)).expand(part.count,32,2050,3),**inputs)
            self.assertEqual(store.read(1).shape,(9,32,2050,3))
            anchor_inputs=staged['zura_hdr_previous_anchor']['inputs']
            self.assertEqual(anchor_inputs['planning_mode'],'sdr')
            with patch.object(paint,'native_colour',side_effect=convert):
                anchor,=adapter.ZuraHDRReadChunkAnchor().read(**anchor_inputs)
            restored=convert(anchor,'HDR ACEScct','linear ACEScg')
            torch.testing.assert_close(restored,torch.full_like(restored,2),rtol=1e-5,atol=1e-5)
            padded,=adapter.ZuraHDRPadSDRAnchor().prepare(anchor)
            self.assertEqual(tuple(padded.shape),(1,32,2080,3))
            self.assertEqual(adapter.ZuraHDRReadChunkAnchor.INPUT_TYPES()['required']['width'][1]['max'],4096)

    def test_half_storage_preserves_representable_extended_values_or_refuses_overflow(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(sys.modules,{'folder_paths':types.SimpleNamespace(get_output_directory=lambda:root)}):
            values=torch.tensor([[[[-.05,20000.,60000.]]]])
            archive=package.ZuraHDRPackageACEScg().package(values,'half','half')['result'][0]
            with zipfile.ZipFile(archive) as z:Path(root,'read.exr').write_bytes(z.read('frame_00000.exr'))
            inp=oiio.ImageInput.open(str(Path(root,'read.exr')))
            try:
                self.assertEqual(inp.spec().format,oiio.HALF)
                result=inp.read_image(format=oiio.FLOAT)
            finally:inp.close()
            np.testing.assert_allclose(result,values[0],rtol=.001,atol=1e-5)
            with self.assertRaisesRegex(ValueError,'FLOAT32'):
                package.ZuraHDRPackageACEScg().package(values*2,'overflow','half')

    def test_delivery_branches_share_final_linear_and_native_is_unchanged(self):
        for format in ('hlg_video','acescg_exr','hlg_and_exr'):
            graph=sdr.build_hdr_graph(source='source.png',start_frame=0,frame_count=1,fps=25,prefix='detail',output=format,exr_storage='float32',single_frame=True)
            self.assertEqual(graph['hdr_detail']['inputs'],{'source':['zura_hdr_source',0],'prediction':['hdr_unpad_raster',0]})
            self.assertEqual(graph['hdr_unpad_frames']['inputs']['length'],['zura_hdr_prepare',3])
            if format!='hlg_video':
                self.assertEqual(graph['zura_hdr_archive']['class_type'],'ZuraHDRPackageACEScg')
                self.assertEqual(graph['zura_hdr_archive']['inputs']['images'],['hdr_detail',0])
            if format!='acescg_exr':self.assertEqual(graph['zura_hdr_hlg']['inputs'],{'image':['hdr_detail',0],'source':'linear ACEScg','destination':'HDR'})
            store=types.SimpleNamespace(plan=[chunks.HDRChunk(0,1,0)],identity='a'*32,width=512,height=512)
            staged=adapter.chunk_graph(graph,store,0,'hdr_unpad_raster')
            self.assertEqual(staged['zura_hdr_stage_chunk']['inputs']['images'],['hdr_detail',0])
            self.assertEqual(staged['zura_hdr_stage_chunk']['inputs']['colour_space'],'acescg')
        creative=native.build_native_video_graph(source='native.mp4',start_frame=0,frame_count=9,fps=24,width=512,height=512,prefix='native')
        self.assertNotIn('hdr_detail',creative)
        self.assertEqual(creative['zura_hdr_hlg']['inputs']['source'],'HDR ACEScct')
        outpaint=sdr.build_hdr_graph(source='intermediate.mp4',start_frame=0,frame_count=9,fps=24,prefix='outpaint',_source_detail=False)
        self.assertNotIn('hdr_detail',outpaint)
        self.assertEqual(outpaint['zura_hdr_archive']['class_type'],'ZuraHDRPackageACEScct')
        self.assertEqual(outpaint['zura_hdr_hlg']['inputs']['image'],['hdr_unpad_raster',0])

    def test_preview_uses_final_acescg_and_hlg_agrees_with_actual_colour_node(self):
        convert=actual_colour_math()
        source=np.full((32,48,3),.5,np.float32)
        final,_,_=detail.ZuraHDRSourceDetail().reconstruct(torch.from_numpy(source[None]),torch.from_numpy(codes(source_linear(source)*4)[None]))
        display,=preview.ZuraHDRSDRPreview().preview(final,source_space='acescg')
        np.testing.assert_allclose(display[0],preview.acescg_sdr_preview(final[0].numpy()),rtol=1e-6,atol=1e-6)
        hlg=convert(final,'linear ACEScg','HDR')
        restored=convert(hlg,'HDR','linear ACEScg')
        torch.testing.assert_close(restored,final,rtol=1e-5,atol=1e-5)


if __name__=='__main__':unittest.main()
