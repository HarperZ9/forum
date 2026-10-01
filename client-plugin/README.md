# Forum local client package

Forum previews how a request would be routed, what context it needs and whether it is ready to run, before anything runs.

## Try it

- Which Forum lane would handle: summarize last week's incident reports?
- Estimate the context pressure of this request before I run it.
- Show the communication contract for a request to draft release notes.

## Details

The source ZIP includes the tool source and one scoped skill. It requires an
installed Python 3.11+; this advanced source package is not self-contained.
Extract it to a persistent folder. Claude Code can load that plugin folder;
Codex-compatible loaders use plugin.json and mcp.json. For a generic local MCP
client, replace the plugin-root token with the absolute extraction path and
select the absolute runtime executable in that client's settings. Keep arguments
as a JSON array. This package never changes client settings automatically.

Route preflight never submits work. The packaged MCP exposes only six preflight tools, uses an in-memory ledger, and refuses submit and gate decisions. Grant execution separately through an explicitly configured host; the skill is not that grant.

The connected client supplies the model and pays any model-provider charges.
There is no publisher-hosted inference, relay or account requirement. Installing
a plugin does not authorize network calls, execution, publishing or production
deployment. Local MCP support differs between clients; ChatGPT cloud and Claude
web connections and marketplace acceptance are not established by this archive.

Build locally with Python 3.11+:

```sh
python scripts/build_client_plugin.py --mode dev --out ../client-artifacts
```

Development filenames include -dev. Their source receipt records the base commit
and every payload hash. They are not previously published bytes even when their
embedded version matches a release. Release mode requires a clean checkout,
an exact source tag and a version ending in .0; the ordinary tool release gates
still apply. Builders refuse to overwrite existing archives.

The Windows x64 ZIP and Claude Desktop MCPB include a frozen Python runtime and
need no separate Python installation. Their default MCP surface exposes only six
preflight tools. Submit, gate decisions and all launch arguments are refused.
Execution must use a separate explicitly configured Forum surface. The archive
includes Python and PyInstaller licenses, roster data, source hashes and a native
qualification receipt. Build with Python 3.12.10 and PyInstaller 6.21.0:

```sh
python scripts/build_native_forum.py --mode dev --out ../forum-native-candidate
```

Native qualification checks the executable with isolated state and a bounded
Windows process tree. This does not establish installed-client compatibility or
marketplace approval. Archive ordering is deterministic; reproducing the frozen
executable across different build environments is not claimed.
