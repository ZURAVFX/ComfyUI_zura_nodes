"""Original/reference performance contracts; no inference or provider calls."""
import copy
import hashlib
import importlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import v2_bootstrap

NAME = 'ComfyUI_zura_nodes.artist_studio'
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / 'artist_studio')]
    sys.modules[NAME] = package
package = sys.modules[NAME]
studio = importlib.import_module(NAME + '.studio')
wan = importlib.import_module(NAME + '.wan')
h3 = importlib.import_module(NAME + '.h3')
wan_speech = importlib.import_module(NAME + '.wan_speech')


class AudioModeTests(unittest.TestCase):
    def project(self, engine='local'):
        return {'id': 'a' * 32, 'source': {'sha': 'source', 'file': 'source.mp4'},
            'character': {'sha': 'character', 'file': 'character.png'},
            'config': studio.clean_config({'engine': engine, 'duration': 3}),
            'review': 'shot_' + 'a' * 16, 'opening_key': 'look',
            'opening_approval': 'look', 'opening_input': {'sha': 'look', 'file': 'opening.png'},
            'phase': 'opening', 'actions': []}

    def audio(self):
        return {'id': 'b' * 32, 'asset_kind': 'audio', 'file': 'reference.wav', 'sha': 'voice'}

    def controller(self, directory):
        obj = studio.Studio.__new__(studio.Studio)
        obj.store = studio.Store(directory)
        obj.collect = lambda p: p
        return obj

    def test_original_defaults_disable_new_speech_for_every_engine(self):
        for engine in ('local', 'h3', 'wan', 'seedance'):
            config = studio.clean_config({'engine': engine, 'lip_sync': True, 'refine_lips': True})
            self.assertEqual(config['audio_id'], '')
            self.assertFalse(config['lip_sync'])
            self.assertFalse(config['refine_lips'])

    def test_switching_back_to_original_remembers_reference_across_reload(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(studio, 'check_asset'):
            obj = self.controller(directory)
            audio = self.audio()
            obj.store.save(audio)
            p = self.project()
            obj.configure(p, {**p['config'], 'audio_id': audio['id'], 'lip_sync': True})
            self.assertEqual(p['audio']['id'], audio['id'])
            obj.configure(p, {**p['config'], 'audio_id': '', 'lip_sync': True, 'refine_lips': True})
            restored = obj.store.load(p['id'])
            self.assertIsNone(restored['audio'])
            self.assertEqual(restored['reference_audio']['id'], audio['id'])
            self.assertFalse(restored['config']['lip_sync'])
            self.assertFalse(restored['config']['refine_lips'])
            obj.configure(restored, {**restored['config'], 'audio_id': audio['id'], 'lip_sync': True})
            self.assertEqual(restored['audio']['id'], audio['id'])
            self.assertTrue(restored['config']['lip_sync'])

    def test_reference_memory_does_not_reset_unchanged_finished_legacy_project(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(studio, 'check_asset'):
            obj = self.controller(directory)
            p = self.project()
            p['phase'] = 'done'
            for key in ('audio_id', 'audio_start', 'length_mode'):
                p['config'].pop(key)
            obj.configure(p, dict(p['config']))
            self.assertEqual(p['phase'], 'done')

    def test_legacy_active_reference_migrates_without_resetting_finished_take(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(studio, 'check_asset'):
            obj = self.controller(directory)
            audio = self.audio()
            obj.store.save(audio)
            p = self.project()
            p.update(audio=audio, phase='done')
            p['config'].update(audio_id=audio['id'], lip_sync=True)
            p['config'].pop('audio_id')
            exposed = studio.public_project(p)
            self.assertEqual(exposed['config']['audio_id'], audio['id'])
            obj.configure(p, exposed['config'])
            self.assertEqual(p['phase'], 'done')
            self.assertEqual(p['reference_audio']['id'], audio['id'])

    def test_remembered_audio_is_exposed_without_becoming_the_active_input(self):
        p = self.project()
        p['reference_audio'] = self.audio()
        before = copy.deepcopy(p)
        exposed = studio.public_project(p)
        self.assertIn('url', exposed['reference_audio'])
        self.assertNotIn('audio', exposed)
        self.assertEqual(p, before)
        with patch.object(studio, 'check_asset'):
            graph = studio.build_graph(p, 'prepare')
        self.assertNotIn('zura_reference_audio', graph)
        self.assertNotIn('audio', graph['3']['inputs'])

    def test_old_text_review_refreshes_only_when_artist_continues_the_shot(self):
        p = self.project()
        p['config']['remove_text'] = True
        legacy_settings = {'source': p['source']['sha'],
            **{key: p['config'][key] for key in studio.PREP_KEYS}, 'remove_text': 1}
        legacy_key = hashlib.sha256(studio.canonical(legacy_settings).encode()).hexdigest()
        self.assertNotEqual(studio.prep_key(p), legacy_key)
        p.update(phase='done', prepared_key=legacy_key, approval=legacy_key,
                 results=[{'url': 'previous-take.mp4'}])
        before = copy.deepcopy(p)
        self.assertEqual(studio.public_project(p)['phase'], 'done')
        self.assertEqual(p, before, 'Reading a finished take must not migrate saved state')
        with tempfile.TemporaryDirectory() as directory, patch.object(studio, 'check_asset'):
            self.controller(directory).configure(p, dict(p['config']))
        self.assertEqual(p['phase'], 'new')
        self.assertIsNone(p['review'])
        self.assertIsNone(p['approval'])
        self.assertEqual(p['results'], before['results'], 'Existing takes stay available')

    def test_current_text_review_does_not_request_repeated_preparation(self):
        p = self.project()
        p['config']['remove_text'] = True
        p.update(phase='done', prepared_key=studio.prep_key(p), approval=studio.prep_key(p))
        with tempfile.TemporaryDirectory() as directory, patch.object(studio, 'check_asset'):
            self.controller(directory).configure(p, dict(p['config']))
        self.assertEqual(p['phase'], 'done')
        self.assertIsNotNone(p['review'])

    def test_original_and_reference_preparation_select_the_right_soundtrack(self):
        p = self.project()
        with patch.object(studio, 'check_asset'):
            original = studio.build_graph(p, 'prepare')
            p['audio'] = self.audio()
            p['config'].update(audio_id='b' * 32, audio_start=1.25, lip_sync=True)
            reference = studio.build_graph(p, 'prepare')
        self.assertNotIn('zura_reference_audio', original)
        self.assertEqual(reference['zura_reference_audio']['inputs']['audio'], 'reference.wav')
        self.assertEqual(reference['3']['inputs']['audio'], ['zura_reference_audio', 0])
        self.assertEqual(reference['3']['inputs']['audio_start_seconds'], 1.25)

    def graph(self, engine, reference=False, speech=True):
        p = self.project(engine)
        p['reference_audio'] = self.audio()
        if reference:
            p['audio'] = self.audio()
            p['config'].update(audio_id='b' * 32, lip_sync=speech)
        package.verify_review = lambda _: (None, {'clip': {'frames': 72, 'duration': 3}})
        package.text_cache_path = lambda _: Path('/nonexistent-audio-test-cache')
        with patch.object(studio, 'assert_approved'), patch.object(studio, 'check_asset'), \
                patch.object(studio, 'text_cache_info', return_value=('test-cache', {})), \
                patch.object(wan, 'cache_key', return_value='c' * 64), \
                patch.object(wan_speech, 'guide_ready', return_value=True), \
                patch.object(wan_speech, 'load_guide', return_value={'path': '/synthetic-guide.mp4',
                    'key_data': {'source': {'frames': 72}}}), \
                patch.object(h3, 'cache_key', return_value='d' * 64):
            if engine == 'seedance':
                return studio.editable_graph(p, 'draft')[0]
            return studio.editable_graph(p, 'animate')[0]

    def test_original_mode_keeps_native_performance_without_new_face_generation(self):
        for engine in ('local', 'h3', 'wan', 'seedance'):
            with self.subTest(engine=engine):
                graph = self.graph(engine)
                self.assertNotIn('zura_reference_audio', graph)
                self.assertFalse(any(n['class_type'] in ('ZuraSpeechFaceGuide',
                    'ZuraSpeechModelLoader', 'ZuraSpeechComposeVideo') for n in graph.values()))
                if engine == 'wan':
                    self.assertEqual(graph['wan_cached']['inputs']['face'], ['wan_pose_detect', 1])
                    self.assertNotIn('Ignore the original dialogue', graph['wan_render']['inputs']['prompt'])
                elif engine == 'h3':
                    # Original audio (including silence) is preserved by the
                    # native stream lock; it does not synthesize a new face guide.
                    self.assertEqual(graph['h3_locked_audio']['inputs']['audio'], ['h3_pad', 2])
                    self.assertNotIn('replacement audio', graph['h3_prompt']['inputs']['value'])
                elif engine == 'local':
                    self.assertEqual(graph['zura_fixed_audio_mask']['inputs']['value'], 0.0)
                    self.assertNotIn('replacement dialogue', graph['5404']['inputs']['value'])

    def test_reference_audio_drives_available_speech_path_without_manual_words(self):
        for engine in ('local', 'h3', 'wan', 'seedance'):
            with self.subTest(engine=engine):
                graph = self.graph(engine, reference=True)
                if engine != 'seedance':
                    self.assertEqual(graph['zura_audio_selection']['inputs']['audio'], ['zura_reference_audio', 0])
                    self.assertEqual(graph['zura_reference_audio']['inputs']['audio'], 'reference.wav')
                if engine == 'wan':
                    self.assertEqual(graph['wan_cached']['inputs']['face'], ['wan_speech_face_detect', 1])
                    self.assertEqual(graph['wan_speech_video']['inputs']['force_rate'], 24.0)
                    self.assertEqual(graph['wan_speech_video']['inputs']['format'], 'None')
                    self.assertFalse(any(n['class_type'] == 'ZuraSpeechFaceGuide' for n in graph.values()))
                elif engine == 'h3':
                    self.assertEqual(graph['h3_locked_audio']['inputs']['audio'], ['h3_pad', 2])
                elif engine == 'local':
                    self.assertIn('replacement dialogue', graph['5404']['inputs']['value'])
                else:
                    self.assertTrue(any(n['class_type'] == 'ZuraSpeechFaceGuide' for n in graph.values()))
                self.assertFalse(any(name in ('transcript', 'script', 'dialogue_text')
                    for n in graph.values() for name in n['inputs']))

    def test_soundtrack_only_does_not_request_speech_guides_or_refinement(self):
        for engine in ('local', 'h3', 'wan', 'seedance'):
            with self.subTest(engine=engine):
                graph = self.graph(engine, reference=True, speech=False)
                self.assertFalse(any(n['class_type'] in ('ZuraSpeechFaceGuide',
                    'ZuraSpeechModelLoader', 'ZuraSpeechComposeVideo') for n in graph.values()))

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for the frontend contract')
    def test_frontend_mode_selects_original_or_reference_for_every_engine(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let source=fs.readFileSync(process.argv[1],'utf8').split('\napp.registerExtension({')[0];
source=source.replace(/^import .*;\r?\n/gm,'');
const context={console,document:{createElement:()=>({setAttribute(){}})}};
vm.createContext(context);vm.runInContext(source+'\nthis.Studio=ArtistStudio;',context);
const proto=context.Studio.prototype;
for(const engine of ['local','h3','wan','seedance']){
 const ui=Object.create(proto),fields={};
 ui.config={size:512,lip_sync:true,refine_lips:true};ui.audio={id:'b'.repeat(32)};
 for(const [name,value] of Object.entries({scope:'person',background:'keep',prompt:'',length_mode:'custom',start:0,duration:3,resolution:1280,performer:-1,margin:8,seed:42,audio_start:1.25,quality:'fast','audio-mode':'original'}))fields[name]={value};
 fields.pitch={checked:false};fields.remove_text={checked:false};fields.lip_sync={checked:true};fields.refine_lips={checked:true};
 ui.$=name=>fields[name];ui.container={querySelector:()=>({value:engine})};
 let selected=ui.readConfig();assert.equal(selected.audio_id,'');assert.equal(selected.audio_start,0);assert.equal(selected.lip_sync,false);assert.equal(selected.refine_lips,false);
 fields['audio-mode'].value='reference';selected=ui.readConfig();assert.equal(selected.audio_id,'b'.repeat(32));assert.equal(selected.lip_sync,true);assert.equal(selected.audio_start,1.25);
 fields.lip_sync.checked=false;selected=ui.readConfig();assert.equal(selected.audio_id,'b'.repeat(32));assert.equal(selected.lip_sync,false);assert.equal(selected.refine_lips,false);
 ui.audio=null;let caught;ui.perform=async fn=>{try{await fn();}catch(e){caught=e.message;}};
 ui.primary().then(()=>assert.equal(caught,'Choose or create a reference audio track first.'));
}
proto.bind=function(){};proto.syncForm=function(){};
const html=new context.Studio().container.innerHTML;
assert(html.includes('Original audio + performance'));assert(html.includes('Reference audio + new performance'));assert(html.includes('Create a new facial performance'));
console.log('Frontend original/reference/soundtrack contracts passed for four engines.');
'''
        result = subprocess.run([shutil.which('node'), '-e', script,
            str(v2_bootstrap.ROOT / 'web/studio.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
