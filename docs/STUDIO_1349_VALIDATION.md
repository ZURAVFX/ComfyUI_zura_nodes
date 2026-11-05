# Zura Studio 1.3.49 browser connections

Previously, sign-in opened the OS default browser while the workers read only a Windows Firefox cookie database. Chrome or Safari sign-in therefore never supplied the session being checked.

Both Studio and the standalone ChatGPT/Gemini nodes now have an installed-browser selector. Chromium-based browsers use a dedicated Zura profile and a loopback connection to that browser. Safari uses its macOS cookie reader, with actionable permission errors. Firefox profile discovery covers Windows, macOS and Linux. No browser's everyday security protections are disabled, and there is no automatic fallback to another browser account.

Only the selected provider's required, unexpired cookies are passed to its isolated worker over standard input. Cookies are not returned by HTTP routes or included in workflows or logs. Connections are held in memory; after a ComfyUI restart, reconnect through the selector. Chromium sign-in profiles remain local so a returning connection can reuse that sign-in.

Validation on 5 November 2026:

- All 150 release regression commands passed locally, including the existing image generation graph, model installation, browser connection and accessibility checks.
- New browser tests cover all three Firefox profile locations, Safari permission errors, provider/domain/expiry/container filtering, chunked ChatGPT cookies, selected-browser launch isolation, cancellation and stale connection attempts.
- The Chromium protocol test uses a real local HTTP/WebSocket server and synthetic cookies. It verifies scoped cookie requests and rejects a different browser endpoint or non-local WebSocket.
- Studio and node tests cover browser selection, workflow serialization, cancellation, generation locking and late status responses.
- An actual-component browser preview verified the selector, pending state and cancellation. Preview data was synthetic.
- Package metadata, required assets and documentation links passed.

No real account cookies were read during this validation. Fresh ChatGPT/Gemini account sign-in and image generation were not performed. Safari requires a macOS test machine for a live sign-in check; this workstation is Windows. Browser/provider policies, account challenges and website changes can still affect these unofficial website clients. The previously recorded live Firefox generation results are historical evidence, not a live cross-browser test of this release.
