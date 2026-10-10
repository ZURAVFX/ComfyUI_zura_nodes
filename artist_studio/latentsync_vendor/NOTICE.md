LatentSync inference components, Copyright ByteDance and upstream contributors.
Source: https://github.com/bytedance/LatentSync
Revision: a229c3948406bc2cf6eaf4873e662e70c6a04746
Licence: Apache-2.0 (LICENSE-LatentSync).

The UNet logging import uses a local logger to avoid training/video dependencies.
The configuration contains only the published stage2_512 model configuration.
Whisper includes only the audio encoder and mel transforms used by LatentSync.
Text decoding, remote model loading and file/subprocess audio loading are omitted.
Whisper source: https://github.com/openai/whisper, MIT (LICENSE-Whisper).
LatentSync's pre-normalisation intermediate encoder embeddings are preserved.
No model weights or user examples are included.
