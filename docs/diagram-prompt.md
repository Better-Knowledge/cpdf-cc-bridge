# Image-generation prompts — `tgbridge` architecture diagram

Generic prompts to render an architecture diagram of the `tgbridge` library with GPT-image-2 (or a similar text-to-image model).

Use the **short** version for a clean slide figure; the **long** version when you want every label and the full inbound/outbound flow; the **fleet** version for several agents on one network; and the **matrix** version for two cooperating agents with persona + hierarchical memory + A2A. The prompts are written in English (image models adhere better to technical terms in English); swap the label language/palette if you want everything in another language.

> Generation tip: ask for **16:9 (landscape)**, **light background**, **crisp legible text**, and explicitly say *"render all labels as crisp, correctly-spelled English text"* — image models mangle text, so short labels help.

The agent is referred to as `my-agent` throughout. For the multi-agent versions, two generic agents are shown side by side as `agent-a` and `agent-b`.

---

## Short version (slide / overview)

```
A clean, modern technical software-architecture diagram, isometric flat-design style, 16:9 landscape, light background, soft shadows, rounded rectangle nodes, clear labeled arrows.

Show a left-to-right data flow with three zones:

1. LEFT — "Telegram Cloud": a phone with the Telegram logo and a user labeled "Authorized user (allow-list)", connected by a double arrow to a cloud labeled "Telegram Bot API (long-polling)".

2. CENTER — a large server box labeled "Container 'my-agent'", containing two stacked panels:
   - top panel "tmux session" holding a terminal window labeled "CLI coding agent (interactive, subscription login)";
   - bottom panel "tgbridge (single Python process)" holding three small blocks: "Telegram I/O", "Hook receiver 127.0.0.1:8787", "Scheduler (cron)". A small database cylinder labeled "SQLite state".

3. RIGHT — "External services": a cloud box "LLM API".

Arrows:
- From Telegram cloud to "Telegram I/O" (bidirectional).
- A green inbound arrow from "Telegram I/O" to the agent terminal labeled "tmux send-keys".
- A blue outbound arrow from the agent terminal to "Hook receiver" labeled "HTTP hook on Stop (Bearer token)".
- From the CLI agent to the external cloud.
- Two folder icons under the container labeled "bind mount: workspace" and "bind mount: config (login persists)".

Color palette: Telegram blue (#229ED9) for messaging, emerald green for the inbound path, indigo for the outbound hook path, neutral grays for infrastructure. Minimal, professional, lots of whitespace, no clutter. Render all labels as crisp, correctly-spelled English text.
```

---

## Long version (technical, all labels + data pipeline)

```
A detailed, professional technical architecture diagram of a Telegram-to-CLI-agent bridge, flat vector style with subtle isometric depth, 16:9 landscape, light neutral background (#F7F8FA), rounded-rectangle nodes with thin borders and soft drop shadows, clean sans-serif labels, clearly directed labeled arrows. Organized in three vertical zones separated by faint dividers.

ZONE 1 — "Telegram (cloud)", top-left:
- A smartphone showing a chat bubble, labeled "Authorized user · ALLOWED_USERS allow-list".
- A cloud node "Telegram Bot API (getUpdates long-polling, no webhook)".
- Double-headed arrow between them.

ZONE 2 — center, a big rounded container titled "Host → Docker container 'my-agent' (debian-slim)". Inside, top to bottom:
- Panel "tmux session 'my-agent'" containing a dark terminal window "CLI coding agent — interactive, headless, subscription login (no API key)".
- Panel "tgbridge — one asyncio process" containing three side-by-side blocks:
    (a) "Telegram I/O — long-polling + ALLOWED_USERS gate + router",
    (b) "Hook receiver — FastAPI, 127.0.0.1:8787, Bearer auth",
    (c) "Scheduler — cron + one-shot".
- A database cylinder "SQLite — state.db / jobs.db (session bindings, dedup, jobs)".
- Two folder icons at the bottom edge labeled "bind mount: workspace → /home/my-agent (config, code)" and "bind mount: config → /config (login, settings, hooks — persists across rebuilds)".
- A small key icon ".env (env_file): tokens & secrets injected".

ZONE 3 — right, "External services (egress)":
- Cloud "LLM API".

ARROWS / DATA FLOW (color-coded, each with a label):
- EMERALD GREEN "INBOUND": Telegram I/O → agent terminal, label "tmux send-keys -l + Enter".
- INDIGO "OUTBOUND": agent terminal → Hook receiver, label "HTTP hook on Stop / Notification (Authorization: Bearer)". Then Hook receiver → Telegram I/O → back to Telegram cloud, label "formatted reply".
- GRAY: Scheduler → agent terminal, label "inject scheduled prompt".
- GRAY: CLI agent → external cloud.

BOTTOM STRIP — a small horizontal pipeline labeled "Output formatting" with five chained chips:
"transcript JSONL" → "extract last assistant" → "stabilize (read_final)" → "dedup by uuid" → "markdown→MarkdownV2, split ≤4096" → "send to Telegram".

Palette: Telegram blue (#229ED9) for messaging, emerald (#10B981) for inbound, indigo (#6366F1) for outbound hooks, slate grays (#475569) for infrastructure, amber accent for secrets/keys. Professional, balanced composition, generous whitespace, no photorealism, no people faces. Render every label as crisp, correctly-spelled English text; keep labels short.
```

---

## Fleet version (multi-agent + shared Whisper)

Use this to illustrate **several agents, each with its own bot**, optionally sharing a single Whisper voice service.

```
A clean technical architecture diagram, flat vector style with subtle isometric depth, 16:9 landscape, light background, rounded-rectangle nodes, color-coded labeled arrows.

TOP — "Telegram (separate bots)": three phone/chat icons labeled "@agent-a", "@agent-b", "@agent-c", each a distinct color.

CENTER — a large rounded box "Docker network: tgbridge-net" containing:
- three identical agent containers side by side, each labeled "agent container: tgbridge + CLI agent (tmux) · own .env · own bot token · receiver 127.0.0.1:8787 (private)";
- one wider box at the bottom labeled "tgbridge-whisper (optional) — faster-whisper, OpenAI-compatible /v1/audio/transcriptions, 1 model in a shared volume, 1 process in RAM".

RIGHT — a cloud "Cloud voice API (default)".

ARROWS:
- Each bot ↔ its own agent container (matching colors), label "1 bot per agent".
- Each agent → the shared whisper box, label "OPENAI_BASE_URL=http://whisper:8000/v1".
- One agent → cloud voice (dashed), label "or cloud voice (just an API key)".
- A small host-side icon labeled "tgbridge up <agent> — ensures network + whisper" pointing at the network box.

Emphasize: agents are isolated (own token, private hook port — no collision); voice is optionally shared to save disk/RAM, with cloud voice as the lightweight default. Palette: Telegram blue, emerald for shared-voice links, indigo for the host wrapper, slate grays for infra. Crisp, correctly-spelled English labels, short.
```

---

## Matrix version (two agents with soul + hierarchical memory + A2A)

Use this for the **full** architecture: two agents side by side on one shared network, each with its own **soul layer** (persona) and **hierarchical memory**, exchanging **per-agent A2A** messages. Includes the matrix `init` scaffolder and the infra secret for ephemeral sessions.

```
A detailed, professional technical architecture diagram of a multi-agent CLI-agent fleet, flat vector style with subtle isometric depth, 16:9 landscape, light neutral background (#F7F8FA), rounded-rectangle nodes with thin borders and soft drop shadows, clean sans-serif labels, clearly directed labeled arrows. Two agents side by side inside one shared Docker network.

TOP — "Telegram (separate bots)": two phone/chat icons labeled "@agent-a" and "@agent-b", each a distinct color, each connected by a double-headed arrow down to its own agent column.

CENTER — a large rounded box "Docker network: tgbridge-net" containing TWO identical agent columns side by side, "AGENT: agent-a" (left) and "AGENT: agent-b" (right). Inside EACH column, stacked top to bottom:
- Panel "tgbridge (one asyncio process)": "Telegram I/O + ALLOWED_USERS gate", "Hook receiver 127.0.0.1:8787 (Bearer)", "Scheduler (cron + one-shot)", small cylinder "SQLite state".
- Panel "tmux session" with a dark terminal "CLI coding agent (interactive, subscription login)".
- Block "Persona / Soul (workspace)": "CLAUDE.md (lightweight orchestrator)" that @-includes five chips "IDENTITY.md · SOUL.md · USER.md · TOOLS.md · AGENTS.md".
- Block "Hierarchical memory + Projects (workspace)": "memory/INDEX.md (lightweight map)" pointing to "topics/<slug>.md (durable knowledge, [[links]])", "daily/ (logs)", "archive/"; and "projects/ — README-per-folder (status in frontmatter)". Caption "regenerable indices".
- A small key icon "/config/bridge.secret (0600) — infra secrets".

A2A LINK — between the two agent columns, a bold double-headed arrow labeled "A2A over tgbridge-net :8788", with sub-label "bearer per-agent (target's secret) + allowlist + rate-limit". Show it touching both columns so agent-a ↔ agent-b can call each other.

INIT / MATRIX — at the bottom-left, a small factory/seed icon labeled "tgbridge init (matrix templates)" with a dashed arrow pointing at a new (faded) agent column, caption "new agents are born with infra + soul + memory".

RIGHT — "External services (egress)": a cloud "LLM API". Gray arrows from each agent terminal to this cloud.

ARROWS / DATA FLOW (color-coded, each with a label):
- EMERALD GREEN "INBOUND" (per agent): Telegram I/O → agent terminal, label "tmux send-keys".
- INDIGO "OUTBOUND" (per agent): agent terminal → Hook receiver → Telegram I/O → Telegram, label "HTTP hook on Stop (Bearer) → formatted reply".
- AMBER (per agent): the skills inside the tmux session read "/config/bridge.secret" in env-scrubbed ephemeral sessions, caption "anti-exfil env-scrub".
- VIOLET: the A2A link between the two agents (the bold double-headed arrow above).

Emphasize: each agent is self-contained (own bot token, own private hook port, own soul + memory), they cooperate via per-agent A2A on the shared network, and new agents are scaffolded from the matrix. Palette: Telegram blue (#229ED9) for messaging, emerald (#10B981) for inbound, indigo (#6366F1) for outbound hooks, violet (#8B5CF6) for A2A, amber for secrets/keys, slate grays (#475569) for infrastructure. Professional, balanced composition, generous whitespace, no photorealism, no people faces. Render every label as crisp, correctly-spelled English text; keep labels short.
```

---

## Suggested palette

| Role | Color | Hex |
| --- | --- | --- |
| Messaging (Telegram) | Telegram blue | `#229ED9` |
| Inbound path (tmux send-keys) | Emerald | `#10B981` |
| Outbound path (Stop hook) | Indigo | `#6366F1` |
| A2A links (multi-agent) | Violet | `#8B5CF6` |
| Secrets / keys | Amber | `#F59E0B` |
| Infrastructure / neutral | Slate gray | `#475569` |
| Background | Light neutral | `#F7F8FA` |

---

## Notes

- To match **one** specific zone (e.g. just the formatting pipeline, just the Docker bind mounts, or just the A2A exchange between two agents), tell the model to focus on that zone and remove the rest of the prompt.
- For another language, swap the labels and keep the final instruction as *"render all labels as crisp, correctly-spelled <language> text"*.
- `my-agent`, `agent-a`, `agent-b` (and `@agent-c` in the fleet version) are placeholders — rename them to your own bot/agent names when generating the figure.
```