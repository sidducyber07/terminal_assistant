# 🎙️ Nova — Voice Terminal Assistant

A terminal-based voice assistant that can listen, understand, and reply — in text and voice.

---

## Prerequisites

- **Python 3.8+** (`python --version` to check)
- **A microphone** (for voice input)
- **Speakers or headphones** (for voice output)

---

## Installation

### System dependencies

> **Windows**: Nothing extra needed.

> **macOS**: Nothing extra needed.

> **Linux (Ubuntu/Debian)**:
> ```bash
> sudo apt-get update
> sudo apt-get install -y portaudio19-dev python3-pyaudio espeak espeak-ng
> ```

### Python packages

```bash
pip install -r requirements.txt
```

---

## Run

```bash
python assistant.py
```

---

## What It Can Do

| Say / Type | What Happens |
|---|---|
| `hello` / `hi` | Greets you |
| `what time is it` | Tells the current time |
| `what's the date` / `today` | Tells today's date |
| `your name` / `who are you` | Introduces itself |
| `tell me a joke` | Tells a random joke |
| `tell me a fact` | Shares a random fact |
| `how are you` | Responds with a status |
| `history` | Shows your recent commands |
| `switch to voice` | Enables microphone input |
| `switch to text` | Disables microphone, keyboard only |
| `list voices` | Shows available TTS voices |
| `set voice 0` | Switches to voice #0 |
| `help` | Shows all commands |
| `quit` / `exit` / `bye` | Ends the session |

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│ Input Layer  │────▶│ CommandHandler│────▶│  Output Layer  │
│ Text / Mic   │     │  (the brain)  │     │ Text / Speaker │
└─────────────┘     └──────────────┘     └───────────────┘
```

Each layer is independent — swap any layer without touching the others.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| `PyAudio` won't install on Linux | `sudo apt-get install portaudio19-dev` first |
| `PyAudio` won't install on Mac | `brew install portaudio` first |
| Microphone not detected | Check system sound settings |
| Voice sounds robotic | Normal for offline TTS — change voice with `set voice N` |
| Speech recognition fails | Speak clearly, reduce background noise |
