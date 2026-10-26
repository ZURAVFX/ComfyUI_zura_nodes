import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from test_paintout_editor_store import editor, core, package

class MaskChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name)
        self.source=self.root/'source.mp4';self.source.write_bytes(b'fixture')
        self.identity=dict(path=str(self.source),fingerprint='source-v1',width=5,height=5,count=8)
        self.description=dict(path=str(self.source),width=5,height=5,count=8,kind='video')
        browser=types.ModuleType(package.__name__+'.browser');browser.checked_path=lambda value:pathlib.Path(value).resolve(strict=True);browser.grant=lambda value:'/candidate/'+pathlib.Path(value).name
        self.patches=[patch.object(editor,'project_root',return_value=self.root/'projects'),patch.dict('sys.modules',{package.__name__+'.browser':browser}),patch.object(core,'describe',return_value=self.description),patch.object(editor,'source_identity',return_value=self.identity)]
        for item in self.patches:item.start()
        self.project=editor.save_project(data={'draft':{'source':str(self.source)}})
        self.id=self.project['id'];self.masks=np.zeros((2,2,2),np.float32);self.masks[0,0,0]=1;self.masks[1,1,1]=1
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()
    def choices(self):
        return editor.save_mask_choices(self.id,self.identity,2,self.masks,'replace',editor.load_project(self.id)['revision'])
    def choose(self,selection,**overrides):
        return editor.choose_mask_candidate(dict(project=self.id,token=selection['token'],index=1,source=str(self.source),frame=2,expected_revision=editor.load_project(self.id)['revision'],**overrides))
    def test_candidates_do_not_change_project_and_remain_separate_hard_masks(self):
        before=editor.load_project(self.id);selection=self.choices()
        self.assertEqual(editor.load_project(self.id),before)
        first=np.asarray(Image.open(selection['choices'][0]['path']));second=np.asarray(Image.open(selection['choices'][1]['path']))
        self.assertEqual(first.shape,(5,5));self.assertLessEqual(set(np.unique(first)),{0,255});self.assertFalse((first&second).any())
    def test_choice_commits_only_one_subject_and_keeps_neighbour_and_protection(self):
        saved=editor.commit_mask_pass(self.id,self.identity,{0:np.ones((5,5))},'replace',1)
        protected=np.zeros((5,5));protected[:,4]=1
        editor.commit_mask_pass(self.id,self.identity,{2:protected},'protect',saved['project_revision'])
        selection=self.choices();doc=self.choose(selection)
        expected=np.asarray(Image.open(selection['choices'][1]['path']))/255;expected[:,4]=0
        np.testing.assert_array_equal(editor.read_project_mask(self.id,2),expected)
        np.testing.assert_array_equal(editor.read_project_mask(self.id,0),np.ones((5,5)))
        self.assertEqual(doc['mask_coverage'],[0,2])
        with self.assertRaises(editor.RevisionConflict):self.choose(selection)
    def test_changed_mask_or_stale_project_cannot_be_overwritten(self):
        selection=self.choices();editor.commit_mask_pass(self.id,self.identity,{4:np.ones((5,5))},'replace',1)
        with self.assertRaises(editor.RevisionConflict):self.choose(selection)
        fresh=self.choices()
        with self.assertRaises(editor.RevisionConflict):editor.choose_mask_candidate(dict(project=self.id,token=fresh['token'],index=0,source=str(self.source),frame=2,expected_revision=1))
    def test_other_source_frame_bad_index_and_path_escape_are_rejected(self):
        selection=self.choices()
        for changes in ({'frame':3},{'index':99},{'index':True},{'token':'../escape'}):
            body=dict(project=self.id,token=selection['token'],index=0,source=str(self.source),frame=2,expected_revision=1);body.update(changes)
            with self.assertRaises(ValueError):editor.choose_mask_candidate(body)
        with patch.object(editor,'source_identity',return_value={**self.identity,'fingerprint':'changed'}):
            with self.assertRaises(ValueError):self.choose(selection)
        self.assertIsNone(editor.load_project(self.id)['mask_revision'])
    def test_bad_candidate_shape_and_nonfinite_are_rejected_without_directories(self):
        for masks in (np.zeros((25,2,2)),np.full((2,2,2),np.nan),np.zeros((2,2))):
            with self.assertRaises(ValueError):editor.save_mask_choices(self.id,self.identity,2,masks,'replace',1)
        self.assertFalse((editor.project_dir(self.id)/'selections').exists())
    def test_native_multiple_detection_returns_choices_without_committing(self):
        import torch
        node=types.SimpleNamespace(execute=lambda **kwargs:(torch.from_numpy(self.masks),))
        nodes=types.SimpleNamespace(NODE_CLASS_MAPPINGS={'SAM3_Detect':node})
        with patch.dict('sys.modules',{'nodes':nodes}),patch.object(editor,'_frame_batch',return_value=torch.zeros((1,2,2,3))):
            result=editor.ZuraPaintoutMaskPass().run(str(self.source),self.id,2,2,1,'srgb_display','replace',text='person',model=object(),conditioning=[[torch.zeros((1,1,1)),{}]],expected_revision=1)
        self.assertEqual(len(result['ui']['zura_mask_choices'][0]['choices']),2)
        self.assertEqual(result['result'][0]['kind'],'selection_required')
        self.assertIsNone(editor.load_project(self.id)['mask_revision'])

if __name__=='__main__':unittest.main()
