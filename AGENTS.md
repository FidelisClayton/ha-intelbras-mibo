# Scope

This is a standalone, shareable Home Assistant custom integration. Support is
cloud control of the Intelbras Mibo EIW 1003 first key, property 11900. Keep runtime
files under `custom_components/intelbras_mibo/`, independent of any CLI, private
configuration, subprocess, separate service, or published Python package. Do not
expand support to cameras, other keys, master control, or local-LAN protocols.

# Public repository

Never include account secrets, vendor application-key literals, private hostnames,
device IDs, or device nicknames in tracked files, fixtures, logs, or documentation.
Use synthetic data in tests and portable paths in examples. Preserve the MIT
license and both root and packaged upstream NOTICE files when adapting code.
Review distributable content and new history before publication. The integration
on the feature branch is manually copyable; HACS default-branch installation is
available only after publication and merge. Do not claim a release, catalog
listing, or successful validation without evidence.

# Home Assistant

Target Home Assistant 2026.10.4 on Python 3.14.9 with
pytest-homeassistant-custom-component 0.13.375. Use Home Assistant config entries,
storage helpers, executor, and lifecycle APIs; never manually edit `.storage`
files for authentication. Passwords and email codes must not be persisted. Treat
saved sessions, device selections, and bootstrap constants as private data.

# Checks

Follow the approved plan and `docs/development.md` for the pinned environment.
For Python behavior changes, add or update the behavior test and run
`scripts/check tests/test_<area>.py` for the affected areas. Before integrating
the full change, run `scripts/check`, which compiles component/tests and runs
pytest with network sockets disabled and Unix sockets allowed. Tests use fakes,
without real accounts, sessions, cloud calls, or device actions. Do not remove
the network guard to make tests pass.

For metadata, config-flow, translation, or packaging changes, also run the
hassfest and HACS jobs defined in `.github/workflows/validate.yml`. Report remote
repository prerequisites separately from component failures. Whole-integration
verification includes a component-only fresh-instance setup/service smoke check
with fakes and a native-form browser smoke check. Do not substitute CLI evidence
for Home Assistant lifecycle or live verification.

For documentation-only changes, review commands and paths against the actual
implementation and run `git diff --check`; no prose-mirroring tests are required.
Always record the checks actually run and any skipped or blocked verification.

# Live access

Workers must not make cloud calls or actuate devices. Only the parent thread may
perform live validation, limited to key 1 of the uniquely pinned switch on the
existing Home Assistant host, as identified privately in the parent thread.
Read-only device discovery is allowed to select that switch. Do not actuate
other devices during live verification; normal user-configured discovery is part
of the integration contract. Keep existing authentication, other integrations,
credentials, and networking intact. Missing private inputs block live validation,
not isolated fake-backed work.
