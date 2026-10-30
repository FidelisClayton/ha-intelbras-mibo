# Additive EIW 1003 discovery

## Approved behavior

The user requested automatic device-list polling and explicitly directed:
“Só adicione. Nunca remova.” Every normal 30-second account refresh discovers
all supported EIW 1003 devices and unions their IDs with persisted known IDs.
There is no manual device-selection step or options filter. Initial successful
native authentication creates the account entry for all supported devices found;
at least one supported device is required for initial setup.

Each newly discovered device adds Key 1, Key 2, and Key 3 under one Home Assistant
device. Known IDs and last known names persist through reloads and restarts,
including while devices are offline. Disappearance, an unreadable device,
discovery failure, or authentication failure must never automatically delete
entity or device registry records. Missing devices remain unavailable until
normal polling can read them again. Repeated lists and returning devices reuse
the same identities.

This plan supersedes only the manual-selection and deselection-removal contracts
in earlier plans. Preserve those documents as historical context. The EIW 1003
compatibility checks, three-key mappings, account isolation, existing session
format, native login/email-code/same-account reauthentication forms, and direct
cached-command contract remain in force. No new settings, other model support,
authentication migration, or changes to other integrations are included.

## Implementation boundaries

- `coordinator.py`: share one discovery result per account refresh, merge all
  supported IDs into the known set, retain names for missing devices, and publish
  unavailable snapshots for missing or unreadable keys. Save known IDs with
  Home Assistant config-entry APIs without creating an options-reload loop.
  Retain last known names through the device and entity registries using public
  Home Assistant APIs; do not add a names field to entry options.
- `switch.py`: subscribe to coordinator updates and add three entities for each
  unseen ID once per platform load. Unregister the listener on unload. Preserve
  account/device/property-based unique IDs, including Key 1's `:11900` suffix.
- `__init__.py`: restore known IDs/names, retain registry records, and remove
  automatic deselection cleanup and options-reload behavior. Preserve runtime
  draining and normal Home Assistant setup/unload lifecycle behavior.
- `config_flow.py` and native form strings: remove device selection and filtering
  options; create entries directly from successful supported-device discovery.
  Keep login, email verification, duplicate-account prevention, and same-account
  reauthentication behavior.
- Documentation and manifest: describe this contract and identify the component
  update as `0.3.0`, without claiming a tag, release, or installation result.

Normal polling still builds validated command metadata. Cached commands retain
zero discovery/schema/state requests before the first `SetIotProperties`, one
absolute integer `0`/`1` write even for an already-matching state, and the existing
bounded `GetIotProperties` readback. Account transactions stay serialized. Missing
or invalid cached metadata fails locally; uncertain writes are not replayed.
Retaining registry records does not retain stale command metadata for disappeared
devices. Cloud readback does not establish physical relay state or total command
latency.

## Proof required

Use synthetic accounts, IDs, names, bootstrap fields, and fake cloud transport.
Workers must not make cloud calls or actuate devices.

1. Initial authentication and email verification create one account entry with
   all supported devices and no selection form; unsupported devices remain
   excluded and empty discovery retains the existing no-supported-devices path.
2. A later poll adds a supported device and exactly three entities without a
   reload. Repeated polls, renamed or reordered devices, returning devices, and
   command publications do not duplicate entities or listeners.
3. Disappearance marks all three keys unavailable while preserving known IDs,
   last known names, and device/entity registry records. Discovery or
   authentication failures do not shrink the known set or delete records.
4. Reload and offline restart restore remembered devices and names. Existing
   stored IDs and registry customizations survive upgrade without a new login.
5. Unload removes the dynamic-addition listener, stops later publications, and
   preserves the existing drain-before-replacement account lifecycle.
6. Cached-command tests continue to prove write-first ordering, exactly one
   target-only write, bounded readback, cache invalidation/recovery, failure
   isolation, no replay, and account serialization.

Run targeted `scripts/check tests/test_<area>.py` commands for changed behavior,
then the full `scripts/check`. Run hassfest and HACS validation for metadata and
native form changes, reporting remote repository prerequisites separately.
Run `git diff --check` and parse `manifest.json`. Parent verification includes
component-only fresh-instance setup/service smoke checks with fakes and native
form browser checks. Any live installation verification remains a separate,
parent-only action under the existing private authorization; this plan does not
expand physical actuation permission.
