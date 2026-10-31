# Paintout inside Zura Studio

The updated contest editor is available through **Video → Paintout / clean plate**. The Paintout shortcut, Comfy command and `?paintout=1` open that same workspace inside the main Studio shell.

## Shared experience

- Studio owns the header, theme, workflow navigation, icons, live sample preview, comparison viewer and native graph layout.
- Paintout keeps its Trim clip → Mask → Clean frames → Render flow, mask tracks, frame-number anchors, paint layers, saved projects, model setup and SDR/HDR pipelines.
- The workflow selector stays visible at every stage. Changing workspace and closing/reopening Studio retain the Paintout controller and draft.
- Studio custom LoRAs, targeted cancellation and submission recovery are retained. A lost response does not automatically submit a duplicate run.
- The canvas fills the available space. The Render stage hides the redundant editing timeline; Trim clip remains available above it. Narrow screens contain overflow inside the tool areas.

## Source and compatibility

Imported from the local `2026-10-25/https-comfy-org-open-source-higgsfield/work/paintout-dev` source. The independent contest source and packaged submission were not edited. The integrated copy uses thin re-exports for shared Studio modules rather than a second shell.

The established Display-P3 PQ handling and EXR metadata validation from main Studio are preserved alongside the updated editor. Portable ffmpeg/ffprobe discovery is used by the imported backend.

## Verification

The final selective compatibility merge is installed locally with rollback
backup `installed-native-hdr-gated-20261031-071120` (40 changed files, all
before/after hashes checked). It retains the installed browser-image node
registrations, setup and job recovery. The newer HDR workspace now uses the
shared shell and return callbacks; native performance, endpoints and HDR
frame-extension experiments remain default-off. Relight consistently routes
to Wan 2.1, including saved settings from the former H3 route.

All 70 staged top-level JavaScript suites passed across the main run and a
targeted resolution rerun. The backend passed 100 HDR/Paintout/opening checks
and 32 Wan relight/availability checks. A disposable installed-basis server
passed default desktop/mobile workspace, setup and reopen checks, then native
result playback/download/reopen and real HDR black-area HTTP review. Its
servers were stopped; those checks did not rerender diffusion output. The
native result and black-area inference outputs were verified in earlier
bounded GPU tests. Native-HDR artist qualification remains a separate gate.

The final neighbouring-media fix prevents duplicate ProRes proxy writers when
the same upload is used with different colour settings. It is installed with a
rollback backup under `installed-preview-ownership-20261031-065014`; six
upload/proxy regressions pass, including actual ProRes/PCM conversion. This
does not change original processing media or the independent contest source.

The current integration passes all 70 top-level JavaScript suites. A fresh
installed-pack browser run also checked the shared first/last, Paintout and
frame-extension workspaces at desktop and mobile sizes, HDR setup and reopen.
All 28 recorded standalone import hashes still match; no contest source files
were changed. The later HDR experiments described in the implementation plan
remain default-off development previews, now carried in the selective local
compatibility installation described above.

Run the main entry, preview and job-recovery checks:

```powershell
node tests/test_paintout_entry.mjs
node tests/test_paintout_unified.mjs
node tests/test_paintout_preview.mjs
node tests/test_paintout_model_setup.mjs
node tests/test_paintout_download_recovery.mjs
node tests/test_studio_completion_race.mjs
node tests/test_studio_create.mjs
node tests/paintout_updated/test_generation_steps.mjs
```

Updated backend tests live in `tests/paintout_updated`. Set `COMFYUI_ROOT` and `PYTHONPATH` to the ComfyUI folder and run its Python environment:

```powershell
python -m unittest discover -s tests/paintout_updated -p 'test_*.py'
$env:PAINTOUT_GRAPH_LIVE_INFO='http://127.0.0.1:8340'
node tests/paintout_updated/test_hdr_graphs.mjs
node tests/paintout_updated/test_editor_graphs.mjs
```

Local browser checks cover source loading, all four editor stages, shared navigation, retained state, close/reopen, shared theme and desktop/mobile overflow. These are CPU/interface integration checks, not new GPU output-quality or speed benchmarks.

On 31 October 2026, the updated backend suite ran 197 tests, with 195 passing and two environment-dependent skips. The main HDR colour fixtures also passed all three checks. Native graph contracts were checked against the CPU-only Comfy server on port 8340.

The integration follow-up checked all 60 top-level JavaScript test files and the original Paintout backend suite (104 tests). Older assertions were updated for removable audio, the playable source proxy and the new model-setup panel. The integrated downloader also retains Studio's duplicate-submit and lost-response recovery: an uncertain submission checks status before permitting another download. The contest source remains unchanged.

The integration was installed locally with a backup of changed files in `work/openjutsu-benchmark/paintout-installed-backup-20261031-014708`. Only the integration changes were applied to the installed main shell; unrelated installed Studio code was retained. Restart ComfyUI to load updated Python modules, then refresh its frontend. No registry release was made for this integration.

A later follow-up fixed the shared ComfyUI `executing` event adapter. Modern
frontends send a node ID string; Studio now uses the observed prompt start or
progress to retain ownership and display loading/handoff stages correctly. This
fix was installed in the main Studio copy, including Paintout, with a separate
`progress-event-installed-backup-*` backup. All 63 top-level JavaScript test files
passed. The independent contest files still match the original import hashes.

The final installed-file audit also corrected a reversible UTF-8/Windows-1252
encoding error in the six shared progress files. Original bytes were backed up
under `installed-utf8-repair-*`; all six repaired files passed JavaScript syntax
checks. This changes text encoding only and retains the installed workflow logic.

The shared-shell reopen follow-up retains the other workspaces alongside
Paintout: frame-extension panels, preview zoom controls and first/last/reference
model setup survive closing and reopening Studio. Status observation reconnects
to the existing model download with one polling loop. These lifecycle changes
were installed selectively with backups under `installed-workspace-reopen-*`.

Paintout's missing-node guidance now uses the same dependency catalogue as main
Studio, with direct source/update links for Zura Nodes, ComfyUI, KJNodes and
LTXVideo. Its updated setup was installed under an
`installed-shared-node-setup-*` backup. All 64 top-level JavaScript test files
pass. The installed pack passed two real browser close/reopen cycles across
Paintout, frame extension, first/last and reference video; loaded-source setup
was checked at 1440 × 900 and 390 × 844 with no page errors, global horizontal
overflow or generation/download submissions. This is interface verification,
not an additional GPU quality or speed benchmark.

When importing another standalone update, retain the shared-shell entry, shared module re-exports, Studio LoRAs, HDR source handoff, targeted cancellation and submission recovery in the integrated host. Preserve the main backend's Display-P3 and EXR validation additions. Do not overwrite the independent contest package as part of a Studio update.

The final reliability follow-up also protects the neighbouring Image, first/last
frame and reference-video workspaces. Direct submissions persist an opaque
request token before sending the graph and recover only its exact queue/history
match after a lost response. Cancellation is persisted and targeted, repeated
clicks do not send duplicate stops, and a result that finished before cancellation
is retained. Image submission is labelled as an image operation. Four focused
suites passed against a selective copy of the installed files; all 68 top-level
JavaScript suites passed in source. The four-file patch was installed with
before/after SHA checks and a backup under
`owned-jobs-installed-backup-20261031-050742-fccd9d8d`. It excludes source-only
native HDR experiments.

Setup-only fixes were installed separately under
`installed-setup-reliability-20261031-050357`: supplied-frame LTX readiness,
independent SAM 3.1 and Wan adapter downloads, and removal of the unused MelBand
branch when voice pitch processing is off. A focused 107-test backend run passed.
After both selective installations, a fresh CPU-only Comfy server using the
installed pack passed eight browser workspace/reopen checks, including the
loaded-source setup panel at desktop and mobile sizes. There were no page errors
or render/download submissions; the owned test server was stopped afterwards.
These checks do not constitute a new GPU quality or speed comparison. No public
release was made.

The shared setup follow-up now also maps all declared whole-scene LTX nodes
to their actual node packs, adds core-node update links in Image setup, and
offers the complete Wan 2.2 first/last-frame package with pinned files and sizes.
Those four reviewed files were installed with checksum verification and a backup
under `installed-shared-setup-20261031-052358`. The package selector retains
download cancellation and lost-response recovery. No model download was started.
A fresh installed-pack browser check again passed all eight workspace/reopen
checks, desktop/mobile setup bounds and zero page errors or render/download
submissions. The separate contest workspace was not modified.

The selective delivery follow-up was installed locally with checksum validation
and rollback backup `installed-inline-hdr-20261031-055706` (33 files). Existing
Paintout, shared setup and owned-job handling remain the installed basis.
First/last LTX, main LTX performance and frame extension now have inline output
controls for a clearly labelled additional SDR-to-HDR pass. This does not enable
the separate native-HDR endpoint, performance or frame-extension experiments.
The independent contest source still matches all 28 imported source hashes.

Validation covered eight focused JavaScript suites, 79 HDR/outpaint backend
checks, real FFmpeg soundtrack handling, and the camera/head-swap graph tests
(one optional schema-snapshot check skipped). The latter now preserve exact
fractional selections separately from held video tails. Staged browser checks
covered desktop/mobile layouts, HDR readiness and close/reopen without new
submissions. Two real nine-frame 640 × 512 frame-extension renders completed
their inline HDR pass in 59.2 and 60.7 seconds respectively; both returned
10-bit BT.2020 HLG, one audio track and CRC-valid nine-frame EXR archives.
These short engineering checks do not establish long-clip or artist colour
qualification. A fresh CPU-only server using the installed files then passed
nine model/workspace/layout checks, HDR readiness and retained-state reopening
with zero page errors or render/download submissions. It was stopped after the
check. No public release was made.

The final Cancel affordance fix is installed under
`installed-paintout-cancel-20261031-070003`. The button disables while stopping
is pending, including after reopening, and restores retry after an unconfirmed
request. Delayed-response, targeted-stop and duplicate-click regressions pass.
