# Model downloads

Studio can install missing files into your selected models folder. Existing files in all configured folders are reused. Model weights are downloaded from their publishers and are not bundled with Studio.

For gated models, open **Hugging Face access** beside the install button and choose **Sign in with Hugging Face**. A browser window opens. Sign in and approve Zura Studio's access to public gated models you are allowed to download. If Hugging Face asks for a short device code, it is shown in Studio. No read token needs to be created or pasted.

Use **Review terms** for each required model. Accept with the same account, then return to Studio; it retries the requested download. Some publishers approve access manually, so those downloads must wait for approval. Completed files are kept. If popups are blocked, **Open sign-in window** opens the same secure page.

**Remember on this computer** is optional. Credentials stay on the ComfyUI server, encrypted with Windows DPAPI on Windows or stored in an owner-only file on other platforms. Studio asks you to sign in again when the browser connection expires. Disconnect removes Studio's saved credential; it does not change another application's Hugging Face login. Existing Hugging Face CLI connections are also reused.

The **Advanced: use a read token** fallback remains available for managed installations. You can also choose **Download in browser** beside a file, then **Install downloaded file**. Studio streams the selected download to the configured models folder and verifies its pinned size and SHA-256 before installation. Your original download is kept and existing models are not overwritten.

Browser sign-in uses the official [Hugging Face OAuth device flow](https://huggingface.co/docs/hub/oauth), with `openid profile gated-repos` permissions. It does not request private repository access or read browser cookies. Restart ComfyUI after updating to load the browser-connection backend.

The workflow's ready state comes from the model choices exposed by ComfyUI. A valid installed model with a different pinned download version does not force another download. Missing custom nodes are shown separately and require installing or enabling the extension.

| Model file | Put it in | Upstream file |
| --- | --- | --- |
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `models/diffusion_models/` | [File and access requirements](https://huggingface.co/Lightricks/LTX-2.5/blob/main/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors) |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `models/text_encoders/` | [File and access requirements](https://huggingface.co/Lightricks/LTX-2.5/blob/main/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors) |
| `ltx-2.5-video-vae-conv-bf16.safetensors` | `models/vae/` | [File and access requirements](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-video-vae-conv-bf16.safetensors) |
| `ltx-2.5-audio-vae-bf16.safetensors` | `models/vae/` | [File and access requirements](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-audio-vae-bf16.safetensors) |
| `LTX23_Obscura_Remova_v1.safetensors` | `models/loras/` | [File and access requirements](https://huggingface.co/WepeNerd/Obscura_Remova/blob/main/LTX23_Obscura_Remova_v1.safetensors) |
| `ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors` | `models/loras/` | [File and access requirements](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate/blob/main/ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors) |
| `flux3-image-klein-int8-convrot.safetensors` | `models/diffusion_models/` | [File and access requirements](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/diffusion_models/flux3-image-klein-int8-convrot.safetensors) |
| `qwen3vl_4b_int8_convrot.safetensors` | `models/text_encoders/` | [File and access requirements](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/text_encoders/qwen3vl_4b_int8_convrot.safetensors) |
| `qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors` | `models/text_encoders/` | [File and access requirements](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors) |
| `flux2-vae.safetensors` | `models/vae/` | [File and access requirements](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/vae/flux2-vae.safetensors) |
| `sam3.1_multiplex_fp16.safetensors` | `models/checkpoints/` | [File and access requirements](https://huggingface.co/Comfy-Org/sam3.1/blob/main/checkpoints/sam3.1_multiplex_fp16.safetensors) |

The four Klein files support the clean-frame editor. The LTX transformer, text encoder, two VAEs and targeted adapter support Targeted repair. The clean-plate adapter is used by Full-scene clean plate. SAM supports text/point selection and tracking; a matching black-and-white mask video can be imported instead.

After adding the files, refresh ComfyUI's model list or restart it. Exact filenames matter. Existing extra model paths are supported; folders above are relative to the ComfyUI root. See DEPENDENCIES.md for the tested combination and the Obscura/LTX 2.5 compatibility qualification.

MODEL_SOURCES.json records the observed repository revisions and revision-specific download URLs. This records source locations, not a verification that every local test weight matches that revision. No general open-weights-only eligibility claim is made.
