import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_artist_studio  # establishes the package fixture

jobs_module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_jobs')

class OutpaintProgressRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_are_routed_to_the_requesting_client(self):
        import execution
        queued=[]; triggered=[]
        queue=SimpleNamespace(put=queued.append)
        server=SimpleNamespace(prompt_queue=queue, number=0,
            trigger_on_prompt=lambda payload: (triggered.append(payload) or payload),
            node_replace_manager=SimpleNamespace(apply_replacements=lambda graph: None))
        manager=jobs_module.OutpaintJobs(SimpleNamespace(server=server))
        async def validate(*args): return (True, None, ['save'], {})
        with patch.object(jobs_module, 'build_review_graph', return_value={'save': {}}), \
             patch.object(execution, 'validate_prompt', validate):
            job=await manager.submit('review', {}, {}, client_id='studio-client')
            self.assertEqual(triggered[0]['client_id'], 'studio-client')
            self.assertEqual(queued[0][1], job['id'])
            self.assertEqual(queued[0][3]['client_id'], 'studio-client')
            with self.assertRaisesRegex(ValueError, 'Invalid Studio connection'):
                await manager.submit('review', {}, {}, client_id='x'*129)

if __name__ == '__main__': unittest.main()
