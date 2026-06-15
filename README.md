<div align="center">
  <img src="docs/assets/banner.png" alt="Lacuna" width="800"/>

  <br/>

  [![PyPI](https://img.shields.io/pypi/v/lacuna-wiki?color=6e40c9&label=lacuna-wiki)](https://pypi.org/project/lacuna-wiki/)
  [![Python](https://img.shields.io/pypi/pyversions/lacuna-wiki?color=3776AB)](https://pypi.org/project/lacuna-wiki/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
  [![Stars](https://img.shields.io/github/stars/Labhund/lacuna-wiki?style=social)](https://github.com/Labhund/lacuna-wiki)

  **Give your agent a knowledge graph that compounds.**

  *Drop in a URL. Your agent handles the rest.*
</div>

---

Lacuna is a single MCP tool — `wiki` — that you plug into your existing agent harness (Claude Code, Hermes, OpenClaw) to give it a searchable, compounding personal research graph. Feed it a YouTube URL, an arXiv link, or a downloaded PDF. Your agent runs the structured extraction. The knowledge accumulates across every session.

Your vault is plain markdown — works natively with [Obsidian](https://obsidian.md/). Browse your knowledge graph as a human, query it as an agent. Same files, no sync required.

It is the *lacuna* — the missing link between your raw inputs and your second brain.

---

## Quick Start

```bash
pip install lacuna-wiki
lacuna init ~/my-vault
```

`lacuna init` creates your vault directory structure, sets up the DuckDB index in `~/.lacuna/`, offers to wire the MCP server into Claude Code and/or Hermes, installs agent skills, and sets up the daemon as a systemd service. Takes about 10 seconds.

---

## What Your Agent Unlocks

Once connected, your agent gets one composable tool:

```
wiki(q="attention mechanisms")          # hybrid semantic + keyword search
wiki(page="transformer-architecture")   # navigate to a specific page
wiki(pages=["sdpa", "flash-attn"])      # pull multiple pages in one shot
wiki(q="...", scope="sources")          # search raw source chunks directly

# sweep — audit and queue
wiki(link_audit=True)                              # vault audit: research gaps, ghost pages, sweep queue
wiki(link_audit=True, limit=10)                    # compact audit: counts only + top N sweep items
wiki(sweep="slug")                                 # single-page audit + top synthesis candidates
wiki(sweep="slug", mark_swept=True, cluster={...}) # mark page swept; optionally queue a cluster

# synthesise — read and write synthesis clusters
wiki(synthesise=True)                   # list pending synthesis clusters
wiki(synthesise=N)                      # detail for cluster N: members, paths, coverage scores
wiki(synthesise=N, commit={"slug":"…"}) # mark cluster synthesised; links synthesis page in DB
```

That's it. One tool. Your entire research graph.

---

## Omnivorous Inputs

Feed Lacuna anything — it knows what to do:

| Source | Command |
|--------|---------|
| 📺 YouTube URL | `lacuna add-source https://youtube.com/watch?v=...` |
| 📄 arXiv link | `lacuna add-source https://arxiv.org/abs/2310.06825` |
| 📑 Local PDF | `lacuna add-source ~/papers/my-paper.pdf` |
| 🌐 Any URL | `lacuna add-source https://example.com/blogpost` |

---

## The Structured Skills

This is where Lacuna is different from dropping a folder of PDFs into a vector store.

Lacuna ships with agent skills for Claude Code and Hermes that encode a **structured, multi-turn extraction workflow** — not "summarize this" but a disciplined process that produces tagged, wikilinked pages with full citations. When your agent ingests a paper, it follows the skill's protocol: pulling core concepts, mapping relationships to your existing graph, and flagging gaps.

Install them into your harness:

```bash
lacuna install-skills --claude-global    # → ~/.claude/skills/
lacuna install-skills --hermes-global    # → ~/.hermes/skills/
lacuna install-skills --openclaw-global  # → ~/.openclaw/skills/
lacuna install-skills --hermes PATH      # custom Hermes skills directory
```

Skills included:
- **ingest** — structured multi-turn knowledge extraction from a source
- **query** — cited, honest answers from your graph (flags what's missing)
- **adversary** — re-verifies old claims against their cited sources
- **sweep** — audits the vault for missing `[[wikilinks]]`, adds them, and queues related pages as synthesis candidates
- **synthesise** — reads the synthesis queue and writes unified pages from clusters of related content

---

## The Compounding Graph

Lacuna outputs aren't isolated notes. Each extraction is structured to deliberately compound — new pages wikilink to existing ones, concepts accumulate across sessions, and the graph gets richer with every source you add.

Under the hood: hybrid BM25 + vector search over a DuckDB store. No format lock-in — your vault is just a folder.

```
my-vault/
├── wiki/                  # compiled knowledge pages (Obsidian-readable)
│   ├── attention.md
│   ├── transformer-architecture.md
│   └── ...
├── raw/                   # original sources
│   ├── vaswani2017/
│   └── ...
└── .lacuna.toml           # vault config
```

---

## Embedding Backend

Lacuna needs an OpenAI-compatible embeddings endpoint. The easiest path is [Ollama](https://ollama.com):

```bash
# Install Ollama: https://ollama.com/download
ollama pull nomic-embed-text:v1.5
```

Then set your vault's `.lacuna.toml` (created by `lacuna init`):

```toml
[embed]
url = "http://localhost:11434"   # Ollama's default port
model = "nomic-embed-text:v1.5"  # default — can omit
dim = 768                         # default — can omit

[worker]
sync_workers = 4        # parallel threads for initial_sync (default: 4)
embed_concurrency = 4   # simultaneous embed requests (default: 4)
reader_pool_size = 3    # read connections for MCP + status API (default: 3)
```

`LACUNA_EMBED_URL`, `LACUNA_EMBED_MODEL`, `LACUNA_EMBED_DIM`, `LACUNA_SYNC_WORKERS`, `LACUNA_EMBED_CONCURRENCY`, and `LACUNA_READER_POOL_SIZE` env vars also work for one-off overrides.

> **Changing models?** Set `embed.dim` in `.lacuna.toml` before running `lacuna init` — the schema is created from that value. Changing the model or dim after ingesting sources will invalidate existing embeddings. A `lacuna reindex` command to re-embed everything in place is planned; for now, delete `~/.lacuna/vaults/<your-vault>/` and re-run `lacuna init` to start fresh.

---

## Requirements

- Python 3.11+
- `pdftotext` (poppler-utils) for PDF extraction: `apt install poppler-utils` / `brew install poppler`
- An embedding server (Ollama, OpenAI, or any OpenAI-compatible endpoint)

---

## Status

Early release. The core loop — add source → agent ingests → agent queries — is solid. The structured skills are where the value is; treat them as opinionated defaults you can adapt.

Windows support is in progress (Linux/macOS fully supported today).

---

## Keeping the Graph Tidy

Ingest adds knowledge — sweep and synthesise maintain it.

**Sweep** audits the vault for missing `[[wikilinks]]` and detects pages that are converging on the same concept. For each page in the backlog, the agent reads it, adds any missing links one at a time, and declares a synthesis cluster if multiple pages are describing the same concept from different angles. Run it periodically in Claude Code / Hermes:

```
/lacuna-sweep
```

After a large ingest, pre-warm the candidate cache before running the sweep skill so it doesn't time out on big vaults:

```bash
lacuna sweep           # process all pages in the backlog
lacuna sweep --batch 50  # process the next 50 pages
lacuna sweep --force     # recompute all pages regardless of last_swept
```

When the daemon is running, `lacuna sweep` submits the job to the daemon and polls for completion — the DB stays locked to one writer. When no daemon is running, it runs directly.

**Synthesise** consumes the synthesis queue populated by sweep. It reads each cluster, writes a unified synthesis page from the combined content of the member pages, and marks the members as synthesised. The synthesis page surfaces shared ground, disagreements, and source provenance in one place:

```
/lacuna-synthesise
```

Both skills support an `auto` mode for unattended runs — pass `"auto"` or `"just run it"` when invoking.

`lacuna status` shows the full queue state at a glance:

```
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━┓
┃ Table              ┃ Rows ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━┩
│ pages              │  106 │
│ research gaps      │    8 │  ← stub pages awaiting sources
│ ghost pages        │    5 │  ← slugs linked but not yet created
│ sweep backlog      │   23 │  ← pages needing a sweep pass
│ synthesis queue    │   12 │  ← clusters ready for synthesise
│ synthesised pages  │    4 │  ← members absorbed into a synthesis page
│ sections           │  464 │
│ sources            │   19 │
└────────────────────┴──────┘
```

---

## Manual MCP Setup

`lacuna init` handles all of this automatically. If you need to wire things by hand:

**Start the daemon first.** The daemon owns the database exclusively — all MCP clients connect to it via HTTP. Without the daemon, nothing works.

```bash
lacuna start
# Or, for a permanent setup:
lacuna init  # offers to set up systemd service during wizard
```

**Claude Code**

```bash
claude mcp add --transport http --scope user lacuna http://127.0.0.1:7654/mcp
```

**Hermes** (`~/.hermes/config.yaml`)

```yaml
mcp_servers:
  lacuna:
    url: "http://localhost:7654/mcp"
```

**OpenClaw**

```bash
openclaw mcp set lacuna '{"url":"http://127.0.0.1:7654/mcp"}'
```

The daemon must be running (`lacuna start` or the systemd service) for any client to connect. All clients share the daemon's connection pool — no lock contention, no conflicts.

---

## Upgrading

```bash
pip install --upgrade lacuna-wiki
lacuna sync
```

`lacuna sync` applies any schema migrations automatically — safe to run on every upgrade. When the daemon is running, sync delegates to it via the status API (no lock contention, no need to stop anything).

---

## Running the Daemon

The daemon watches your vault for changes, handles embedding and DB registration, and serves the MCP API. The recommended setup is a systemd user service (auto-starts on login, survives agent restarts):

```bash
lacuna init  # offers to set up systemd service during wizard
```

Or manually:

```bash
# One-time: write and enable the service file
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/lacuna-daemon.service << 'EOF'
[Unit]
Description=lacuna wiki daemon — file watcher and MCP server
After=network-online.target

[Service]
Type=simple
ExecStart=/home/you/.local/bin/lacuna _daemon-run /path/to/vault
ExecStop=/home/you/.local/bin/lacuna stop
WorkingDirectory=/path/to/vault
Restart=on-failure
RestartSec=5
StandardOutput=append:%h/.lacuna/daemon.log
StandardError=append:%h/.lacuna/daemon.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now lacuna-daemon.service
```

For ad-hoc use, `lacuna start` / `lacuna stop` work fine — just note that if started from within an agent process (e.g. Hermes gateway), the daemon will be killed when that process restarts. The systemd service avoids this by owning its own cgroup.

---

## License

MIT © Markus Williams, 2026
