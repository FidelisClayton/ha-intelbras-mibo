---
title: Simplify integration - Plan
type: refactor
date: 2026-10-30
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---
# Simplify integration - Plan

## Goal Capsule

- **Objective:** Maintainers have no remaining actionable simplifications in the reviewed integration scope.
- **Means:** Remove the confirmed unnecessary flow state and redundant descriptions (KTD1–KTD2), then repeat all five simplification lenses.
- **Authority:** The authorized simplification request and pinned proof constraints govern this plan; `AGENTS.md` and its linked behavior plans remain binding.
- **Execution:** One bounded change on `refactor/simplify-integration`, based on `b794647f0d62a585deb1e306d31c6df8e20c7b8b`. The parent coordinates implementation and verification; publication is outside this plan.
- **Stop condition:** Definition of Done is met, or new evidence requires changing a protected contract.

## Product Contract

### Summary

Simplify production Python without changing integration behavior. The approved edits remove two transient attributes and ten redundant docstrings.

### Problem Frame

The flow stores method-local results as persistent instance state, and several descriptions repeat the declarations beside them. These add reading and state-tracking work for maintainers.

### Requirements

**Behavior preservation**

- R1. Preserve session/data/options shapes, errors, request ordering, validation, MFA verified-code retry, same-account reauthentication, and client/password cleanup exactly.
- R2. Preserve account thread locking, coordinator operation locking and shutdown guards, additive known-device ID/name persistence, and SET-first single-write commands with bounded readback.

**Proof and scope**

- R3. Keep every test file byte-for-byte unchanged, including helpers and comments; preserve upstream attribution, both NOTICE files, public behavioral contracts, and all four inline production comments.
- R4. Apply only the approved edits in U1–U2; judge subsequent review findings against R1–R3 before adding another bounded change to this plan.

### Scope Boundaries

Review handwritten component Python and connected tests. No API changes, extractions, new behavior, test cleanup, historical-plan edits, UI work, cloud calls, device actions, authentication changes, browser checks, deployment, commits, or publication are included. Additional safeguards are unnecessary for these private-state and description removals; evidence of changed behavior would stop the simplification.

## Planning Contract

### Key Technical Decisions

- KTD1. **Use locals for authenticated discovery results.** `MiboConfigFlow._session` and `_devices` have no consumers outside `_async_authenticated`; remove their initializations and the `_session` cleanup assignment. Keep the rebuilt `_client` assignment because subsequent authenticated-session handling and flow cleanup depend on it. This implements R1 without introducing an abstraction.
- KTD2. **Delete only descriptions that duplicate structure.** Remove seven module docstrings, the `MiboRuntime` and `AccountRuntime` descriptions, and the `AccountRunner.closed` property description. Preserve R3; protocol provenance and behavioral contracts explain obligations that declarations alone do not.

### Caller map and proof pins

`_async_credentials` and `async_step_code` call `_async_authenticated` after successful login. Its executor closure exports the session, reconstructs the client, and discovers switches. The returned session feeds reauthentication or new-entry data; discovered devices feed empty-result handling and new-entry options. Repository searches find no other readers of the two attributes. `async_remove` continues clearing `_client`, password, and verified-code state and closing the runner.

Existing `tests/test_config_flow.py` covers setup/session reconstruction, empty and failed discovery, preserved reauth terminal/options, failure cleanup, and accepted-code login retry. The remaining suite pins R2. These tests are the independent proof; no replacement or mirrored tests are needed.

### Assumptions

No inferred product scope is required. Whether post-change checks pass and whether another actionable review finding exists remain execution evidence, not planning claims.

## Implementation Units

### U2. Remove redundant descriptions

**Goal / requirements:** Remove the approved descriptions under R3–R4.
**Dependencies:** None; perform subtraction before the local-state conversion.
**Files:** `custom_components/intelbras_mibo/__init__.py`, `bootstrap.py`, `config_flow.py`, `const.py`, `coordinator.py`, `runtime.py`, and `switch.py` in that same directory.
**Approach:** Apply KTD2. Delete the seven leading module descriptions, the two named dataclass descriptions, and the `closed` property description; retain surrounding code and all other documentation.
**Test expectation:** No new tests; docstring deletion introduces no functional behavior.
**Verification:** The diff contains exactly the ten approved description deletions; compilation and the full existing suite pass.

### U1. Reduce authenticated flow state

**Goal / requirements:** Remove unnecessary retained values while preserving R1 and R3.
**Dependencies:** U2; both units touch `config_flow.py`.
**Files:** `custom_components/intelbras_mibo/config_flow.py`; verification-only `tests/test_config_flow.py`.
**Approach:** Apply KTD1 within the existing method and cleanup structure; preserve the discovery closure and every branch in its current order.
**Existing test scenarios:**

1. Successful setup saves the same session and all supported IDs and uses the reconstructed client.
2. Empty discovery and authentication/network failures return the same abort reasons.
3. Same-account reauth preserves terminal, unrelated data, and options.
4. An accepted email code followed by a connection failure retries login without another grant; success, abort, and cancellation clear secrets.

**Verification:** Existing config-flow tests pass; the two removed attributes have no remaining references, and tests have no diff.

## Verification Contract

- Baseline supplied by the parent: `scripts/check` passed **198 tests and 10 subtests in 17.37s** using the pinned Home Assistant 2026.10.4 container. This is pre-change evidence.
- Follow `docs/development.md`: run `scripts/check tests/test_config_flow.py`, then the complete `scripts/check` after the combined change, keeping the network guard and pinned Python 3.14.9/test-helper environment.
- Run the pinned hassfest and HACS validations in `.github/workflows/validate.yml` because config-flow code changes. Report remote HACS prerequisites separately from component failures.
- Check whitespace with `git diff --check` and verify all test files and historical plans remain byte-identical to the baseline. Retain required notices, protocol attribution, public behavioral docstrings, and four inline comments.
- Run a fresh five-lens simplification review: reuse, quality, efficiency, test value, and comments. Apply only worthwhile findings consistent with R1–R4 and repeat until all five report zero actionable findings.
- Report actual results and skipped/blocked checks. The authorized offline scope does not establish browser, live-cloud, installed-instance, or deployment validation.

## Definition of Done

U1–U2 satisfy their verification, required checks pass or their external prerequisites are explicitly reported, and a fresh complete five-lens review finds zero actionable simplifications. Every test remains unchanged, R1–R3 remain intact, and no abandoned or experimental code remains in the diff. A blocked required check must remain visible in the handoff and cannot be described as passing.
