# Zura LongCat Voice

Local LongCat-AudioDiT 3.5B voice cloning and text-to-speech, available in Zura Nodes 1.1.0.

## Daily use

Open `workflows/Zura_LongCat_Voice_Clone.json` in ComfyUI:

**Load Audio -> Zura LongCat Voice -> Preview Audio**

Upload a clean, prepared clip of one authorised speaker. Start with 8-20 seconds without music or overlapping voices. Paste its exact spoken words into **reference_transcript**. Put the new words in **script**, enter a **project** label, and click **Run**. Reference transcription is manual.

For longer source recordings, trim first or insert the core **Trim Audio Duration** node. The transcript must match the trimmed audio. LongCat's combined reference/generation window is 60 seconds; a reference filling that window cannot generate speech.

**Pace:** 1.0 is the tested default; higher requests faster speech, lower requests slower speech. This changes synthesis duration, not playback pitch. It is not an exact duration guarantee.

**Seed:** keep fixed to repeat sampling on the same software/hardware stack, or randomise for another take. Different hardware/software can change results.

The templates contain no personal recording, reference transcript or machine-specific paths.

## Text-to-speech without a recording

Open `workflows/Zura_LongCat_Text_to_Speech.json`, enter a script and project label, and Run. No reference branch is needed.

Unconditioned TTS does not promise a stable speaker across scripts or long-script chunks. To keep a consistent voice, generate a short sample, then use that WAV and its actual spoken transcript in the cloning workflow. This is speech synthesis, not speech-to-speech performance transfer, singing or a dialogue engine. The upstream model is documented for English and Chinese.

**Speaker descriptions are not supported by LongCat.** The script field is spoken text, not instructions for age, accent, timbre or emotion. A separate voice-design model can generate a reference to use here, but no voice-design model is included in this release.

## Output

Every run creates `zura_voice/Project_Date_Time_ID/` under your configured ComfyUI output directory. Existing takes are not overwritten.

- `voice.wav`: 24-bit PCM, 24 kHz mono WAV.
- `master_float32.wav`: original model samples in a float WAV.
- `chunk_001.wav`, etc.: individual long-script parts.
- `script.txt`, `job.json`, `report.json`, `worker.log`: script, configuration and diagnostics.

Cloning runs retain the reference recording. Treat run folders as voice data; do not publish them to a source repository. Preview Audio is just a listening preview; masters are already saved.

Only the PCM copy is reduced by a single gain factor if required to avoid clipping; the report records that gain. No EQ, denoising, pitch change or loudness mastering is applied.

Long scripts are split at sentence/word boundaries using the upstream duration estimate. Each cloned part reuses the original reference; the combined render inserts 150 ms between parts. Check every join, name and pronunciation before delivery. Splitting prevents silent text truncation but does not guarantee perfect prosody.

## One-time setup on another workstation

1. Install/update **Zura Nodes** (`comfyui-zura-nodes`) to **1.1.0 or newer** through ComfyUI Manager, or update the Git repository. Registration is included; do not manually replace `__init__.py`.
2. Install **Git** and **uv** if missing. In the installed node package, double-click **Setup_LongCat_Windows.cmd**. This explicitly downloads the pinned model/source and tokenizer into `%USERPROFILE%\ZuraLongCat`, with a separate Python 3.11 environment.
3. Restart ComfyUI and open either supplied workflow. Copy the JSONs to `ComfyUI/user/default/workflows` to add them to the sidebar.

The model dependencies stay isolated. The node package adds only SoundFile for WAV I/O to ComfyUI's environment. Installing the Registry package does not itself download the model weights.

Tested on Windows with an RTX 4080 16 GB and 64 GB RAM. CUDA with BF16 support is required. Smaller-memory GPUs and other operating systems are not validated. The full-precision checkpoint loads on CPU; allow sufficient RAM and disk space for the weights and isolated environment. The reuse/check setup route has been tested; a completely fresh workstation installation remains unvalidated.

Equivalent commands from the Zura Nodes folder:

```powershell
uv run --python 3.11 --no-project --no-config setup_longcat.py --install
uv run --python 3.11 --no-project --no-config setup_longcat.py --check
```

Add `--root D:\AI\ZuraLongCat` to choose another drive. Machine paths are stored in `longcat.local.json`, not workflows. This file and its backups are excluded from Git and Registry packages. Do not copy it between workstations. Advanced installs can set `ZURA_LONGCAT_CONFIG` and choose `device_index` in the config.

An existing VoiceCloneLab setup can be reused with `python setup_longcat.py --reuse-lab D:\VoiceCloneLab`, replacing that example path with its real location. VoiceCloneLab is not required for new installations.

## Runtime and troubleshooting

Defaults retain the tested configuration: 16 sampling time points, APG guidance 4.0, BF16 main model/text encoder, FP16 VAE, FP32 ODE state. The upstream checkout is not edited.

Each run starts a separate process, including model loading, and releases its GPU memory on exit. ComfyUI Stop/interrupt terminates that run's child process. Partial outputs and logs remain available.

Generation uses local files and Hugging Face/Transformers offline flags; no hosted synthesis service is called. Downloads happen only in the explicitly invoked installer. Do not expose ComfyUI publicly without separate access controls.

Missing-input and generation errors point to the relevant run folder. For memory failures, close other GPU-heavy applications and shorten the reference. The node unloads models managed by its own ComfyUI process, not allocations owned by other applications.

## Rights and sources

LongCat weights and source are MIT-licensed; retain upstream notices when redistributing them. Setup preserves the upstream checkout and available model notices. This does not change the existing Zura Nodes licence. Obtain permission for the speaker, recording and intended use; the model licence does not provide those rights.

- Model: https://huggingface.co/meituan-longcat/LongCat-AudioDiT-3.5B
- Source: https://github.com/meituan-longcat/LongCat-AudioDiT
- Licence: https://github.com/meituan-longcat/LongCat-AudioDiT/blob/main/LICENSE

Source revision: `12c76b51d2a8aa6b6c9af5b25cd5ff8f7aa8178a`

Model revision: `5d3e6dc007872d756c3a69b44951598d7d9bdf6d`
