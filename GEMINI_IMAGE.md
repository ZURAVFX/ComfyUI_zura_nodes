# Zura · Gemini Image

1. Restart ComfyUI and add **Zura · Gemini Image** under **Zura/Image**.
2. Click **Sign in to Gemini** at the top. The node checks your existing default Firefox profile. If sign-in is needed, it opens Gemini in your normal default browser. Sign in in Firefox; the node checks automatically and shows **Connected**.
3. Enter a prompt, optionally connect reference images and choose a requested size. Connect the image output to Preview Image or Save Image, then queue. Generation makes direct requests using your Gemini website session, with no browser window.

No extension, browser driver or developer API key is used. Your Gemini website generation limits apply. The first connection automatically installs `gemini-webapi==2.1.1` in an isolated runtime under `%LOCALAPPDATA%/ZuraNodes/runtimes`, without changing ComfyUI's Python packages. This uses the maintained [Gemini-API client](https://github.com/HanaokaYuzu/Gemini-API), also used by [Comfyui-GeminiWeb](https://github.com/Koko-boya/Comfyui-GeminiWeb). TLS verification stays enabled.

Currently supported session source: the default Firefox profile on Windows, outside private windows and containers. Only the two relevant Google session cookies are read from its cookie database, read-only. Refreshed session data stays under `%LOCALAPPDATA%/ZuraNodes/sessions/gemini`, outside workflows and logs. The adapter uses hashed cache filenames so session cookies do not appear in filenames. Keep that directory private.

Each of the eight reference sockets accepts an image batch. Provider upload limits still apply. Size is requested in the prompt; `actual_size` reports the real returned dimensions. Only generated image assets are accepted, and the client downloads the full-size result. Connection means the web session was accepted, not a promise of available image quota. Every generation reads and validates the session again. If it expires, open Gemini in normal Firefox and reconnect. This unofficial integration can break when Google changes its website or session handling.

The node consumes generated assets directly from the response stream. Once an image arrives, unrelated trailing response frames do not discard it. The stream watchdog uses the node's requested timeout. If a stream fails after identifying the new conversation, the node can retrieve the image from that same conversation. It does not resubmit the generation request automatically or search other chats for a replacement image. Quota, temporary service failures, response-format failures and authentication failures have separate messages.

Verified locally on 30 October 2026: real image generation and a reference-image edit using the existing Firefox sign-in. A reference request also timed out during verification; generation latency depends on Google's service. Timeouts stop the local request and report the stage. Check the conversation before retrying, as a server-side generation may still finish.
