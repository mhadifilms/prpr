# MCP server

`pmr` ships a [Model Context Protocol](https://modelcontextprotocol.io)
server so LLM agents (Claude, Cursor, and any MCP client) drive Premiere
through typed tools instead of shell parsing.

## Setup

```bash
pmr mcp install-claude    # writes Claude Desktop's config
pmr mcp install-cursor    # writes Cursor's config
pmr mcp serve             # or run the stdio server yourself
pmr mcp tools --detail    # introspect all tools + schemas
```

The server hosts the bridge itself — with Premiere running and the
`pmr bridge` panel open, tools connect lazily on first call. Meta tools
(`version`, `doctor`, `media_scan`, `render_presets`, static `schema`
topics) work even without Premiere, so first-time setup is instant.

## Tool surface

77 tools mirroring [`dvr`](https://github.com/mhadifilms/dvr)'s tool names
wherever the capability exists in both apps — an agent that knows dvr's
tools already knows pmr's:

- **State**: `ping`, `inspect`, `timeline_inspect`, `clip_where`,
  `media_inspect`, `media_bins`, `media_ls`
- **Projects/timelines**: `project_list/ensure/save/delete`,
  `timeline_list/ensure/switch/rename/delete/append/clear`
- **Markers**: `marker_add`, `marker_list`, `marker_remove`
- **Media**: `media_import`, `media_scan`, `media_bin_ensure`,
  `media_move`, `media_subclip`, `media_attach_proxy`, `media_transcribe`
- **Effects (pmr-only)**: `effects_list`, `effect_apply`,
  `effect_param_set` (transforms + keyframes), `transition_add`,
  `clip_components`, `timeline_insert_mogrt`, `timeline_scene_detect`
- **Export**: `render_presets`, `render_submit`, `render_frame`,
  `render_watch`, `interchange_export` (FCPXML/OTIO/AAF)
- **Declarative**: `apply_spec`, `spec_export`, `diff_timelines`,
  `diff_to_spec`, `snapshot_save/list/restore`, `lint`
- **Setup**: `doctor`, `plugin_install`, `plugin_status`, `reconnect`

Operations Premiere can't perform (`render_queue`, `page_set`,
`interchange_import`, ...) are still registered and return a structured
`NotSupportedError` with a `fix` naming the closest alternative — agents
get an actionable failure, never a missing tool. See
[parity](parity.md).

## Resources

`pmr://inspect`, `pmr://timeline/current`, `pmr://media/bins`,
`pmr://render/presets`, `pmr://doctor`, and `pmr://schema/<topic>`.

## Eval escape hatch

Set `PMR_MCP_ENABLE_EVAL=1` to expose the `eval` tool, which runs raw
JavaScript inside Premiere with the full `premierepro` module in scope
(the body of an `async (ppro, uxp, H, args) => {...}` function). dvr's
`eval` runs Python against Resolve; same tool name, same gate, same
spirit.

## Error shape

Failures return `isError: true` with dvr's error JSON:

```json
{"error": {"type": "TimelineError", "message": "...", "cause": "...", "fix": "...", "state": {...}}}
```
