# Word replacement in Zura Nodes

Two separate native ComfyUI workflows keep the editing controls inside the nodes:

* `workflows/Audio - Replace Speech (LongCat).json`: audio only, using local LongCat voice cloning.
* `workflows/Video - Replace Speech (LTX INT8).json`: video and sound, using a tracked face crop and LTX Dub-It.

The templates contain no recordings, personal reference files or generated takes. Use a current ComfyUI frontend with native subgraphs. Restart ComfyUI and refresh the browser after updating the pack.

## Audio only: LongCat

1. Choose your original audio and transcribe it with Parakeet, or type its complete transcript. Add an optional speaker reference and its exact transcript here.
2. In **Generate replacement phrase**, type the full revised sentence. **Change seed** only changes the seed. Click ComfyUI **Run** once to generate a take and load the two waveforms.
3. In **Choose both sections**, select the original words to remove on the upper waveform, then the replacement words to insert on the lower waveform. Click a word, Shift-click to extend, or drag the IN and OUT handles. Listen to each selection before applying it. The selected words appear below each waveform.
4. Click **Update final audio** in the separate **Final audio** node. It applies both selections and reuses the retained voice take. Listen to the final waveform, where the inserted interval is highlighted, then click **Download WAV**.
5. Moving either selection or changing the edge blend invalidates the old final preview until you update it. Phrase, reference, pace or seed changes create a new take; selection changes keep the current take, including after a ComfyUI restart.

The older combined editor remains available for existing workflows. The supplied template uses the clearer four-stage layout and starts with Manual IN/OUT selection. Both templates appear in ComfyUI Browse Templates under the ZuraNodes pack.

The source node's **Speaker reference** section accepts optional extra audio and its exact transcript. Use **Source and extra reference** to add it, or **Extra reference only** to use a cleaner recording instead. Prefer 8–20 seconds of clean speech from one speaker, without music or overlap. Combined references are limited to 25 seconds to leave room for synthesis. Very short references are accepted but can give a weaker match. If you trim the source reference range, fill in its separate trimmed-reference transcript; the original full phrase remains available for word matching.

**Timing is explicit.** The default **Natural duration (no stretch)** inserts the selected take at its natural speed and shifts the following audio. **Keep timing (up to 15% fit)** preserves the original timeline using pitch-preserving tempo adjustment; larger mismatches are refused. Adjust the selection or LongCat pace instead. Each mode leaves all samples outside the selected interval unchanged, with the following samples moved in natural-duration mode. The 12 ms default edge blend and bounded local level matching operate inside the replacement interval.

Exports are float WAVs under `output/zura_voice/<label>_<date>_<id>/`: `dialogue_edit.wav`, `replacement_take.wav` and `edit_receipt.json`. The original sample rate and channel count are retained. LongCat synthesises at 24 kHz; exporting at the source rate does not add voice detail. The receipt records the selected samples, gain, timing and whether stretching occurred. No loudness processing is applied to the rest of the source. Use another output node if you need a compressed delivery copy.

### Local setup

LongCat uses the existing [LongCat setup](LONGCAT.md), its installed model and isolated Python runtime. This editor does not download models or send audio to a service.

Parakeet is optional. Manual waveform editing works without it. For local word buttons and automatic changed-word selection, install `onnx-asr[cpu,hub]==0.12.0` in a separate Python environment and stage the Parakeet v3 INT8 and Silero VAD assets using the ONNX ASR project's instructions. Create **untracked** `parakeet.local.json` next to the pack:

```json
{"python":"/absolute/path/to/python", "models":"/absolute/path/to/models"}
```

The model directory must contain `parakeet-tdt-0.6b-v3-int8/` and `silero-vad/`. Alternatively set `ZURA_PARAKEET_CONFIG` to the configuration file. Windows also recognises an existing `%LOCALAPPDATA%/ParakeetRuntime` installation. Inference uses installed assets with offline mode enabled. If recognition fails or is ambiguous, the selection editor asks for a manual selection and the final node refuses to export a misleading finished result. Check recognised words and timings by ear.

Speaker references, transcripts and generated takes stay in local run folders. Do not publish these folders with a workflow or commit local configuration.

## Video and sound: LTX Dub-It

Choose the video, draw the face crop, place the mouth centre, and select source words. Type the full revised phrase on the LTX stage. The final node defaults to **Use original timestamps**, using the same timestamps within the generated context. This is an initial selection, not automatic dialogue alignment. The model can speak earlier or later than the source. Outside that interval, source audio and picture are retained. Download the result directly from **Finished video**.

**Mouth placement is required.** The amber oval shows the replaced pixels. Click the actual lips and cover both lips, including opening movement. Redrawing a crop preserves a confirmed mouth in the same reference frame when it stays inside the crop. The previous picker guessed the mouth at 65% of the crop and could silently overwrite manual placement. That guess is now rejected before sampling until you place the mouth. Hand-placed older selections remain usable.

The template uses the installed LTX 2.5 distilled INT8 transformer, Gemma 4 text encoder, matching 2.5 video/audio VAEs and latent upscaler, plus the Dub-It 0.9 LoRA for LTX 2.3. **The 2.3 Dub-It adapter on 2.5 is an experimental local combination, not an officially validated pairing.** Install the native LTX nodes from ComfyUI-LTXVideo for the graph's conditioning, audio reference and tiled decode nodes. The exact checkpoint filenames are exposed inside the native subgraph; weights are separate downloads.

**Follow face** retains the tracked crop from the tested artist workflow. Quality renders a native face crop at 512 pixels, refines to 1024 pixels, and area-downsamples it into the original frame. Preview uses 384 → 768. The tested distilled settings are 8 base plus 3 refinement steps. Higher processing resolution reduces avoidable resampling loss but cannot guarantee a sharp mouth on every seed.

The source validates constant frame rate and a zero start timestamp, pads generation to `8n+1`, and rounds spatial dimensions to multiples of 64. This local profile permits at most 241 generated frames and a 768-pixel base / 1536-pixel refined longest edge. Long contexts are bounded around the selected words; selected spans above the frame budget are refused. The native crop is padded to the generated aspect ratio and padding is removed before one downsample into the source. Unsupported geometry, changed source files and unexpected generated frame counts or sizes are rejected. The export is checked against the original frame count, size and frame rate. Use another workflow for longer edits or variable frame rate sources.

**Video and audio are never retimed in this workflow.** The old template could leave the generated range at 0–0.5 seconds while the selected original words were later and longer. This inserted a different head pose and interpolated it across the wrong interval, producing a smeared mouth/chin. Source timing now ignores stale generated IN/OUT values. If the generated delivery needs an offset, open **Replacement words**, choose **Move replacement selection**, and move either handle. Both handles move together, keeping the original selection duration. Differences over one video frame are refused; smaller boundary differences use the exact original duration. Nearest-frame selection is the default, avoiding the blending of distinct mouth poses. The receipt records effective ranges, timing mode and `retimed: false`. The audio-only workflow has its separate timing modes above.

## Validation

The audio editor was run on an RTX 4080 using the installed LongCat 3.5B, 16 sampling points and APG 4. A full revised phrase was generated, Parakeet identified the changed word, and only that interval was blended. CPU checks cover mono/stereo sample preservation, native-duration splicing, bounded timing fit, ambiguous word matching, retained-take caching, added references and trimmed-reference transcripts. Video checks cover supported geometry, frame/timestamp guards, tracking and unchanged audio outside the word selection. Example templates are saved through native frontend graph/subgraph APIs, reloaded, and compiled to verify promoted phrase/seed controls.

The 15 October regression test used the earlier tracked INT8 crop and seed 42 at 512 → 1024, with 8 + 3 steps. A real local GPU run completed in approximately 100 seconds. Parakeet recognised the revised phrase in both the generated take and finished word-only composite; visual inspection confirmed different mouth poses in the composite. This is a controlled neutral-clip test, not qualification of every voice or of the unvalidated 2.5/2.3 pairing. Lightricks recommends matching the prompt to the original timing and syllable length: [Dub-It guidance](https://docs.ltx.io/open-source-model/feature-guides/audio/dub-it-beta).

## Transcript editing and reference selection

The first video node has two views. **Clip and face** trims the voice/video reference with amber IN/OUT handles and lets you draw the face crop and mouth area on a paused frame. **Select words** shows a green waveform selection and Parakeet word buttons. Click any word, drag across several words, or Shift-click to extend a selection. Arrow keys move between word buttons; Shift-arrow extends the selection.

Parakeet runs locally when a clip is opened. The next node fills **Phrase to speak** from the recognised words inside the effective processing reference. Edit the full phrase there. Green words in the original phrase show the source selection; amber words in the preview show text changes. Existing manual edits are preserved across refreshes and reference changes. **Use recognised phrase** explicitly resets the draft. If Parakeet is unavailable, waveform selection and manual phrase entry remain available, with a retry button.

The reference waveform spans the original clip; the word waveform zooms into the chosen reference range. Selecting transcript words outside that range moves the reference around them. Reference handles respect the local 241-frame processing limit. The effective, frame-aligned interval is displayed, including any automatic bounding. Only the selected words are composited into the original; the reference range supplies context.

To place the mouth, click its centre to keep the current size or drag a rectangle around both lips to draw a new oval. **Reset mouth size** restores a useful size relative to the face crop. An accidental tiny crop drag retains the prior crop. Dot-sized mouth masks and face reference frames outside the effective reference clip are rejected before sampling. Choose a clear paused frame inside the reference interval, then place the mouth there. These safeguards prevent invalid selections; they do not guarantee generated speech or lip-sync quality.

No models, sampling schedules, precision settings, crop-following controls or retiming behaviour changed in this UI update. Refresh the frontend after updating; restart ComfyUI once for the Python validation changes.
