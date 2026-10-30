# Intelbras Mibo for Home Assistant

Unofficial community integration for cloud control of **key 1 on the Intelbras
Mibo EIW 1003**. Each selected device exposes one native Home Assistant switch.
Cameras, keys 2 and 3, master control, and local-LAN control are outside its scope.

The compatibility target is Home Assistant **2026.10.4** on Python **3.14.9**.
Other versions are not verified. The integration runs entirely from
`custom_components/intelbras_mibo/`; it needs no CLI, separate Python package,
subprocess, or extra service.

## Installation availability

The implementation is currently on `feat/hacs-integration`. The planned public
repository is `FidelisClayton/ha-intelbras-mibo`; publication is pending. The
bootstrap on `main` does not contain the integration. Until the implementation is
merged, use the component directory from the feature branch for manual testing.
There is no release or HACS catalog listing.

### Manual copy

1. Obtain a checkout or archive of the implementation branch. After merge, the
   default branch can be used instead.
2. Copy the entire `custom_components/intelbras_mibo` directory, including its
   `NOTICE`, into `<config>/custom_components/`. The resulting path must be
   `<config>/custom_components/intelbras_mibo/manifest.json`, with the Python and
   translation files alongside it.
3. Restart Home Assistant, then follow the setup steps below.

Only the component directory is needed at runtime. Do not copy development tests
or a virtual environment into Home Assistant.

### HACS custom repository, after merge

These steps become usable after the public repository exists and the
implementation is merged into its default branch:

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
   does not send another email.
4. Select at least one supported EIW 1003. The selector includes device IDs to
   distinguish switches with the same name. Cameras and unsupported identities
   are omitted.

Each selected device gets a **Key 1** entity, usable with normal Home Assistant
switch actions. One integration entry is allowed per account.

To change selected devices, open the entry's **Configure** options. At least one
selection is required. Missing devices remain selected and unavailable until you
explicitly remove them; a discovery error keeps the previous selection. Saving
options reloads the entry and removes deselected entities. Device renames and
list reordering preserve entity identity.

When Home Assistant requests reauthentication, sign in through its repair/setup
prompt using the same account. Email verification may be requested again. A
successful sign-in updates the existing entry and keeps selected devices and
entity identities. Passwords and email verification codes are not persisted.

## Cloud state and privacy

The integration polls the cloud every **30 seconds**. A command validates the
device and property schema, reads the current state, and sends at most one write.
If the desired state is already present, it sends no write. State is updated only
after a cloud read confirms it. A timeout or unconfirmed write reports an error
and makes the affected entity unavailable; later polling can recover it without
replaying the write. Cloud readback does not independently confirm the physical
relay or connected load.

Internet access to the Mibo cloud is required. Cold setup also downloads a pinned
upstream Swift source file, verifies its SHA-256 digest, and extracts six static
application fields. It never executes the downloaded source. Home Assistant
privately caches those fields and their provenance; a valid cache avoids that
source download on later starts. A source mismatch fails setup rather than
accepting changed constants.

Home Assistant stores the account email, token session, terminal identifier,
account namespace, and selected device IDs using its normal config-entry and
storage APIs. Treat configuration backups as sensitive. No manual `.storage`
changes or session-file imports are needed.

## Troubleshooting

- **Integration missing:** check the exact component path above, ensure you copied
  the implementation branch, then restart Home Assistant.
- **Unable to connect:** check internet access and retry later. On cold setup,
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
