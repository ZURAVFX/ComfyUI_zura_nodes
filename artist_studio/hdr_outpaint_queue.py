"""Private Comfy queue adapter for reviewed two-pass HDR outpainting."""
import asyncio
from pathlib import Path
import time
import uuid

from .hdr_outpaint_artifacts import checked_stage, checked_delivery
from .hdr_outpaint_runner import run_reviewed_hdr_outpaint


class ReviewedHDRQueue:
    def __init__(self, server, output_root, *, client_id, identity, selection, has_audio, update, on_prompt=lambda identity: None):
        if not isinstance(client_id, str) or not client_id or len(client_id) > 128:
            raise ValueError('Invalid Studio connection. Reload Studio and try again.')
        if not isinstance(identity, str) or not identity.isalnum() or len(identity) > 64:
            raise ValueError('Invalid HDR outpaint job identity.')
        self.server, self.root, self.client_id, self.identity = server, Path(output_root).resolve(), client_id, identity
        self.selection, self.has_audio, self.update, self.on_prompt = selection, has_audio, update, on_prompt
        self.started = {}
        self.owned_stage = None

    async def submit(self, stage, graph):
        import execution
        prompt_id = uuid.uuid4().hex
        submitted = self.server.trigger_on_prompt({'prompt': graph, 'prompt_id': prompt_id, 'client_id': self.client_id})
        graph = submitted['prompt']
        self.server.node_replace_manager.apply_replacements(graph)
        valid = await execution.validate_prompt(prompt_id, graph, None)
        if not valid[0]:
            details = '; '.join(e.get('message', '') for node in valid[3].values() for e in node.get('errors', []))
            raise ValueError('ComfyUI needs attention: ' + (details or str(valid[1]))[:1200])
        number = self.server.number
        self.server.number += 1
        self.started[prompt_id] = time.monotonic()
        self.server.prompt_queue.put((number, prompt_id, graph, {'client_id': self.client_id,
            'create_time': int(time.time() * 1000), 'comfy_usage_source': 'zura-studio'}, valid[2], {}))
        self.on_prompt(prompt_id)
        return prompt_id

    async def wait(self, stage, prompt_id):
        queue = self.server.prompt_queue
        while True:
            entry = queue.get_history(prompt_id).get(prompt_id)
            if entry:
                if entry.get('status', {}).get('status_str') != 'success':
                    errors = [message[1].get('exception_message', '') for message in entry.get('status', {}).get('messages', [])
                              if isinstance(message, (list, tuple)) and len(message) > 1 and message[0] == 'execution_error' and isinstance(message[1], dict)]
                    raise ValueError((errors[-1] if errors and errors[-1] else
                        'The HDR outpaint pass did not complete. Check ComfyUI for details.')[:1200])
                outputs = entry.get('outputs', {})
                count = self.selection['padded_frames']
                if stage == 'outpaint':
                    refs = outputs.get('stage_save', {}).get('images', [])
                    if not isinstance(refs, list) or len(refs) != 1:
                        raise ValueError('The outpaint pass did not return its intermediate video.')
                    path = await asyncio.to_thread(checked_stage, self.root, refs[0], self.identity,
                        width=self.selection['padded_width'], height=self.selection['padded_height'], frames=count)
                    self.owned_stage = path
                    return str(path)
                if stage != 'hdr':
                    raise ValueError('Unknown HDR outpaint pass.')
                return await asyncio.to_thread(checked_delivery, self.root, outputs, self.identity,
                    width=self.selection['width'] if self.selection.get('mode')=='black' else self.selection['padded_width'],
                    height=self.selection['height'] if self.selection.get('mode')=='black' else self.selection['padded_height'],
                    frames=count, has_audio=self.has_audio)
            running, pending = queue.get_current_queue_volatile()
            if (not any(item[1] == prompt_id for item in (*running, *pending)) and
                    time.monotonic() - self.started[prompt_id] > 20):
                raise ValueError('The HDR outpaint job is no longer in ComfyUI. It was not resubmitted.')
            await asyncio.sleep(.5)

    async def cancel(self, prompt_id):
        queue = self.server.prompt_queue
        queue.interrupt_if_running(prompt_id)
        queue.delete_queue_item(lambda item: item[1] == prompt_id)
        while True:
            running, pending = queue.get_current_queue_volatile()
            if not any(item[1] == prompt_id for item in (*running, *pending)):
                return
            await asyncio.sleep(.25)

    async def cleanup(self, intermediate):
        path = Path(intermediate).resolve()
        if self.owned_stage is not None and path == self.owned_stage:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            self.owned_stage = None

    async def run(self, *, source, review_key, colour_space, prompt, seed, check_asset):
        return await run_reviewed_hdr_outpaint(source=source, selection=self.selection, review_key=review_key,
            colour_space=colour_space, has_audio=self.has_audio, prompt=prompt, seed=seed, identity=self.identity,
            check_asset=check_asset, submit=self.submit, wait=self.wait, cancel=self.cancel,
            update=self.update, cleanup=self.cleanup)
