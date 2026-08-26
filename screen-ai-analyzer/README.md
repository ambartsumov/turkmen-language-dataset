# Screen AI Analyzer

Press a hotkey → the current screen is captured once → the image goes to a
vision model → **the answer lands on your clipboard and a normal desktop
notification tells you it is ready**. Optionally the answer can be shown in a
small always-on-top overlay instead.

Built for Ubuntu 24.04 LTS, Wayland first, X11 as a fallback.

## Scope

This is an ordinary, visible desktop application for permitted study and work
scenarios. It deliberately contains **no** anti-cheat / proctoring evasion, no
screen-capture-detection bypass and no process masking:

* the process is a plain `python -m app.main`, visible in `ps` and in the
  window/tray list;
* on Wayland every capture goes through `xdg-desktop-portal`, so the
  compositor's own consent dialog and capture indicator apply;
* the overlay (when enabled) is a real window and appears in screen recordings.

Do not use it where the rules of an exam or an employer forbid it.

## Install

```bash
git clone <this-repository-url>
cd <repository>/screen-ai-analyzer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env          # put your API key(s) here
./run.sh
```

`./install.sh` does all of the above and offers to install the optional system
packages (`tesseract-ocr`, `gnome-screenshot`, `xdg-desktop-portal*`,
`libnotify-bin`).

Check the environment at any time:

```bash
./run.sh --check   # session, capture backends, providers, hotkey status
./run.sh --ping    # one cheap request per provider — verifies the API keys
```

## API keys

Keys are read from the environment (`.env`) first; the settings dialog is only
a fallback and stores them in `~/.config/screen-ai-analyzer/config.json`
(mode 0600). No key ever appears in the source or in the log file.

| Variable | Used for |
| --- | --- |
| `OPENROUTER_API_KEY` | one key for both a vision model and a text model |
| `GEMINI_API_KEY` | direct Gemini Vision (Google AI Studio) |
| `DEEPSEEK_API_KEY` | direct DeepSeek (text-only → OCR first) |
| `OPENAI_API_KEY` | optional extra vision provider |
| `CUSTOM_API_KEY` + `CUSTOM_BASE_URL` + `CUSTOM_MODEL` | any OpenAI-compatible endpoint (vLLM, Ollama, LM Studio, LiteLLM) |

With OpenRouter one key covers the whole chain:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODELS=google/gemini-2.5-flash,deepseek/deepseek-chat
```

The first model is vision-capable and receives the screenshot; the second is
text-only and is used only after local OCR, if the vision request fails.

## How it works

```
hotkey / tray / button
        ↓
ScreenCapture  (portal → gnome-screenshot → grim → spectacle | Qt on X11)
        ↓
preprocessing  (downscale ≤1600 px, flatten, JPEG)
        ↓
vision model   (Gemini → OpenRouter → OpenAI → custom)   ← screenshot
        ↓  (all vision providers failed)
OCR (tesseract) → text-only model (DeepSeek)             ← text only
        ↓
strict JSON  {question, answer, answer_text?, confidence, explanation}
        ↓
clipboard + desktop notification   (or the overlay)
```

* The screen is captured **only** on an explicit trigger — never continuously.
* The temporary image is deleted as soon as its bytes are read, before the
  request is sent; nothing is stored on disk afterwards.
* A screenshot is never uploaded to a model that cannot read images.
* No camera, no microphone, no telemetry, no autostart.
* Malformed JSON is repaired locally (fences, trailing commas, truncation); if
  that fails the model is asked once more, then the error is reported.

## Output modes

`output_mode = notification` (default)

* answer copied to the clipboard (answer text only, never the JSON),
* one desktop notification: *"Answer copied — B — Paris"*,
* nothing is drawn on the screen by the app.

`output_mode = overlay`

* small frameless, translucent, always-on-top window (25–40 % of the screen
  width, height follows the text, scrolls when long),
* top-center or bottom-center, configurable font size and opacity,
* `Copy` / `Close` buttons, `Esc` closes it, drag to move.

Switch in **Settings ▸ Output**.

## The F8 hotkey on Ubuntu 24.04

Check your session first:

```bash
echo $XDG_SESSION_TYPE     # wayland (default on Ubuntu 24.04) or x11
echo $XDG_CURRENT_DESKTOP  # ubuntu:GNOME
```

An ordinary application cannot grab a global key on GNOME Wayland, and this app
does not try to work around that. It uses the supported mechanism instead:

* **GNOME (Wayland and X11)** — Settings ▸ Hotkey ▸ *Register desktop shortcut*
  creates a normal GNOME custom shortcut (visible and removable under
  Settings ▸ Keyboard ▸ View and Customize Shortcuts ▸ Custom Shortcuts) that
  runs `run.sh --trigger`. That command talks to the running instance over a
  local socket; it does not start a second copy.
* **X11, any desktop** — if `pynput` is installed, the hotkey is grabbed
  in-process, no desktop configuration needed.
* **Other Wayland compositors (KDE, sway, …)** — bind the command shown in the
  Hotkey tab yourself in the desktop's own shortcut settings.

The tray menu and the control window's **Capture & Analyze** button always work.

## Wayland screen capture setup

```bash
sudo apt install xdg-desktop-portal xdg-desktop-portal-gnome gnome-screenshot
systemctl --user restart xdg-desktop-portal xdg-desktop-portal-gnome
```

On the first capture GNOME may ask for permission — allow it once. If the
portal is unavailable the app falls back to `gnome-screenshot`, `grim` or
`spectacle`; on X11 it uses Qt's own grab.

The app draws no flash or animation of its own. GNOME's own screenshot
indicator/flash comes from the shell and is **not** suppressed (that is the
system telling you the screen was captured). If you want to turn off desktop
animations generally, that is a user-side setting:

```bash
gsettings set org.gnome.desktop.interface enable-animations false
```

Backends differ: `grim` (wlroots) and Qt/`import` (X11) are silent, while
`gnome-screenshot` and the GNOME portal show the shell's flash.

## Settings

Settings dialog (tray ▸ *Settings…*, or the control window):

* API keys per provider (read-only when supplied by `.env`)
* preferred provider: auto / gemini / openrouter / openai / custom / deepseek
* model ids, including the OpenRouter model chain
* output: notification or overlay; overlay position, font size, opacity, width
* request timeout, hotkey, answer language

## Logging

`~/.local/share/screen-ai-analyzer/app.log` (rotating, 1 MB × 3). API keys are
scrubbed by both a log filter and the formatter. Users never see a traceback —
only a short message.

## Tests

```bash
source .venv/bin/activate
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
```

Covers JSON parsing/repair, the answer schema, Gemini response parsing,
DeepSeek/OpenAI-compatible requests, the vision-capability table, the provider
fallback chain, OCR, clipboard, notification output, overlay rendering and
geometry, configuration and key redaction, screenshot cleanup, the hotkey
strategy and the GNOME keybinding management.

## Known limitations (Ubuntu 24.04 / Wayland)

* No global key grab on GNOME Wayland — the GNOME custom shortcut (or the
  button/tray) is the supported route.
* The portal may ask for confirmation on first use and shows a capture
  indicator; both are intentional and are not bypassed.
* `QSystemTrayIcon` needs the AppIndicator GNOME extension; without it the
  control window is shown instead.
* Multi-monitor: the primary screen is captured (portal behaviour depends on
  the compositor).
* OCR quality on small fonts is mediocre; the text-only fallback is noticeably
  weaker than a vision model.
* `confidence` is the model's own self-assessment, not a measured accuracy.
