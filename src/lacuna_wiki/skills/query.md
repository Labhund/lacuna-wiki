---
name: lacuna-query
description: Search, navigate, or ask questions about the wiki without ingesting anything. Use when the user asks what the wiki says about a topic, wants to read a page, or needs to look something up.
---

# Query Skill — lacuna

Use the `wiki` MCP tool to answer questions from the wiki. No writing. No ingesting.

---

## Tool Reference

Single tool: **`wiki`**. Exactly one of `q`, `page`, or `pages` per call.

**Search** — hybrid semantic + keyword:
```
wiki(q="your query", scope="wiki")
```
`scope` values: `"wiki"` (compiled pages, default), `"sources"` (raw source chunks), `"all"` (both).

**Navigate** — read a page or section:
```
wiki(page="slug")
wiki(page="slug", section="Section Name")
```

**Multi-read** — read several pages at once:
```
wiki(pages=["slug-a", "slug-b"])
```

---

## How to Answer a Question

1. **Formulate a one-sentence query** from the user's question — fuller sentences outperform keywords.
2. **Search** with `scope="wiki"`. Read the top results.
3. **Navigate** to any page with score > 0.7 to read the full content.
4. **Answer** directly, citing the page slug: `(→ [[slug]])`.

If nothing relevant is found, say so. Do not invent content.

---

## When scope="sources" is useful

Use `scope="sources"` or `scope="all"` when:
- The user asks about a specific paper or source by name
- The question is about evidence or experimental detail that may only be in raw source chunks, not compiled wiki pages
