"""Validate release metadata and distributable assets without loading models."""
import ast
import json
import os
from pathlib import Path
import tomllib
os.chdir(Path(__file__).resolve().parents[1])
metadata = tomllib.loads(Path('pyproject.toml').read_text())
version = metadata['project']['version']
tag = os.environ.get('RELEASE_TAG', '')
if tag and tag != f'v{version}':
    raise SystemExit(f'Release tag {tag} must match v{version} in pyproject.toml')
assert metadata['tool']['comfy']['PublisherId'] == 'zuravfx'
assert metadata['project']['name'] == 'comfyui-zura-nodes'
tree = ast.parse(Path('__init__.py').read_text(encoding='utf-8'))
module_version = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets))
assert version == module_version, 'Update __version__ as well as pyproject.toml'
assert Path('LICENSE').is_file()
assert Path('THIRD_PARTY_NOTICES.md').is_file()
for asset in ('paintout/__init__.py', 'paintout/paintout.py', 'paintout/media.py', 'paintout/browser.py', 'paintout/attention.py', 'web/paintout.js', 'web/studio_paintout.js', 'web/studio_paintout.css', 'web/paintout_recipes.js', 'PAINTOUT.md'):
    assert Path(asset).is_file(), f'Missing paintout release asset: {asset}'
for asset in ('studio_launchers.py', 'web/studio_launchers.js', 'web/studio_launchers.css',
              'paintout/editor_store.py', 'paintout/editor_routes.py',
              'paintout/frame_editor.py', 'paintout/import_review.py',
              'web/paintout_studio/paintout_app.js',
              'web/paintout_studio/paintout_shared.js',
              'web/paintout_studio/paintout_integrated.css',
              'web/paintout_studio/paintout_editor.js',
              'web/paintout_studio/paintout_editor.css',
              'web/paintout_studio/assets/fonts/Manrope-Variable.ttf',
              'web/paintout_studio/assets/fonts/Manrope-OFL.txt',
              'web/paintout_studio/assets/icons/Lucide-LICENSE.txt',
              'PAINTOUT_STUDIO_TESTING.md', 'PAINTOUT_THIRD_PARTY_NOTICES.md',
              'docs/paintout-studio/MODEL_DOWNLOADS.md'):
    assert Path(asset).is_file(), f'Missing Paintout Studio release asset: {asset}'
assert Path('web/v2_media_picker.js').is_file()
studio_loader = Path('web/studio.js').read_text(encoding='utf-8')
for asset in ('web/studio_create.js', 'web/studio_create.css',
              'web/studio_composer.js', 'web/studio_composer.css',
              'web/studio_frames.js', 'web/frame_video_recipes.js',
              'web/video_recipe_catalog.js', 'web/wan_frame_video_recipes.js',
              'web/ltx_frame_video_recipes.js', 'web/reference_video_recipes.js',
              'web/studio_references.js', 'web/studio_popovers.js',
              'web/studio_resolution.js', 'docs/FASTH3_DRAFT.md',
              'web/studio_live_preview.js', 'artist_studio/live_preview.py',
              'artist_studio/opening_subject.py',
              'web/image_recipes.js',
              'web/studio_components.css',
              'web/vendor/studio-components.css',
              'web/vendor/studio-components.js',
              'web/vendor/studio-components.js.LEGAL.txt',
              'licenses/daisyui-LICENSE.txt',
              'licenses/tailwindcss-LICENSE.txt',
              'licenses/webawesome-LICENSE.md'):
    assert Path(asset).is_file(), f'Missing Studio component release asset: {asset}'
for import_path in ('./studio_create.js', './studio_create.css',
                    './studio_components.css', './vendor/studio-components.css',
                    './vendor/studio-components.js'):
    assert import_path in studio_loader, f'Studio does not load packaged UI asset: {import_path}'
for asset in ('web/multicam_angle_gallery.js', 'web/anyangle_english.js', 'multicam_v3.py',
              'multicam_v4_clean.py', 'h3_single_angle.py',
              'idv2v_control.py', 'klein_look.py'):
    assert Path(asset).is_file(), f'Missing multicam release asset: {asset}'
for asset in ('wan_artist.py', 'web/studio.js', 'web/studio.css', 'web/studio_trim.js',
              'artist_studio/__init__.py', 'artist_studio/studio.py',
              'artist_studio/h3.py', 'artist_studio/wan.py', 'artist_studio/wan_speech.py',
              'artist_studio/mask_selection.py', 'artist_studio/text_removal.py',
              'artist_studio/enhancement.py',
              'artist_studio/speech.py', 'artist_studio/speech_latentsync.py',
              'artist_studio/latentsync_vendor/NOTICE.md',
              'artist_studio/latentsync_vendor/LICENSE-LatentSync',
              'artist_studio/latentsync_vendor/LICENSE-Whisper',
              'artist_studio/latentsync_vendor/mask.png',
              'artist_studio/latentsync_vendor/unet_config.json',
              'artist_studio/latentsync_vendor/scheduler_config.json',
              'artist_studio/latentsync_vendor/models/unet.py',
              'artist_studio/latentsync_vendor/models/unet_blocks.py',
              'artist_studio/latentsync_vendor/models/attention.py',
              'artist_studio/latentsync_vendor/models/motion_module.py',
              'artist_studio/latentsync_vendor/models/resnet.py',
              'artist_studio/latentsync_vendor/models/utils.py',
              'artist_studio/latentsync_vendor/audio/encoder.py',
              'artist_studio/latentsync_vendor/audio/mel.py',
              'artist_studio/latentsync_vendor/audio/assets/mel_filters.npz',
              'artist_studio/voice.py', 'artist_studio/signals.py',
              'web/artist_graph.js', 'web/graph_routing.js', 'web/vendor/elk.bundled.js', 'web/vendor/ELK-LICENSE.md',
              'setup_speech.py', 'Setup_Speech_Windows.cmd',
              'setup_wan_speech.py', 'Setup_Wan_Speech_Windows.cmd',
              'setup_h3_enhancement.py', 'Setup_H3_Enhancement_Windows.cmd',
              'workflows/Image - Build a Starting Frame.json', 'workflows/Image - Build a Starting Frame (3 References).json',
              'workflows/Image - Use a Finished Starting Frame.json',
              'ARTIST_STUDIO.md', 'ARTIST_STUDIO_VALIDATION.md', 'Open_Zura_Studio.url'):
    assert Path(asset).is_file(), f'Missing artist studio asset: {asset}'
for asset in ('artist_studio/ltx25.py', 'artist_studio/opening.py', 'artist_studio/appearance.py', 'artist_studio/hardware.py', 'INSTALL_STUDIO.md',
              'artist_studio/wan21_relight.py', 'tests/test_wan21_relight.py',
              'artist_studio/wan_parts.py', 'artist_studio/wan_graph.py', 'artist_studio/wan_graph_guard.py',
              'artist_studio/h3_windows.py', 'artist_studio/h3_window_nodes.py',
              'artist_studio/cut_tracking.py', 'wan_preparation_runtime.py',
              'wan_preparation_parts.py', 'wan_preparation_windows.py', 'wan_preparation_merge.py',
              'wan_bounded_speech.py', 'streaming_video.py', 'bounded_video_audio.py',
              'h3_control_data.py', 'h3_reference_data.py', 'video_latent_data.py',
              'studio_mask_cleanup.py', 'web/wan_graph.js',
              'tests/test_ltx25_native_plan.py', 'tests/test_ltx25_studio_runtime.py',
              'tests/test_studio_opening.py', 'tests/test_wan_bounded_guard.py',
              'tests/test_wan_parts_graph.py', 'tests/test_wan_preparation_parts.py',
              'tests/test_wan_preparation_windows.py', 'tests/test_wan_preparation_merge.py',
              'tests/test_wan_streaming.py', 'tests/test_wan_graph.py',
              'tests/test_wan_graph_integration.py', 'tests/test_bounded_video_audio.py',
              'tests/test_h3_control_data.py', 'tests/test_h3_reference_data.py',
              'tests/test_h3_windows.py', 'tests/test_h3_window_nodes.py',
              'tests/test_video_latent_data.py', 'tests/test_cut_tracking.py',
              'tests/test_studio_mask_cleanup.py', 'tests/test_wan_graph.mjs'):
    assert Path(asset).is_file(), f'Missing bounded Studio release asset: {asset}'
for graph in Path('artist_studio/graphs').glob('*.json'):
    assert json.loads(graph.read_text()), f'Invalid native graph: {graph}'
for filename in ('Video - Change Camera (H3).json',
                 'Video - Multicam (H3 Advanced).json'):
    text = Path('workflows', filename).read_text(encoding='utf-8')
    workflow = json.loads(text)
    assert workflow.get('nodes') and workflow.get('definitions', {}).get('subgraphs')
    assert 'example_performance.mp4' in text
    assert '2026-09-18' not in text
    assert not any(item in text for item in ('ComfyUI-Shared', 'C:\\\\Users', 'ellio'))
    assert not any(ext in text.lower() for ext in ('data:image/', 'data:video/', 'base64,'))
workflow = json.loads(Path('workflows/Video - Replace a Character (Wan 2.2).json').read_text())
expected = {'TrendStudioV2DrivingClip', 'TrendStudioV2MaskPerformer', 'TrendStudioV2Render', 'TrendStudioV2Speed'}
assert expected <= {n['type'] for n in workflow['nodes']}
prompt_workflow = json.loads(Path('workflows/Utility - Improve a Prompt (Gemma 4).json').read_text())
prompt_text = json.dumps(prompt_workflow)
assert 'example_reference.png' in prompt_text
assert '00.png' not in prompt_text
assert not any(ext in prompt_text.lower() for ext in ('data:image/', 'data:video/', 'base64,'))
for filename, placeholders in {
    'Reference - Mask and Roto (SAM3).json': ('example_source.mp4',),
    'Reference - Head and Face Swap (H3).json': ('example_driving_video.mp4', 'example_character.png'),
    'Reference - Speedboost Comparison (H3).json': ('example_reference.png',),
}.items():
    text = Path('workflows', filename).read_text(encoding='utf-8')
    assert all(item in text for item in placeholders)
    assert not any(item in text for item in ('ComfyUI-Shared', 'Gurkhas', 'Scouser Starter', 'Codex Image'))
    assert not any(ext in text.lower() for ext in ('data:image/', 'data:video/', 'base64,'))
for asset in ('longcat.py', 'setup_longcat.py', 'Setup_LongCat_Windows.cmd',
              'LONGCAT.md', 'longcat_runtime/worker.py',
              'longcat_runtime/text.py', 'longcat_runtime/requirements.txt'):
    assert Path(asset).is_file(), f'Missing LongCat release asset: {asset}'
assert not list(Path('.').rglob('longcat.local.json*'))
for asset in ('audio_dialogue.py', 'audio_parakeet.py', 'dialogue_edit.py',
              'dialogue_signals.py', 'web/audio_dialogue_editor.js',
              'web/dialogue_editor.js', 'web/dialogue_transcript.js',
              'web/dialogue_face_picker.js', 'DIALOGUE_EDITING.md'):
    assert Path(asset).is_file(), f'Missing dialogue editor asset: {asset}'
assert not list(Path('.').rglob('parakeet.local.json*'))
for filename in ('Audio - Replace Speech (LongCat).json', 'Video - Replace Speech (LTX INT8).json'):
    text = Path('workflows', filename).read_text(encoding='utf-8')
    graph = json.loads(text)
    assert len(graph['nodes']) == (4 if filename == 'Audio - Replace Speech (LongCat).json' else 3) and graph['definitions']['subgraphs']
    assert not any(item in text for item in ('ComfyUI-Shared', 'C:\\\\Users', 'ellio', 'pound_euro_original', 'zuraAudioPreview', 'zuraDialoguePreview', 'base64,'))
for asset in ('qwen_voice_design.py', 'setup_voice_design.py', 'VOICE_DESIGN.md',
              'Setup_Voice_Design_Windows.cmd', 'voice_design_runtime/qwen_voice_worker.py',
              'voice_design_runtime/requirements.txt'):
    assert Path(asset).is_file(), f'Missing VoiceDesign release asset: {asset}'
assert not list(Path('.').rglob('qwen_voice_design.local.json*'))
# Registry metadata and pip requirements describe the same base environment.
requirements = {
    line.strip() for line in Path('requirements.txt').read_text().splitlines()
    if line.strip() and not line.lstrip().startswith('#')
}
assert requirements == set(metadata['project']['dependencies']), 'Python dependency manifests differ'
catalogue = json.loads(Path('template_catalogue.json').read_text(encoding='utf-8'))
for entry in catalogue['templates']:
    text = Path('workflows', entry['file']).read_text(encoding='utf-8')
    assert json.loads(text)['nodes'], f'Empty workflow: {entry["file"]}'
    assert not any(marker in text.lower() for marker in ('data:image/', 'data:audio/', 'data:video/', 'base64,')), f'Embedded media: {entry["file"]}'
print(f'Package checks passed for Zura Nodes {version}')
