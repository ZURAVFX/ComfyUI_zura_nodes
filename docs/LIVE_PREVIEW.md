# Live sampling previews

Studio displays ComfyUI's native sample stream on the canvas while a job runs. Native TAE previews show the **first frame changing as sampling progresses**, rather than a live playback of the entire generated video. The existing Director animated-preview fallback shows more of the clip using approximate latent RGB colours; it is not a TAE decode. The stream is checked against the active prompt ID; another queue item's sample cannot replace the current shot. Final results replace previews, and temporary image URLs are released when sampling ends or Studio closes.

The preview method is set **per job**, rather than changing ComfyUI's global preference:

| Route | Installed optional tiny decoder | Fallback |
| --- | --- | --- |
| H3, including first/last frame, references, camera and head replacement | `models/vae_approx/taeh3.safetensors` | Native latent RGB; the existing animated H3 approximation remains available on its supported graph |
| Wan 2.1 relight, Wan 2.2 14B and Wan Animate 2 | `models/vae_approx/lighttaew2_1.safetensors` | Native latent RGB |
| LTX 2.5 | Current installed core does not select the LTX 2.5 TAE through its latent-format interface | Native latent RGB |
| Starting-image generation | Native model-specific preview when supported | Native latent RGB |

Tiny decoders are optional. Missing preview assets do not block a render or trigger an automatic download. Preview colours and detail are approximate; approve the final decoded output.

Wan 2.2 **14B** uses the Wan 2.1 VAE family. `lighttaew2_2` is for the different Wan 2.2 5B VAE and must not be substituted. Likewise, the LTX 2.0 tiny decoder must not be passed off as an LTX 2.5 decoder.

Primary sources:

- [TAEHV author models and compatibility](https://github.com/madebyollin/taehv)
- [Lightx2v's autoencoders](https://huggingface.co/lightx2v/Autoencoders)
- [ComfyUI native video tiny-VAE integration](https://github.com/Comfy-Org/ComfyUI/pull/10884)
- [ComfyUI's native latent-preview implementation](https://github.com/Comfy-Org/ComfyUI/blob/master/latent_preview.py)

Checks: `tests/test_studio_live_preview.mjs` covers prompt ownership, rejection of foreign or stale samples, metadata/legacy deduplication, temporary URL cleanup, optional-decoder fallback and canvas lifecycle. `tests/test_live_preview.py` checks family-specific decoder selection. These checks do not benchmark decoder overhead or prove an inference-quality result.
