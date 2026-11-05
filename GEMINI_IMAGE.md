# Zura · Gemini Image

1. Restart ComfyUI and add **Zura · Gemini Image** under **Zura/Image**.
2. Choose **Sign-in browser** (or **Browser** beside the prompt in Studio), then click **Sign in to Gemini**. Zura opens the browser you selected on the computer running ComfyUI and checks automatically until **Connected**. You can cancel a pending connection and choose another browser.
3. Enter a prompt, optionally connect reference images and choose a requested size. Connect the image output to Preview Image or Save Image, then queue. Generation makes direct requests using your Gemini website session, with no browser window.

No extension, browser driver or developer API key is used. Your Gemini website generation limits apply. The first connection automatically installs `gemini-webapi==2.1.1` in an isolated runtime under `%LOCALAPPDATA%/ZuraNodes/runtimes`, without changing ComfyUI's Python packages. This uses the maintained [Gemini-API client](https://github.com/HanaokaYuzu/Gemini-API), also used by [Comfyui-GeminiWeb](https://github.com/Koko-boya/Comfyui-GeminiWeb). TLS verification stays enabled.

Supported browser connections:

- **Chrome, Microsoft Edge, Brave, Vivaldi, Chromium and Opera**, when installed: Zura opens a dedicated sign-in window in that browser. Sign in once there, even if your everyday browser window is already signed in. The separate profile avoids the browser protections that prevent reading an everyday Chrome or Edge session. Zura does not disable those protections.
- **Safari on macOS**: uses your existing normal Safari session. If macOS blocks access, the UI explains how to allow Full Disk Access for the app that starts ComfyUI, or you can choose another browser. Private browsing is not supported.
- **Firefox on Windows, macOS and Linux**: uses the default profile outside private windows and containers.

Only installed browsers appear in the selector. This connection runs on the ComfyUI computer; a browser on a separate phone or laptop cannot provide its session to a remote ComfyUI server. Only the chosen provider's relevant cookies reach its client. Connection credentials are held in memory and stay out of workflows, API responses and logs. Dedicated browser profiles stay in the local ZuraNodes/browser-profiles directory. You can close the sign-in window after connection. Reconnect after restarting ComfyUI, changing accounts or an expired session.

Refreshed Gemini session data stays under the local ZuraNodes/sessions/gemini directory. Cache filenames are hashed so cookies do not appear in filenames.

Each of the eight reference sockets accepts an image batch. Provider upload limits still apply. Size is requested in the prompt; `actual_size` reports the real returned dimensions. Only generated image assets are accepted, and the client downloads the full-size result. Connection means the web session was accepted, not a promise of available image quota. Every generation validates the explicitly connected session again. If it expires, reconnect using the browser selector. This unofficial integration can break when Google changes its website or session handling.

The node consumes generated assets directly from the response stream. Once an image arrives, unrelated trailing response frames do not discard it. The stream watchdog uses the node's requested timeout. If a stream fails after identifying the new conversation, the node can retrieve the image from that same conversation. It does not resubmit the generation request automatically or search other chats for a replacement image. Quota, temporary service failures, response-format failures and authentication failures have separate messages.

Verified locally on 30 October 2026: real image generation and a reference-image edit using the existing Firefox sign-in. A reference request also timed out during verification; generation latency depends on Google's service. Timeouts stop the local request and report the stage. Check the conversation before retrying, as a server-side generation may still finish.
