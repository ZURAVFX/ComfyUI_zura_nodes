# Browser accounts in the Image workspace

Open **Image**, choose **Create image** or **Edit image**, then select
**ChatGPT Image** or **Gemini Image** under **Browser sign-in · no API credits**.
Click the sign-in button beside the prompt. This reuses the same account nodes
available in the ComfyUI graph, without API keys or a Zura credit balance.
Your website subscription and generation limits still apply.

The existing session connection currently supports your default Firefox profile
on Windows. Sign in to the selected website in a normal Firefox window, outside
containers or private browsing. First connection prepares an isolated client;
progress appears beside the prompt. Restart ComfyUI after updating Zura Nodes.

Add up to eight reference images by upload, drop or paste. For edits, Image 1 is
the image to change. Selecting Edit automatically uses the current canvas image
as Image 1 when available. Your prompt and references are sent to the selected
provider. Sizes are requests: the saved image retains the provider's actual
returned resolution. Local seeds and LoRAs do not apply to browser models.

Selecting a model only reads connection status. Account connection starts when
you click Sign in; generation starts when you click Generate or Apply edit.
Credentials are not saved in workflows. These unofficial website connections
can require reconnection after account changes or website updates. A successful
connection does not guarantee remaining generation allowance.

Details: [ChatGPT node](../CHATGPT_IMAGE.md), [Gemini node](../GEMINI_IMAGE.md).

Local FLUX.2 Klein 9B and Flux 3 Klein remain available in both Create and Edit,
with their existing model downloads, native sampling and LoRA support.
