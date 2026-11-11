# ComfyLink adapter and high-depth nodes

This optional local adapter exposes capabilities and a versioned preset catalogue
for the separate ComfyLink After Effects extension. It does not run a second
queue: the supervisor remains responsible for staging, prompt submission,
state, cancellation, results and recovery through the existing ComfyUI APIs.
Existing Zura nodes and Studio do not require an AE licence.

For the optional browser session, source-interval rules and supported limits,
see [ComfyLink Studio](COMFYLINK_STUDIO.md). The extension, native AE plug-in,
supervisor and licensing implementation are separate products and are not
included in this public repository.

`GET /zura/comfylink/v1/capabilities` provides loopback-only anonymous protocol
discovery. Identity, diagnostics, presets and graph preflight require a bearer
token set at process startup in `COMFYLINK_TOKEN`; without one they are disabled.
The supervisor also sets `COMFYLINK_INSTANCE_ID` and
`COMFYLINK_CONFIG_FINGERPRINT`. Authenticated `GET /identity` reports these
values and runtime PID, interpreter, installation path and process start time
when available. Treat these as a handshake, not proof of ownership by themselves:
the supervisor must validate process identity and loaded configuration. The
server restricts peer, Host and Origin to the local machine. No secrets appear
in capabilities or the catalogue.

Authenticated `GET /presets` returns API graphs with stable IDs, revision,
canonical graph SHA-256, bindings and stated media requirements. The SHA-256 is
over the supervisor's Go `json.Marshal(map[string]Node)` representation: map
keys are sorted, node fields are in `class_type`, `inputs`, `_meta` order, and
Go's standard JSON escaping applies. Number tokens must be retained exactly.
Revisions must never change meaning: add a new revision or ID when a graph or
its semantics changes. The original `zura-character-mask-video` remains a
replacement output for compatibility. A grayscale mask is not alpha footage;
it needs explicit matte application in the AE client. Native `LoadVideo` and
`SaveVideo` stay in the original graph, including the original FPS, bit-depth,
colour and audio links.

Authenticated `POST /preflight` accepts either `{"preset_id": "..."}` or
`{"workflow": {...}, "input": {"node": "1", "field": "file"},
"output": {"node": "2"}}`. It checks node types, bindings, and whether the
selected output depends on the selected input. When both a preset ID and a
workflow snapshot are supplied, preflight checks the snapshot itself. It only
treats the preset's requirements as complete when the snapshot's graph hash and
bindings match the current catalogue. Optional `required_models` is a
list of `{"category": "detection", "name": "subfolder/file.onnx"}` entries;
the exact category and relative filename go through ComfyUI's path resolver,
including registered additional model folders. The authenticated response
returns each model's category, name and `resolved`, `not_resolvable` or
`unreadable` status, plus counts of available and unavailable category roots.
For any graph containing the Zura mask node it checks the loaded node's
segmentation and pose model names and its helper-node/Python-package dependencies. If it cannot
identify that node's requirements, or for a custom graph whose requirements
cannot be fully established, `execution_ready` is `unknown`. A `blocked` result
describes a failed check; `ready` means the checks passed, not that inference
has run. The adapter does not download, move or load models. JSON graphs can execute any
installed custom-node code; import only graphs from sources you trust. API
format is required; visual-editor graph JSON must be exported via ComfyUI.

The compatibility `ComfyLinkLoadFrames` node is registered only when the old
`custom_nodes/comfylink_ae` package is absent. Remove or rename that old package
manually after stopping ComfyUI if migration is desired; it is never deleted by
this adapter. The node and original preset graphs were copied from the MIT
ComfyLink 1.1.2 preview, Copyright 2026 zura; the complete licence is in
`comfylink/MIT-LICENSE.txt`. Zura's own code remains AGPL-3.0-only. This
architecture and notice do not determine the licence of a combined product.

The mask graph uses `placeholder.mp4` for its input; the supervisor must bind
the actual input path and unique output prefix before submitting a job.
Local CPU and HTTP tests do not establish live After Effects import,
fresh-machine installation or GPU generation quality.

## High-depth nodes and colour

`ZuraComfyLinkLoadFloatFrames` reads a declared, validated transfer manifest
and returns RGB `IMAGE`, `MASK` (1 minus alpha) and typed frame metadata.
`ZuraComfyLinkSaveFloatFrames` saves a raw FLOAT RGBA transfer plus EXRs.
Its EXR storage defaults to `float32`; choose `half` explicitly to quantise
the EXRs. The raw FLOAT transfer remains the authoritative payload.

The high-depth path preserves finite float32 values, including negative RGB,
values above one and RGB beneath zero alpha. AE uint16 uses 32768 as white.
Colour encoding, alpha association, source depth and rational frame timing are
declared metadata. Float32 storage alone does not prove linear light or model
fidelity. Unpremultiplication is an explicit load option; no hidden gamma,
gamut or range conversion is applied by these I/O nodes. Downstream nodes
may still change or clip values.

`ZuraComfyLinkToLTXColour` converts declared scene-linear Rec.709 or ACEScg to
LTX ACEScct. `ZuraComfyLinkFromLTXColour` decodes declared ACEScct to
scene-linear ACEScg. The bridge is separate from model inference. LTX's
ACEScct code domain remains [0, 1]; the default range policy rejects values
outside it. Choosing `clamp` explicitly discards that range and records the
operation. This is not an unbounded HDR model. Alpha remains separate and
requires declared straight association. Unknown or custom ICC colour
conversion is unsupported.

Ordinary Studio's advanced EXR precision setting defaults to HALF (16-bit).
FLOAT (32-bit) is selectable on supported native EXR delivery paths. An AE
32-bit source can prefer FLOAT within its isolated session without changing
normal Studio's default. Real OpenImageIO CPU write/read fixtures check
storage type and numeric samples. They do not measure model quality.
