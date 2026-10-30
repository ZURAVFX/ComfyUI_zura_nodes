"""H3 Studio adapters must not silently shorten a requested source interval."""
import types
import unittest
from unittest.mock import MagicMock, patch

import test_h3_camera as camera_fixture
import test_h3_head_swap as head_fixture
import test_h3_frame_anchors as viewport_fixture


def media(seconds):
    stream=types.SimpleNamespace(duration=seconds,time_base=1)
    container=MagicMock()
    container.__enter__.return_value=types.SimpleNamespace(
        streams=types.SimpleNamespace(video=[stream],audio=[object()]))
    return container


class H3SourceRangeTests(unittest.TestCase):
    def test_camera_and_head_swap_reject_a_range_past_the_source(self):
        project={'id':'a'*32,'source':{'file':'source.mp4'},'references':[],
                 'config':{'length_mode':'custom','start':.5,'duration':1.75}}
        for build in (camera_fixture.camera._request,head_fixture.head._selection):
            with self.subTest(adapter=build.__name__),patch('av.open',return_value=media(2.24)):
                with self.assertRaisesRegex(ValueError,'shorter range'):
                    build(project,lambda asset:asset['file'])
        project['config']['duration']=1.5
        with patch('av.open',return_value=media(2.24)):
            self.assertEqual(camera_fixture.camera._request(project,lambda asset:asset['file']).duration_seconds,1.5)
        with patch('av.open',return_value=media(2.24)):
            self.assertEqual(head_fixture.head._selection(project,lambda asset:asset['file'])[2],36)

    def test_viewport_rejects_a_range_past_the_source(self):
        fixture=viewport_fixture.H3FinishedFrameAnchorTests()
        project=fixture.viewport_project(ready=False)
        project['config'].update(start=.5,duration=1.75,length_mode='custom')
        with patch.object(viewport_fixture.studio,'assert_approved'), \
             patch.object(viewport_fixture.studio,'check_asset'), \
             patch('av.open',return_value=fixture.media_container(2.24)):
            with self.assertRaisesRegex(ValueError,'shorter range'):
                viewport_fixture.h3.build_h3_graph(project,use_cache=False)


if __name__=='__main__':unittest.main()
