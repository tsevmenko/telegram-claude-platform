---
name: youtube-transcript
description: "Fetch a YouTube video transcript with timestamps. Use when: YouTube link, video transcript, summarise a video, what's in this video."
user-invocable: true
argument-hint: "<youtube-url>"
---

# YouTube Transcript

Fetch the transcript of a YouTube video. Two backends — `yt-dlp` (free, self-hosted) and TranscriptAPI (paid, faster).

## When to use

- The user shares a YouTube URL and wants a summary or timestamps.
- You need to quote or analyse what was said in the video.

## Setup

`yt-dlp` is installed by the system installer. No setup needed for the free path.

For TranscriptAPI fallback:

```bash
mkdir -p ~/.claude-lab/shared/secrets
echo 'YOUR_KEY' > ~/.claude-lab/shared/secrets/transcript-api.key
chmod 600 ~/.claude-lab/shared/secrets/transcript-api.key
```

## Usage

```bash
bash $CLAUDE_SKILL_DIR/scripts/fetch.sh https://www.youtube.com/watch?v=VIDEO_ID
```

Outputs the transcript to stdout, prefixed with timestamps when available.

## Notes

- `yt-dlp` strategy: download auto-generated subtitles (`--write-auto-subs --sub-format vtt`) and convert to timestamped lines.
- Falls back to TranscriptAPI if `yt-dlp` returns no subtitles (some videos have them disabled).
