"""Browser starting-frame routing without account access or generation."""
import importlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import test_artist_studio as fixture

s = fixture.studio
models = importlib.import_module(s.__package__ + '.opening_models')
camera = importlib.import_module(s.__package__ + '.h3_camera')
spec = importlib.util.spec_from_file_location('browser_prompt_test', Path(s.__file__).parents[1] / 'chatgpt_image.py')
prompts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prompts)


class BrowserOpeningTests(unittest.TestCase):
    def project(self, provider='chatgpt', mode='relight', engine='h3', custom=False):
        p = fixture.SharedEngineTests().project()
        p.update(look_mode='build', references=[] if mode=='relight' else [p['character']])
        p['config'] = s.clean_config({**p['config'], 'engine':engine, 'workflow_mode':mode,
            'opening_model':provider, 'image_prompt':'Warm afternoon light' if mode=='relight' else 'Replace only the centre character',
            'h3_viewport_direct':False, 'openjutsu_direct':False,
            **({'opening_width':1136,'opening_height':1760} if custom else {})})
        return p

    def graph(self, p):
        with patch.object(s,'assert_approved'), patch.object(s,'check_asset'):
            return s.build_graph(p,'design',use_cache=False)

    def assert_links(self, graph):
        for key, node in graph.items():
            for name, value in node.get('inputs',{}).items():
                if isinstance(value,list) and len(value)==2 and isinstance(value[0],str):
                    self.assertIn(value[0], graph, f'{key}.{name} has a dangling connection')

    def test_relight_original_frame_no_local_models_or_mask(self):
        for provider,node in [('chatgpt','ZuraChatGPTImage'),('gemini','ZuraGeminiImage')]:
            with self.subTest(provider=provider):
                graph=self.graph(self.project(provider))
                self.assertEqual(graph['92:105']['class_type'],node)
                inputs=graph['92:105']['inputs']
                self.assertEqual(inputs['reference_1'],['125',0])
                self.assertEqual(inputs['custom_width'],['zura_original_size',0])
                self.assertIn('Relight the first image only',inputs['prompt'])
                self.assertIn('Do not change the proportions',inputs['prompt'])
                self.assertEqual(graph['zura_original_video']['inputs']['file'],'source.mp4')
                self.assertFalse(any(any(token in n['class_type'] for token in ('Loader','Sampler','VAE','SAM3')) for n in graph.values()))
                self.assertEqual(graph['zura_opening_original_resolution']['inputs']['crop'],'disabled')
                self.assertEqual(graph['zura_opening_original_resolution']['inputs']['width'],['zura_original_size',0])
                self.assert_links(graph)

    def test_exact_prompt_dimensions_and_ordered_appearance_references(self):
        p=self.project(custom=True)
        p['references']=[{'file':'lighting.png'}, {'file':'second.png'}]
        graph=self.graph(p)
        inputs=graph['92:105']['inputs']
        self.assertEqual((inputs['custom_width'],inputs['custom_height']),(1136,1760))
        text=prompts._prompt(inputs['prompt'],inputs['size'],inputs['custom_width'],inputs['custom_height'])
        self.assertIn('1136:1760 aspect ratio, targeting 1136 x 1760 pixels if possible.',text)
        self.assertIn('Do not change the proportions of Image 1 at all',text)
        self.assertEqual(graph[inputs['reference_2'][0]]['inputs']['image'],'lighting.png')
        self.assertEqual(graph[inputs['reference_3'][0]]['inputs']['image'],'second.png')
        self.assert_links(graph)

    def test_character_viewport_and_retries_keep_original_source(self):
        for engine,mode in [('wan','swap'),('wan2','motion'),('h3','swap'),('h3','viewport'),('local','motion')]:
            with self.subTest(engine=engine,mode=mode):
                p=self.project('gemini',mode,engine)
                graph=self.graph(p)
                p['opening_input']['file']='failed-generation.png'
                self.assertEqual(self.graph(p),graph)
                self.assertNotIn('failed-generation.png',str(graph))
                self.assertEqual(graph['92:105']['inputs']['reference_1'],['125',0])
                self.assert_links(graph)

    def test_camera_still_uses_browser_without_local_image_weights(self):
        p=self.project(mode='camera')
        request=camera.CameraRequest('source.mp4', source_path='source.mp4', width=768,height=448)
        with patch.object(camera,'_request',return_value=request),patch.object(s,'check_asset'):
            graph=s.build_graph(p,'design',use_cache=False)
        self.assertEqual(graph['still_decode']['class_type'],'ZuraChatGPTImage')
        self.assertEqual(graph['still_decode']['inputs']['reference_1'],['source_still_size',0])
        self.assertNotIn('still_model',graph)
        self.assertEqual(graph['zura_browser_camera_size']['inputs']['crop'],'center')
        self.assert_links(graph)

    def test_reference_limit_loras_and_readiness_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'seven appearance references'):
            models.browser_node('gemini','Edit', ['source',0],[{'file':'ref.png'}]*8,1136,1760)
        p=self.project()
        p['config']['opening_loras']=[{'name':'local.safetensors','strength':1}]
        with self.assertRaisesRegex(ValueError,'cannot use local image LoRAs'):
            self.graph(p)
        kinds={name:object for name in ('LoadImage','GetImageSize','SaveImage','ZuraChatGPTImage')}
        status=models.readiness(kinds,lambda *args:None)
        self.assertTrue(status['chatgpt']['ready'])
        self.assertFalse(status['gemini']['ready'])
        self.assertEqual(status['chatgpt']['model_files'],[])
        self.assertEqual(status['chatgpt']['provider'],'chatgpt')


if __name__=='__main__':
    unittest.main()
