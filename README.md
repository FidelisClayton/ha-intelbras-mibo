# Intelbras Mibo for Home Assistant

Unofficial community integration for cloud control of the **three individual
keys on the Intelbras Mibo EIW 1003**. Each discovered device exposes three native
Home Assistant switches: **Key 1**, **Key 2**, and **Key 3**, under the same device.
Cameras, master control, other models, and local-LAN control are outside its scope.

The compatibility target is Home Assistant **2026.10.4** on Python **3.14.9**.
Other versions are not verified. The integration runs entirely from
`custom_components/intelbras_mibo/`; it needs no CLI, separate Python package,
subprocess, or extra service.

## Installation availability

The integration is available on `main` in the public repository
[`FidelisClayton/ha-intelbras-mibo`](https://github.com/FidelisClayton/ha-intelbras-mibo).
Install it by manual copy or as a HACS custom repository. There is no tagged
release or HACS default-catalog listing. Component version **0.3.1** identifies
this component update; it is not a tagged release.

### Manual copy

1. Obtain a checkout or archive of the repository’s `main` branch.
2. Copy the entire `custom_components/intelbras_mibo` directory, including its
   `NOTICE`, into `<config>/custom_components/`. The resulting path must be
   `<config>/custom_components/intelbras_mibo/manifest.json`, with the Python and
   translation files alongside it.
3. Restart Home Assistant, then follow the setup steps below.

Only the component directory is needed at runtime. Do not copy development tests
or a virtual environment into Home Assistant.

### HACS custom repository

1. In HACS, open **Custom repositories** from its menu.
2. Add `https://github.com/FidelisClayton/ha-intelbras-mibo` with category
   **Integration**.
3. Download **Intelbras Mibo** through HACS and restart Home Assistant.
4. Configure the integration below. HACS downloads the files; account setup
   happens in Home Assistant.

## Account setup

1. Open **Settings → Devices & services → Add integration → Intelbras Mibo**.
2. Enter your Mibo account email and password in the native form.
3. If the cloud requests email verification, enter the code sent to your email.
   Only the specific cloud challenge `12112` opens this step. Retrying a code
   does not send another email. If terminal trust was accepted but the following
   login could not connect, retrying resumes login without granting the code again.
4. Setup discovers all supported EIW 1003 devices in the account automatically.
   At least one supported device is required for initial setup. Cameras and
   unsupported identities are omitted.

Each discovered device gets **Key 1**, **Key 2**, and **Key 3** entities, usable with
normal Home Assistant switch actions. One integration entry is allowed per account.
A key with an unvalidated schema or unreadable property remains unavailable;
healthy sibling keys can still update and work. Later polling can recover the
key without reconfiguration.

When upgrading an existing entry, replace the component and restart Home
Assistant. The existing account session, known device IDs, device identity, and
Key 1 entity ID and customizations are preserved; no new setup or password entry
is needed for the upgrade. Key 2 and Key 3 are added under the existing device.

Every **30 seconds**, discovery adds newly found supported devices and their
three key entities automatically. Known device IDs and last known names are
retained across restarts, including while a device is offline. A disappeared or
unreadable device becomes unavailable; it is never removed automatically from
Home Assistant's device or entity registry. Cloud failures also retain known
devices. Repeated discovery does not create duplicate entities. There is no
manual device selector or options filter. Device renames and list reordering
preserve entity identity.

When Home Assistant requests reauthentication, sign in through its repair/setup
prompt using the same account. Email verification may be requested again. A
successful sign-in updates the existing entry and keeps known devices and
entity identities. Passwords and email verification codes are not persisted.

## Cloud state and privacy

The integration polls the cloud every **30 seconds**. Account transactions are
serialized. An absolute on/off command uses the device identity and validated
target-key metadata cached by normal polling. With a valid cache, its first cloud
request writes integer `0` or `1` to that key, even when the last confirmed state
already matches. It makes no discovery, schema, or state requests before that
write. Missing or invalid cached metadata fails locally until polling restores
it. Each accepted command sends exactly one write; state is updated only after
bounded cloud readback confirms it. A timeout or unconfirmed write reports an error
and makes the affected entity unavailable; later polling can recover it without
replaying the write. Cloud readback does not independently confirm the physical
relay or connected load. The 30-second poll and account serialization are
unchanged, so a command can still wait for a running refresh. This change does
not establish total command latency.

The key mapping is `switch` / `11900` for Key 1, `std_switch2` / `127000` for
Key 2, and `std_switch3` / `127100` for Key 3. Read-only cloud checks confirmed
these boolean read/write properties and readable states. This establishes schema
support, not physical button order. User-observed control of all three property
keys was verified on an existing installation, with the original states restored.
This does not establish physical button order or compatibility with other models.

Internet access to the Mibo cloud is required. Cold setup also downloads a pinned
upstream Swift source file, verifies its SHA-256 digest, and extracts six static
application fields. It never executes the downloaded source. Home Assistant
privately caches those fields and their provenance; a valid cache avoids that
source download on later starts. A source mismatch fails setup rather than
accepting changed constants.

Home Assistant stores the account email, token session, terminal identifier,
account namespace, known device IDs, and last known names using its normal
config-entry and storage APIs. Treat configuration backups as sensitive. No manual `.storage`
changes or session-file imports are needed.

## Troubleshooting

- **Integration missing:** check the exact component path above, ensure you copied
  the full component directory, then restart Home Assistant.
- **Unable to connect:** transport failures, HTTP 5xx responses, and malformed
  provider responses during login or email verification report a connection
  error. Retry later. On cold setup,
  upstream source access is also required. Do not bypass a source digest failure.
- **Unable to sign in / invalid code:** check your credentials or code in the
  native form. Other login errors do not automatically trigger email verification.
- **No supported devices:** confirm that this account owns an EIW 1003. Similar
  names or other product models do not establish compatibility.
- **Unavailable switch / command error:** check cloud and device connectivity.
  Allow a later poll to establish state before deciding whether another command
  is needed; the previous command may have reached the device.
- **Session rejected:** complete Home Assistant's same-account reauthentication
  prompt rather than editing stored credentials.

When reporting a problem, include the Home Assistant version, the step that
failed, and sanitized error text. Remove emails, tokens, codes, device IDs and
names, application credentials, and private addresses or paths. Never attach
configuration-entry or storage files, raw cloud responses, or authentication
headers.

See [development](docs/development.md) for offline checks and
[protocol](docs/protocol.md) for the transport, bootstrap, and control contract.
Licensed under the [MIT License](LICENSE). Upstream attribution is preserved in
[NOTICE](NOTICE) and the [distributed NOTICE](custom_components/intelbras_mibo/NOTICE).
