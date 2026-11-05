# Browser accounts in the Image workspace

Open **Image**, choose **Create image** or **Edit image**, then select
**ChatGPT Image** or **Gemini Image** under **Browser sign-in · no API credits**.
Choose **Browser**, then click the sign-in button beside the prompt. This reuses the same account nodes
available in the ComfyUI graph, without API keys or a Zura credit balance.
Your website subscription and generation limits still apply.

The selector lists browsers installed on the computer running ComfyUI:

- Chrome, Edge, Brave, Vivaldi, Chromium and Opera open a dedicated sign-in window. Sign in once there, even if you already use that account in your everyday browser.
- Safari on macOS reads your normal Safari session. If macOS blocks access, follow the Full Disk Access guidance shown in Studio or choose another browser.
- Firefox uses its default profile on Windows, macOS or Linux, outside containers and private browsing.

First connection prepares an isolated client; progress appears beside the prompt.
Use **Cancel connection** to stop waiting and choose another browser. After
**Connected**, you can close the sign-in window. Reconnect after restarting
ComfyUI or changing accounts. Restart ComfyUI and refresh Studio after updating
Zura Nodes. Remote ComfyUI cannot use a browser session from another computer.

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

## Video starting images

In a video workflow's starting-image stage, open the image model menu and choose
**ChatGPT Image · browser sign-in** or **Gemini Image · browser sign-in**. The
same sign-in controls appear beside the prompt. This includes Relight and the
shared character/viewport starting-image stages. Camera image editing also
supports the existing browser models.

The original selected video frame is always Image 1. Add up to seven appearance
references after it. Regenerating starts from the original video frame, not the
previous result. Local image LoRAs do not apply to browser generators.

Studio asks the provider to preserve Image 1's proportions and framing, with an
explicit aspect ratio and target pixel dimensions. The provider may return a
different size; Studio fits the result proportionally back to the source canvas
without stretching. Review the starting image before animating it.
