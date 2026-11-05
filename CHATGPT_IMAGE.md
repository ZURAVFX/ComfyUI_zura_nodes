# Zura · ChatGPT Image

1. Restart ComfyUI and add **Zura · ChatGPT Image** under **Zura/Image**.
2. Choose **Sign-in browser** (or **Browser** beside the prompt in Studio), then click **Sign in to ChatGPT**. Zura opens the browser you selected on the computer running ComfyUI and checks automatically until **Connected**. You can cancel a pending connection and choose another browser.
3. Enter a prompt, optionally connect reference images and choose a requested size. Connect the image output to Preview Image or Save Image, then queue. Generation makes direct requests using your ChatGPT website session, with no browser window.

No extension, WebDriver, Codex login, Codex allowance or paid developer API key is used. Your ChatGPT website generation limits apply. The first connection automatically installs the pinned client in an isolated runtime under `%LOCALAPPDATA%/ZuraNodes/runtimes`, without changing ComfyUI's Python packages.

Supported browser connections:

- **Chrome, Microsoft Edge, Brave, Vivaldi, Chromium and Opera**, when installed: Zura opens a dedicated sign-in window in that browser. Sign in once there, even if your everyday browser window is already signed in. The separate profile avoids the browser protections that prevent reading an everyday Chrome or Edge session. Zura does not disable those protections.
- **Safari on macOS**: uses your existing normal Safari session. If macOS blocks access, the UI explains how to allow Full Disk Access for the app that starts ComfyUI, or you can choose another browser. Private browsing is not supported.
- **Firefox on Windows, macOS and Linux**: uses the default profile outside private windows and containers.

Only installed browsers appear in the selector. This connection runs on the ComfyUI computer; a browser on a separate phone or laptop cannot provide its session to a remote ComfyUI server. Only the chosen provider's relevant cookies reach its client. Connection credentials are held in memory and stay out of workflows, API responses and logs. Dedicated browser profiles stay in the local ZuraNodes/browser-profiles directory. You can close the sign-in window after connection. Reconnect after restarting ComfyUI, changing accounts or an expired session.

The client uses the explicit `OpenaiChat` provider from [gpt4free](https://github.com/xtekky/gpt4free/tree/91d9c82150b8d5032a0400591872cfc816cfa9af); it does not select other services.

Each of the eight reference sockets accepts an image batch. Provider upload limits still apply. Size is requested in the prompt; `actual_size` reports the real returned dimensions. Connection means the web session was accepted, not a promise of available image quota. Every generation validates the explicitly connected session again. If it expires, reconnect using the browser selector. Website changes or account challenges can break this unofficial integration.

Verified locally on 30 October 2026: direct generation and a reference-image edit, with the edited full-size image downloaded successfully.
