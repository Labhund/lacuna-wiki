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

`lacuna init` creates your vault directory structure, sets up the DuckDB index in `~/.lacuna/`, and asks whether to wire the MCP server into Claude Code and/or Hermes automatically. Takes about 10 seconds.

---

## What Your Agent Unlocks

Once connected, your agent gets one composable tool:

```
wiki(q="attention mechanisms")          # hybrid semantic + keyword search
wiki(page="transformer-architecture")   # navigate to a specific page
wiki(pages=["sdpa", "flash-attn"])      # pull multiple pages in one shot
wiki(q="...", scope="sources")          # search raw source chunks directly
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
```

`LACUNA_EMBED_URL`, `LACUNA_EMBED_MODEL`, and `LACUNA_EMBED_DIM` env vars also work for one-off overrides.

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

## [[Wikilink]] Cleanup
The agents are given detailed instructions that enforce proactive addition of [[wikilinks]] but sometimess (especially using smaller local models!) your agent will miss a few. For now periodically ask your agent to: 
- *"please crawl ~/path/to/vault and add all [[wikilinks]] for proper nouns and key concepts in each page where they are missing"*

> Planned Feature: Dedicated skill and tool to help your agent discover pages that are likely missing [[wikilinks]]

---

## Manual MCP Setup

`lacuna init` handles all of this automatically. If you need to wire things by hand:

**Claude Code**

Claude Code requires two files. First, the server config at your vault root:

```json
// /path/to/my-vault/.mcp.json
{
  "mcpServers": {
    "lacuna": {
      "command": "/full/path/to/lacuna",
      "args": ["mcp"],
      "env": { "LACUNA_VAULT": "/path/to/my-vault" }
    }
  }
}
```

Find the full path with `which lacuna`. Then auto-approve it so Claude Code connects without a prompt:

```json
// /path/to/my-vault/.claude/settings.local.json
{
  "enableAllProjectMcpServers": true
}
```

Add `.claude/settings.local.json` to your `.gitignore` — it's a per-user approval file. Optionally also add the entry to `~/.claude/mcp.json` as a global fallback.

**Hermes (`~/.hermes/config.yaml`)**
```yaml
mcp_servers:
  lacuna:
    command: lacuna
    args: [mcp]
    env:
      LACUNA_VAULT: /path/to/my-vault
```

**OpenClaw**
```bash
openclaw mcp set lacuna '{"command":"lacuna","args":["mcp"],"env":{"LACUNA_VAULT":"/path/to/my-vault"}}'
```

---

## License

MIT © Markus Williams, 2026
