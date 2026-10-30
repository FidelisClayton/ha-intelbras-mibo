# Development

The verification environment pins Python **3.14.9**, Home Assistant
**2026.10.4**, and `pytest-homeassistant-custom-component==0.13.375`.
`requirements-dev.txt` declares the Home Assistant and test-helper pins. Run
commands below from the repository root. Runtime installation only needs the
component directory; these dependencies are for development.

## Local environment

Use an installed Python 3.14.9 interpreter:

```sh
python3.14 -c 'import sys; assert sys.version_info[:3] == (3, 14, 9), sys.version'
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
scripts/check
```

`scripts/check` uses `.venv/bin/python` by default. It compiles the component and
tests, then runs pytest. `pyproject.toml` globally disables network sockets and
allows Unix sockets for Home Assistant's local test machinery. Tests inject
synthetic bootstrap data and fake cloud transport; they must not need an account,
a local Home Assistant configuration, or a CLI checkout.

The script forwards arguments to pytest. For example:

```sh
scripts/check tests/test_config_flow.py
scripts/check tests/test_protocol.py tests/test_coordinator.py tests/test_switch.py tests/test_init.py
```

An alternate environment can be selected with `PYTHON=/path/to/python
scripts/check`. Keep its interpreter and package versions pinned as above.

## Container environment

The official `ghcr.io/home-assistant/home-assistant:2026.10.4` image provides the
pinned Python 3.14.9 runtime. This alternative creates `.venv` with `uv` inside the
image and runs as your host user. Start in a fresh checkout without a local
`.venv`: an Alpine container virtual environment cannot be reused on a host with
a different C library or Python installation.

```sh
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env UV_CACHE_DIR=/tmp/uv-cache \
  --volume "$PWD:/work" --workdir /work \
  --entrypoint /bin/sh \
  ghcr.io/home-assistant/home-assistant:2026.10.4 -ec '
    unset UV_EXTRA_INDEX_URL PIP_EXTRA_INDEX_URL
    python3 -c "import sys; assert sys.version_info[:3] == (3, 14, 9), sys.version"
    uv venv --python /usr/local/bin/python3 .venv
    uv pip install --python .venv/bin/python -r requirements-dev.txt
    scripts/check
  '
```

The image's extra wheel index does not contain every test dependency, so the
command unsets both extra-index variables. Package installation needs internet
access; pytest blocks network access during the tests. No account or Home
Assistant configuration directory is mounted. To rerun checks in that environment:

```sh
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD:/work" --workdir /work \
  --entrypoint /bin/sh \
  ghcr.io/home-assistant/home-assistant:2026.10.4 -ec 'scripts/check'
```

## Verification boundaries

The validation workflow runs the fake-backed suite, hassfest, and the HACS
validation action as separate jobs. Action revisions are pinned in
`.github/workflows/validate.yml`. hassfest checks component metadata and
translations; HACS checks repository packaging, with remote checks depending on
the public repository being available. A successful pytest run alone does not
establish either validation result or live device behavior.

Before accepting the integration, also check that copying only
`custom_components/intelbras_mibo/` into a fresh pinned Home Assistant instance
allows native config-entry setup and switch-service control of all three keys
using fakes. Check upgrade preservation of account/session/options, the device
registry identity, and Key 1's entity ID and customizations, plus per-key schema
and read failures, target-only command failure, and later poll recovery. Verify
same-account reauthentication, unload, and reload paths. Initial native setup
must create the entry for all supported devices without a manual selection or
options-filter form. The native forms require a separate browser smoke check. Record actual results and unresolved
prerequisites; do not describe unrun checks as passing.

For documentation-only changes, review commands and installation paths against
the component and tooling, then run `git diff --check`. Do not add tests that
merely repeat documentation text.

Live validation is separate from fake-backed checks. Workers may not contact the
cloud or actuate devices. Only the parent thread may use the privately authorized
Home Assistant installation and pinned key-1 switch, through normal authentication
and supported Home Assistant APIs. Three-key software support does not expand
that actuation authorization. Do not automatically actuate keys 2/3; expanding
live actuation requires a new explicit user grant. Read-only schema and state
checks establish property support, not physical button order or relay operation.
Only Key 1 has prior physical validation; Key 2 and Key 3 still require user
physical verification after installation. Missing authorization or private setup
inputs block live verification, not offline tests. Do not edit authentication storage,
other integrations, networking, or credentials to make validation work.

The three-key support boundary is governed by
[the extension plan](plans/2026-10-30-1611-feat-three-switch-keys-plan.md).
The [direct cached-command plan](plans/2026-10-30-direct-cached-switch-commands-plan.md)
supersedes only the earlier command preflight and no-op contract. Its tests must
assert that a warmed command starts with `SetIotProperties`, sends exactly one
integer `0`/`1` target-only write even for an already-matching state, and uses only
the existing bounded readback afterward. Verify local rejection of missing or
invalid metadata, cache invalidation and recovery on normal refresh, no write
replay, and unchanged target-only failure and account-wide authentication paths.
The [additive-discovery plan](plans/2026-10-30-additive-device-discovery-plan.md)
supersedes only the earlier manual-selection and automatic registry-removal
contracts. Its fake-backed tests must cover initial discovery of all supported
devices, polling additions, persistence of known IDs and last known names,
offline restart, and recovery without registry deletion. Assert three entities
per new device, no duplicate additions after repeated or reordered lists,
renames or command publications, and listener removal on unload. Discovery and
authentication failures must retain known devices. A missing device is
unavailable, including across restarts, and must not cause automatic entity or
device registry deletion. Existing cached-command ordering, exactly one write,
bounded readback, account serialization, and failure isolation remain covered.
The initial first-key plan remains historical context. Version `0.3.0` identifies
the additive-discovery component update for installation testing, not a tag or
release. Installation and read-only verification results must be recorded
separately from fake tests;
do not claim an existing installation was upgraded until the parent verifies it.
The implementation remains on `feat/hacs-integration` with draft PR #1 open;
`main` contains the bootstrap, and HACS default-branch installation requires merge.

## Contributions and privacy

Keep runtime code self-contained under `custom_components/intelbras_mibo/` and
preserve both root and packaged `NOTICE` files. Use synthetic test identities and
application fields. Do not track passwords, verification codes, token sessions,
real device names or IDs, private paths or hosts, raw cloud payloads, or vendor
application-key literals. Review the distributable files and new history before
publication. The source URL and digest in `bootstrap.py` establish public upstream
provenance; development must not download and paste the extracted values into
fixtures or documentation.
