# Privacy

Forum's plugin runs on your computer. The publisher operates no backend, account or
inference service for it, and the plugin collects no telemetry or usage statistics.

**What it reads.** The request text and optional context fields that the connected
model passes to a tool call. It reads no files from your computer beyond its own
package.

**What it stores.** Nothing on disk. The packaged server keeps a ledger in memory for
the life of the process. Stopping the client or the server discards it.

**What it sends.** Nothing. The packaged tools open no network connection and start
no other program. Submit, execution and gate decisions are absent from this package.

**Retention.** None after the process ends.

**Third parties.** The connected client and its model see tool arguments and results
under that client's terms. Your model provider's privacy policy applies to what the
model reads.

**Support and security reports.** https://github.com/HarperZ9/forum/issues
