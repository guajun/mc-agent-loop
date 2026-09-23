# mc-agent-loop

📖 Part of **mc-agent**; the guide lives at <https://guajun.github.io/mc-agent/>.

A small, generic agent loop for Minecraft: it listens to chat through the
`mc-agent-bridge`, wakes a backend when somebody addresses the agent, and posts
the answer back into the game.

It contains no game logic. Nothing here knows what a sulfur cube is - that
belongs to whichever backend or tool you plug in.

```
 chat event ──► bridge daemon ──► this loop ──► backend ──► reply
                                     │                        │
                                     └──── bridge: chat/command ┘
```

## Why the loop is the active side

MCP servers are spawned *by* the agent, so they can never wake it: the game
cannot call into a tool. Anything event-driven therefore needs a resident
listener on the agent's side, which is what this process is. The bridge stays
passive and reusable; the loop is the piece you can restart, swap or run
several of.

## Install

```bash
pip install -e ../bridge     # the loop depends on the bridge package
pip install -e .
```

You also need the bridge daemon running (`mc-bridge run`) and the
`mc-agent-interface` mod loaded in the game.

## Quick start

```bash
# 1. make sure the bridge is up
mc-bridge call state

# 2. hear yourself think, no model involved
mc-agent-loop run --backend echo --trigger @codex

# 3. the real thing
mc-agent-loop run --backend hermes --trigger @codex
```

Now typing `@codex what is your position?` in game chat gets an answer.

By default the triggers are `@codex`, `@agent` and `!ai`; pass `--trigger`
one or more times to replace them.

## Backends

| Name | What it is | Notes |
| --- | --- | --- |
| `hermes` | Nous Research **hermes-agent** over its OpenAI-compatible API | default; the primary runtime for this framework |
| `echo` | local stub | no model, used by the tests |
| `codex` | Codex CLI | experimental: one process per reply |

### Hermes

Start a Hermes API server, then point the loop at it. Defaults are
`http://127.0.0.1:8642` and model `hermes-agent`; override with
`--hermes-url` / `--hermes-model` or the environment:

| Variable | Meaning |
| --- | --- |
| `HERMES_API_BASE` | API base URL, default `http://127.0.0.1:8642` |
| `HERMES_MODEL` | model name, default `hermes-agent` |
| `HERMES_API_KEY` | bearer token, if your build requires one |

Any of them can live in a file instead of the shell environment:

```bash
mc-agent-loop run --backend hermes --trigger @codex --env-file ../.env
```

`--env-file` falls back to `./.env` when it exists, and variables already set in
the environment win. The key therefore never has to appear in a command line or
in shell history.

Hermes can call the bridge as a tool. Register the MCP front-end
(`mc-bridge mcp`) in your Hermes MCP configuration and the model gets
`mc_state`, `mc_entities`, `mc_command`, `mc_record_start`, `mc_events` and the
rest - so it can look things up instead of guessing.

### Codex (experimental)

```bash
mc-agent-loop run --backend codex --codex-bin codex --codex-cwd <workspace>
```

Each reply spawns a fresh `codex exec`, so replies are slower and the process
has no memory of the previous turn beyond the short history the loop passes in.
Useful for driving a Codex session from chat; not the recommended default.

## One-shot mode

The agent does not have to be resident. Anything that can run a command can ask
for a single turn:

```bash
mc-agent-loop once "summarise what you can see" --sender operator
mc-agent-loop once "wrap up and report" --backend hermes --trigger @codex
```

That is the hook for external schedulers, cron-style self-directed runs, or a
one-off "trigger an experiment, wait, report" flow. The loop itself never
schedules anything; it just answers. Triggers, the duplicate guard and
cooldowns do not apply to one-shot turns - they exist to keep chat civil.

## Behaviour worth knowing

* **Self-echo.** The agent ignores chat whose sender matches its own player
  name, so it cannot answer itself forever.
* **Stale chat.** Messages older than `--max-age` (default 120s) are dropped, so
  a backlog is not replayed after a restart.
* **Cooldowns.** `--cooldown` per sender, `--min-reply-interval` overall.
* **Chunking.** Long replies are split at `--chunk-size` (default 220 chars)
  with `--chunk-delay` between them, because chat lines are short.
* **Failure isolation.** A backend error is logged and the loop keeps running.

## Reply modes

`--reply-mode chat` (default) sends the reply as the player's chat message.
`--reply-mode command` runs a command instead, with `{json}` replaced by the
reply text component:

```bash
mc-agent-loop run --reply-mode command --reply-command 'tellraw @a {json}'
```

`{text}` is the same thing without the JSON wrapper, which is what a fake player
needs to speak under its own name (the fake player has no command permission of
its own, but the server can broadcast for it):

```bash
mc-agent-loop run --reply-mode command \
  --reply-command 'execute as deepseek run say {text}'
```

## CLI reference

```
mc-agent-loop run      [--backend NAME] [--trigger PREFIX]... [--api-port N] ...
mc-agent-loop once     TEXT [--sender NAME] [--backend NAME] ...
mc-agent-loop backends
```

`mc-agent-loop run --help` lists every tunable: triggers, ignore lists,
cooldowns, history depth, timeouts, chunking, system prompt.

## Tests

The suite drives the loop against a fake bridge, so no game or model is needed:

```bash
PYTHONPATH=src:../bridge/src python -m unittest discover -s tests -t .
```

## License

MIT
