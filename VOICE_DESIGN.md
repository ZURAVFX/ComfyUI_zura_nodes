# Zura voice workflows — team guide

Both designed-TTS routes are included in Zura Nodes 1.2.0. Keep whichever take works best for the project; neither route is labelled an enhancement of the other.

## Choose a workflow

| Workflow file | What it does |
| --- | --- |
| `Zura_Voice_Design_Qwen_Direct.json` | Written voice description + final script → Qwen VoiceDesign → finished audio. |
| `Zura_Voice_Design_Qwen_to_LongCat.json` | Qwen creates a short reference; LongCat uses it to speak a separate final script. |
| `Zura_LongCat_Voice_Clone.json` | Use an approved existing real or designed voice recording, its transcript and a new script. |

The existing reference-free LongCat TTS workflow is also retained. It does not accept a written speaker description. See [LONGCAT.md](LONGCAT.md).

## Qwen Direct

Open the workflow. Describe the speaker and delivery in **voice_description**. Put only the words to speak in **script**, choose a language and project label, then click Run. Listen in Preview Audio; the WAV is already saved.

Example description: “An adult British woman with a warm medium-low voice, a light rasp, clear diction and a calm conversational delivery. Measured and reassuring, without exaggerated advertising intonation.”

The description is an instruction, not text to be spoken. Accents and subjective qualities are requests rather than guarantees. Keep the seed fixed to revisit a take, or randomise it for a different performance. Changing the script may also change speaker identity even with the same description and seed.

## Qwen → LongCat

Describe the voice in the Qwen node. **REFERENCE WORDS** supplies one shared short passage to Qwen's script and LongCat's reference transcript. Put the actual deliverable into LongCat's **FINAL SCRIPT** box. Run the workflow and audition both the reference and finished voiceover.

Qwen exits and releases its GPU memory before LongCat runs; both weights do not need to stay in VRAM together. The LongCat route is documented for English and Chinese. Direct Qwen exposes the ten languages supported by the upstream VoiceDesign checkpoint.

LongCat receives the generated recording and its transcript, not the written voice description. It makes a new performance. It is not an audio restoration, enhancement, or speech-to-speech conversion stage. Check that the generated reference really says the shared words before approving it for use.

### Reuse an approved designed voice

Within the same graph, changing only LongCat's final script reuses Qwen's cached reference when that cached result is still available. Keep Qwen's description, reference passage, language, seed and project label unchanged. Change its seed to create another reference. A ComfyUI restart or cache eviction may require regeneration.

For permanent campaign reuse, keep the approved Qwen run folder, especially `master_float32.wav`, `voice.wav`, `script.txt` and `voice_description.txt`. On later projects open **Zura_LongCat_Voice_Clone.json**, load the approved WAV, paste its exact spoken transcript, and enter the new script. Qwen is not needed for those subsequent renders. This also avoids depending on in-session caching or reproducibility across software versions.

Use a short, clean reference. Start with 8–20 seconds. LongCat's combined reference/generation window is 60 seconds; leave room for the new speech. Long scripts in the LongCat path are split and saved as individual chunks as well as a joined version.

## Output and limits

Both nodes save into the configured ComfyUI output directory under `zura_voice/Project_Date_Time_ID/`.

- `voice.wav`: 24-bit PCM delivery/listening copy, with a single gain reduction only if needed to prevent clipping.
- `master_float32.wav`: unprocessed float samples, also returned by Qwen to downstream cloning.
- `script.txt`, `job.json`, `report.json`, `worker.log`: text, settings and diagnostics. Qwen also saves `voice_description.txt`.

LongCat additionally saves chunks and the reference recording. These folders can contain private voice and client data; do not add them to source control or share them publicly.

Direct Qwen is tested on short scripts. Start with a few sentences. It currently makes one generation, with a 2048-token safety cap; it does not automatically split long scripts or verify the final words. Check the full read before delivery. For longer projects generate approved sections or use LongCat's chunked route. Neither model guarantees perfect pronunciations, stable emotion or identical speaker identity across all scripts.

Fixed Qwen inputs can return a cached result instead of creating another output folder. Change the seed for a new take. LongCat retains its existing behaviour of saving a new take each run. No EQ, denoising, pitch shift, time stretch or loudness mastering is applied by these nodes.

## One-time setup on a Windows workstation

Install/update **Zura Nodes** (`comfyui-zura-nodes`) to 1.2.0 or newer. If Registry availability is still pending, use the reviewed GitHub release instead. Do not overwrite an existing package that has unsaved local code changes.

1. Install `uv` if it is not available. Double-click **Setup_Voice_Design_Windows.cmd** in the installed Zura Nodes folder.
2. For LongCat routes, also run **Setup_LongCat_Windows.cmd** once; it requires Git and uv. Existing working LongCat installations can be reused.
3. Restart ComfyUI and open a workflow JSON from the package's `workflows` directory. Copy it into `ComfyUI/user/default/workflows` for a sidebar entry.

These are explicit installers, not automatic downloads when ComfyUI starts. Qwen setup creates a separate Python 3.11 environment in `~/ZuraVoiceDesign/.venv`, stages the pinned weights in the shared Hugging Face cache and writes `qwen_voice_design.local.json`. Existing cached weights are reused. No Qwen/Transformers dependency pins are added to ComfyUI's own environment.

Equivalent commands from the Zura Nodes folder:

```powershell
uv run --python 3.11 --no-project --no-config setup_voice_design.py --install
uv run --python 3.11 --no-project --no-config setup_voice_design.py --check
```

Use `--root D:\AI\ZuraVoiceDesign` to place the isolated environment elsewhere. The weight cache follows Hugging Face's standard `HF_HOME`/`HF_HUB_CACHE` settings. Setup pins the tested qwen-tts 0.1.1 runtime, Torch 2.8.0 CUDA 12.8, BF16 and PyTorch SDPA. It does not require compiling FlashAttention. CUDA with BF16 support is required. Runtime tests use Windows and an RTX 4080 16 GB; other GPU/OS combinations are not validated.

Machine configuration must not be copied between workstations or published. Both Git and Registry package rules exclude `qwen_voice_design.local.json*`. Back up machine configurations before replacing a package folder. Advanced users can place Qwen's configuration outside the package with `setup_voice_design.py --install --config <path>` and set `ZURA_QWEN_VOICE_DESIGN_CONFIG` to that same path. `--reuse-config <existing-path>` validates and reuses a local runtime without downloads.

Generation uses local files with Hugging Face/Transformers offline flags. It makes no hosted speech request. Stop/interrupt terminates the node's own worker process; logs and available outputs are retained. Close other GPU-heavy applications if memory is insufficient. Neither node can unload models held by a different application.

## Rights and source

The separately downloaded Qwen3-TTS code and VoiceDesign checkpoint use Apache-2.0; LongCat's code and checkpoint use MIT. Their upstream notices remain applicable. The existing Zura Nodes licence is unchanged. Obtain the necessary speaker, recording and script permissions for client projects.

- Qwen source and usage: https://github.com/QwenLM/Qwen3-TTS
- VoiceDesign checkpoint: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
- Pinned checkpoint revision: `5ecdb67327fd37bb2e042aab12ff7391903235d3`
- LongCat source and inference: https://github.com/meituan-longcat/LongCat-AudioDiT
