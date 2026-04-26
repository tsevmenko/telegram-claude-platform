---
name: voice-transcribe
description: "Transcribe audio (.ogg, .wav, .mp3) to text via Groq Whisper API. Use when: voice file attached, transcribe audio, make a transcript."
user-invocable: true
argument-hint: "<audio-file-path>"
---

# Voice Transcribe

Transcribes any audio file to text using the Groq Whisper API.

## When to use

- An audio file is attached to a message and you need its content as text.
- The user asks to transcribe a recording, voice memo, or interview.
- You need to summarise a long voice note before answering.

## Setup

API key lives at `~/.claude-lab/shared/secrets/groq.key`. Get one at https://console.groq.com (large free tier).

```bash
mkdir -p ~/.claude-lab/shared/secrets
echo 'YOUR_KEY' > ~/.claude-lab/shared/secrets/groq.key
chmod 600 ~/.claude-lab/shared/secrets/groq.key
```

## Usage

```bash
bash $CLAUDE_SKILL_DIR/scripts/transcribe.sh /path/to/audio.ogg
```

Outputs the transcript to stdout. Exits non-zero on error with a message on stderr.

## Notes

- Model: `whisper-large-v3-turbo` (fast, ~0.5s for 30s of audio).
- Supports 50+ languages including Russian.
- Files larger than 25MB are rejected by the API — chunk them first.
