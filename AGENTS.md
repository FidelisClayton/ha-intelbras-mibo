# Scope

This is a standalone, shareable Home Assistant custom integration. Initial scope
is cloud control of the Intelbras Mibo EIW 1003 first key. Keep it independent of
the CLI. Implementation and verification commands must follow the approved plan;
the bootstrap does not establish a working integration or baseline CI checks.

# Public repository

Never include account secrets, vendor application-key literals, private hostnames,
device IDs, or device nicknames in tracked files, fixtures, logs, or documentation.
Use synthetic data in tests. Preserve the MIT license and upstream NOTICE when
adapting upstream code.

# Home Assistant

Target the official pinned Home Assistant 2026.10.4 release. Use Home Assistant
APIs, config entries, and storage helpers; never manually edit `.storage` files
for authentication. Automated tests must use fakes, without real sessions.

# Live access

Workers must not make cloud calls or actuate devices. Only the parent thread may
perform live validation, limited to key 1 of the uniquely pinned switch on the
existing Home Assistant host, as identified privately in the parent thread.
Do not discover or operate other devices.
