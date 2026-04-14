# lacuna-v2 — Agent Instructions

This is the implementation repository for lacuna-v2.

Before doing any work here, read the design specification:

```
docs/design/2026-04-14-v2-design-draft.md
```

The spec is the authority on architecture, philosophy, schema, skill flows, and conventions. All implementation decisions should be traceable to it.

## Testing

When testing CLI commands or running the ingest skill as part of development, use the fixture vault — not the production wiki:

```
tests/fixtures/wiki-vault/
```

Run all `lacuna` commands from that directory (or pass it as context). This vault contains pre-seeded pages and sources for the transformer/attention domain and is safe to modify.

Do **not** run test ingests against `/home/labhund/wiki`.
