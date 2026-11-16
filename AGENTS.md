# Project instructions

- This is a relay to existing Codex installations. Do not standardize, upgrade, or restart remote Codex versions as an incidental prerequisite.
- Never commit credentials, local inbox/outbox databases, SSH configuration, or full conversation exports.
- Report RPC connectivity, persisted login state, successful model execution, and Feishu round trips separately.
- Never automatically replay an uncertain task dispatch.
- Only the paired owner's direct messages or authenticated owner workbench requests may cause task dispatch or answer approvals.
- Preserve remote execution policy. Root-directory validation for file transfer is not a Codex sandbox.
- Test protocol transport, ownership, deduplication, recovery, and dispatch behavior when changing these components.
