# Ponytail review fixes

## Goal

Resolve the three actionable review findings and correct public installation
documentation after PR #1 merged into `main`. Repeat fresh Ponytail review after
the fixes until it reports zero actionable findings. This plan records the
required behavior and verification, not completed test results.

## Changes

1. Preserve coordinator transaction order through state publication. A refresh
   started before a command must not publish its older snapshot after that
   command publishes confirmed readback. Add a coordinator async lock covering
   refresh and command work through publication, retaining the existing account
   runner's executor and account lock.
2. Treat initial-login transport failures, HTTP 5xx responses, and malformed
   provider responses as `cannot_connect`, including reauthentication. Malformed
   responses include `invalid_response`, `invalid_data`, `api_invalid_code`, and
   `invalid_login_response`. Only numeric `api_*` provider rejections, HTTP
   401/403, `login_required`, and `login_failure_no_retry` map to `invalid_auth`
   during login. Keep the specific `12112` email challenge unchanged.
3. Separate email-code grant and subsequent login errors. Transport failures,
   HTTP 5xx responses, and malformed provider responses report `cannot_connect`;
   rejected codes report `invalid_code`. After a grant
   succeeds, remember acceptance only in flow memory so a login connection retry
   does not repeat `GrantingCredit`. A credential rejection after grant returns
   to the credentials form. Clear flow-local acceptance on new credentials and
   flow removal, without persisting passwords or codes.
4. Update README, development guidance, and repository instructions to describe
   installation from public `main`, by manual copy or HACS custom repository.
   Do not claim a tagged release or HACS default-catalog listing. Set the
   component version to `0.3.1`. Preserve historical plans. Record user-observed
   control of all three property keys on an existing installation, with original
   states restored, without claiming physical button order, other-model
   coverage, or command latency.

## Preserved contracts

- EIW 1003 only: Key 1 `switch` / `11900`, Key 2 `std_switch2` / `127000`,
  and Key 3 `std_switch3` / `127100` retain their identities and isolated failures.
- Discovery only adds supported IDs to persisted known IDs. Offline devices and
  last known names remain present across restarts. Never remove registry records
  automatically; do not introduce a selector or options filter.
- A warmed command makes zero discovery, schema, or state requests before
  `SetIotProperties`. It sends exactly one absolute target-only integer write,
  even when cached state already matches, followed by existing bounded readback.
  No automatic write replay, optimistic state, or new cache TTL.
- Keep account locking, cancellation draining, unload cleanup, same-account
  reauthentication, session format, and authentication privacy. Workers use
  synthetic data and make no cloud calls or device actions.
- Do not add speculative frameworks, concurrency optimizations, model support,
  new authentication mechanisms, or unrelated cleanup.

## Verification

Reproduce each changed behavior with a deterministic failing test before its
runtime fix. Coordinator tests must cover refresh publication racing a command,
success and failure state isolation, and unload/cancellation behavior. Config-flow
tests must cover initial and reauthentication login HTTP 5xx/transport failures
and malformed provider responses, code-grant and post-grant login connection
and malformed-response failures, rejected codes and
credentials, and accepted-grant retries without another grant or email.

Run affected tests with
`scripts/check tests/test_coordinator.py tests/test_switch.py` and
`scripts/check tests/test_config_flow.py`, then the complete `scripts/check` suite
with its network guard intact. For documentation, compare commands, paths, and
contracts with the implementation and run `git diff --check`; no prose-mirroring
tests are needed. Parse the manifest JSON. Run the pinned hassfest and HACS
validation jobs from `.github/workflows/validate.yml`, reporting remote repository
prerequisites separately. Do not use Dagger.

The parent performs whole-change verification, component-only fresh-instance
setup/service smoke checks with fakes, and the native-form browser smoke check.
Record only actual results and identify skipped or blocked checks. Any live
verification remains limited to the user's explicit private authorization; do
not put owner identities, device IDs, device names, or private paths in public
artifacts. A fresh Ponytail review must assess the final diff; fix any actionable
findings and repeat until none remain.
