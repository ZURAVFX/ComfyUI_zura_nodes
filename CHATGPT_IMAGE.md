# Zura · ChatGPT Image

1. Restart ComfyUI and add **Zura · ChatGPT Image** under **Zura/Image**.
2. Click **Sign in to ChatGPT** at the top. The node checks your existing default Firefox profile. If sign-in is needed, it opens the normal ChatGPT sign-in page in your default browser. Sign in in Firefox; the node checks automatically and shows **Connected**.
3. Enter a prompt, optionally connect reference images and choose a requested size. Connect the image output to Preview Image or Save Image, then queue. Generation makes direct requests using your ChatGPT website session, with no browser window.

No extension, WebDriver, Codex login, Codex allowance or paid developer API key is used. Your ChatGPT website generation limits apply. The first connection automatically installs the pinned client in an isolated runtime under `%LOCALAPPDATA%/ZuraNodes/runtimes`, without changing ComfyUI's Python packages.

Currently supported session source: the default Firefox profile on Windows, outside private windows and containers. Only the relevant ChatGPT session cookies are read from its cookie database, read-only. Credentials stay outside workflows and logs. The client is the explicit `OpenaiChat` provider from [gpt4free](https://github.com/xtekky/gpt4free/tree/91d9c82150b8d5032a0400591872cfc816cfa9af), pinned to that revision; it does not select other services or fall back to browser automation.

Each of the eight reference sockets accepts an image batch. Provider upload limits still apply. Size is requested in the prompt; `actual_size` reports the real returned dimensions. Connection means the web session was accepted, not a promise of available image quota. Every generation reads and validates the session again. If it expires, open ChatGPT in normal Firefox and reconnect. Website changes or account challenges can break this unofficial integration.

Verified locally on 30 October 2026: direct generation and a reference-image edit, with the edited full-size image downloaded successfully.
