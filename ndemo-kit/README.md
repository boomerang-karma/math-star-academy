# ndemo kit — record narrated client demos

A ready-to-run wrapper around [splitbrain/ndemo](https://github.com/splitbrain/ndemo):
an installer, a self-contained sample app with a finished playbook, and a
run script that renders it with or without narration.

## Quick start (macOS)

```bash
cd ~/Claude/ndemo-kit && ./setup.sh
echo 'export OPENAI_API_KEY=sk-...' >> ~/.zshrc && source ~/.zshrc
./run-sample.sh --silent     # then ./run-sample.sh for the narrated version
```

Output lands in `out/`: `sample-tour-silent.mp4` / `sample-tour-narrated.mp4`, each with an `.srt`.

| Command | What it does | Needs API key |
|---|---|---|
| `./setup.sh` | brew-installs node/ffmpeg if missing, clones ndemo (pinned), builds, installs Chromium, links the Claude Code skill to `~/.claude/skills/ndemo`, runs `ndemo doctor` | no |
| `./run-sample.sh --silent` | renders the sample with no narration | no |
| `./run-sample.sh` | renders with OpenAI TTS narration | yes |
| `./run-sample.sh --live` | plays the demo in a visible browser (rehearsal, no recording) | no |
| `./run-sample.sh --live --audio` | rehearsal with narration through your speakers (needs `ffplay`, ships with brew ffmpeg) | yes |
| `--port N`, `--open` | change the sample server port; open the mp4 when done | |

## Making a demo of a client's app

1. Start the client app (staging, seeded data — see *Limitations*).
2. Open Claude Code in that app's repo. The skill is linked globally, so ask:
   > Create a narrated demo of http://localhost:3000. Show: (1) the dashboard,
   > (2) filtering by region, (3) exporting a report. Log in with demo/demo.
3. Claude writes `demo/<name>/<name>.yaml`, drives a real browser, and fills in
   the actions. Review segment by segment (`ndemo play … --segment <id>`),
   then render.

Or start from `sample/demo/sample-tour/sample-tour.yaml`: copy it, change
`app.url`, rewrite `narration`/`intent`, empty the `actions`, and ask Claude
Code to author them.

Playbook levers that matter for client video:
- `timing: parallel` makes actions happen while the voice speaks (natural); default `after` speaks first, then acts.
- `type` actions take `delay` (ms per keystroke); 70–110 looks human.
- `tts.voice` / `tts.speed` change the voice; narration audio is cached by
  text+voice+speed, so re-renders only pay for segments you changed.
- `scale: 2` renders 3840×2160; `scale: 1` renders 1920×1080 and is faster.

## Limitations (read before a client deadline)

- **Tested on Linux, not on your Mac.** Setup, silent render, and the narrated
  merge path were run end-to-end in a Linux container (Node 22, ffmpeg 6.1).
  The narrated test used pre-seeded audio files, so the actual OpenAI TTS call
  has not been exercised. The macOS steps (brew, `playwright install`) are
  standard but unverified here.
- **`ndemo render` rewrites the playbook it renders**: it re-serializes the YAML
  (comments and formatting are lost) to store measured durations. The kit renders
  a copy in `out/`; for your own playbooks keep them in git.
- **Title cards render tiny** at this ndemo version (the title page is a `data:` URL
  and Chrome's zoom is per-origin). The sample leaves `titleCard` out; add titles in your editor.
- **Only OpenAI TTS works.** The schema accepts `provider: elevenlabs`, but it
  is not implemented and the render fails.
- **Narration text goes to OpenAI.** Model `tts-1-hd`; cost is per character
  (the sample is ~600 characters, a few cents). Check current OpenAI pricing.
- **Client data shows on screen and passwords sit in plain-text YAML.** Record against
  staging with demo accounts and fake data.
- **Renders use a fresh browser profile every time.** Login, cookie banners and
  seed data must be handled in `app.setup` (conditional steps with `if:`).
- **ndemo is v0.1.0 with no releases.** The kit pins commit `d60e17e`. To try a
  newer one: `NDEMO_REF=main ./setup.sh`, then re-run the sample before trusting it.
- `ndemo doctor` marks a missing `OPENAI_API_KEY` as a failure; silent renders don't need it.

## Layout

```
setup.sh, run-sample.sh
sample/app/index.html            sample web app (fixed seed data, repeatable)
sample/serve.mjs                 zero-dependency static server
sample/demo/sample-tour/*.yaml   finished playbook (source of truth)
tools/prepare-playbook.mjs       makes the render copy (port, --silent)
ndemo/  out/  .ndemo/            generated, git-ignored
```
