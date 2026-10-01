## Marketplace source distribution

This folder packages the source plugin from release 1.16.0. It requires Python 3.11 or later, available as `python3`. It includes the tool source and no model or bundled runtime. The connected client supplies any model used in the conversation.

The separate [Windows x64 native download](https://github.com/HarperZ9/forum/releases/download/v1.16.0/forum-routing-1.16.0-win-x64.mcpb) includes its runtime. That download is a manual MCPB package and is not part of this source plugin. Directory approval and availability remain unverified.

This branch contains the installable plugin. Build commands in the release README below apply to the [product source tag](https://github.com/HarperZ9/forum/tree/v1.16.0). DISTRIBUTION.json records the published asset digest and every packaging change; any SOURCE.json describes the original release payload.

# Forum local client package

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
