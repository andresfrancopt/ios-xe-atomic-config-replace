# IOS-XE Atomic Config Replace (ACR)

> Safely replace the full running configuration of a Cisco IOS-XE device over NETCONF — with pre/post diffs, operator approval gates, and automatic rollback protection.

Originally authored by **Balaji Senthamil Selvan** (Cisco Systems) and extended by **Jeremy Cohoe**, and later on by **Andrés Franco**

---

## What This Does

This tool performs a **full atomic configuration replacement** on a Cisco IOS-XE device using the `Cisco-IOS-XE-cli-rpc` YANG model over NETCONF. It is designed for controlled Day-2 operations where you need to replace an entire device config while keeping a safety net in case something goes wrong.

Key features:
- 🔍 Pre and post `show run` snapshots with diffs
- ✋ Two operator approval prompts — nothing commits without explicit `yes`
- 🔄 Confirmed commit with 120s auto-rollback if final commit is not confirmed
- 📁 All snapshots written to timestamped files for audit

---

## How It Works

### 1. Connect
Establishes a NETCONF session (port 830) using `ncclient`, with automatic retry (up to 5 attempts, 30s apart) to handle devices still initialising their datastore. Writes all advertised NETCONF capabilities to `netconf_capabilities.txt`.

### 2. Pre-Check
- Discards any pending candidate datastore changes
- Retrieves running and candidate datastore configs via NETCONF RPC
- Captures `show running-config` over SSH
- Saves all three to timestamped files and prints a diff between running and candidate

### 3. Apply Target Configuration
- Loads `target_config.xml` into the **candidate** datastore via NETCONF RPC
- Automatically retries if the device returns `"Sync is in progress"`
- **Aborts immediately** if the RPC returns any other error

### 4. Post-Check
- Captures running and candidate configs again
- Prints a diff against the pre-check baseline

### 5. Operator Approval — Step 1 of 2
```
STEP 1 OF 2 — CONFIRMED COMMIT
Start confirmed commit? [yes/no]:
```
- `yes` → proceeds to confirmed commit (120s timer starts)
- `no` → calls `discard_changes()` and exits — device untouched

### 6. Confirmed Commit
Issues a confirmed commit. The new config becomes **active but not permanent**. The 120s rollback timer starts.

### 7. Operator Approval — Step 2 of 2
```
STEP 2 OF 2 — FINAL COMMIT (PERMANENT)
Make configuration permanent? [yes/no]:
```
- `yes` → `commit()` — config becomes **permanent** ✅
- `no` → exit without committing — device **auto-rolls back** when timer expires 🔄

### 8. Final Commit
Calls `commit()`, then captures a final `show run` and prints the diff against baseline.

---

## Commit vs Confirmed Commit

### NETCONF Datastores

IOS-XE NETCONF operates with two configuration datastores:

| Datastore | Description |
|-----------|-------------|
| **candidate** | Staging area — changes are prepared here but not yet active |
| **running** | The live config the device is currently using |

When the script loads `target_config.xml`, it writes the new config into the **candidate** datastore only. The device continues running on the old config until a commit operation copies candidate → running.

### `commit()` — Permanent, Immediate

Copies candidate to running instantly. No safety window.

```
candidate ──commit()──► running  (permanent, immediate)
```

### `confirmed_commit()` — Two-Phase Safety Commit

1. Candidate is copied to running — device is now using the new config
2. A 120-second countdown begins — the change is **active but not permanent**
3. If `commit()` is called within 120s → **permanent** ✅
4. If `commit()` is never called → device **automatically restores** the previous config 🔄

```
candidate ──confirmed_commit()──► running  (active, timer running)
                                      │
                        ┌─────────────┴─────────────┐
                    commit()                    timer expires
                   (permanent ✅)              (auto-rollback 🔄)
```

**Why this matters:** if the new config breaks SSH or NETCONF access (e.g. wrong ACL, incorrect management IP), you physically can't call `commit()` — the timer expires and the device rolls back automatically.

---

## YANG-Modelled CLI vs `show running-config`

This script uses **YANG-modelled CLI text** retrieved via NETCONF, not raw `show run` output. Here's why that matters:

| | YANG-modelled CLI | Raw `show run` |
|---|---|---|
| Normalised ordering | ✅ Consistent, model-driven | ❌ Can vary between reboots |
| No ephemeral/default values | ✅ Only explicitly set config | ❌ Includes platform defaults |
| Safe to replay | ✅ Filtered by the YANG model | ❌ Some lines are display-only and fail on replay |
| Reliable diffs | ✅ Structural comparison | ❌ Whitespace/ordering noise |

Raw `show run` can contain lines that **cannot be pushed back** to the device — certificates, platform-specific display lines, hardware-dependent features. The YANG model filters all of that out automatically.

---

## Requirements

| Package | Purpose |
|---------|---------|
| `ncclient` | NETCONF session and RPC operations |
| `netmiko` | SSH connection for CLI commands |
| `lxml` | XML parsing and XPath queries |
| `xmltodict` | Convert NETCONF XML responses to Python dicts |
| `python-dotenv` | Load credentials from `.env` file |

Install with:
```bash
pip install -r requirements.txt
```

---

## Prerequisites

- Cisco IOS-XE device running **17.3+** (tested on 17.15.4)
- NETCONF enabled on the device:
  ```
  conf t
    netconf-yang
    netconf-yang feature candidate-datastore
  end
  ```
- Device reachable on **port 830** (NETCONF) and **port 22** (SSH)
- User account with privilege 15

Verify NETCONF is ready:
```
show netconf-yang status
```

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/andresfrancopt/ios-xe-atomic-config-replace.git
cd ios-xe-atomic-config-replace
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.sample .env
```

Edit `.env`:
```
DEVICE_HOST=<device_ip_here>
DEVICE_USERNAME=<username_here>
DEVICE_PASSWORD=<password_here>
```

### 3. Generate the target config from golden device

Use `get_target_config.py` to pull the current running config from golden device already running similar or same tested configuration as a ready-to-use ACR payload:

```bash
python get_target_config.py
```

This creates `candidate_target_config.xml` — the golden device's own running config expressed in YANG-modelled CLI text, already wrapped in the correct XML structure.

### 4. Edit the target config

```bash
cp candidate_target_config.xml target_config.xml
```

Edit `target_config.xml` to reflect the desired state you want to apply.

> ⚠️ Ensure all values are valid XML — do not use bare `<` or `>` characters in values. Replace any placeholder strings before running.

### 5. Run the ACR script

```bash
python atomic_replace_config_v1.3.py
```

---

## Understanding `target_config.xml`

```xml
<config-ios-cli-trans xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-cli-rpc">
  <clis>
    ... full CLI configuration ...
  </clis>
  <operation>full-replace</operation>
  <do-commit>false</do-commit>
</config-ios-cli-trans>
```

| Tag | Purpose |
|-----|---------|
| `config-ios-cli-trans` | Root RPC element from the `Cisco-IOS-XE-cli-rpc` YANG module. The `xmlns` tells NETCONF which module handles this request — without it the device returns `unknown-namespace` |
| `clis` | Container for the raw CLI config text — the device parses this exactly as if typed at the CLI |
| `operation>full-replace` | Replaces the **entire** running config atomically. Without this it defaults to a merge, leaving existing config lines untouched |
| `do-commit>false` | Loads into the candidate datastore only — does **not** auto-commit. This enables the two-phase confirmed commit workflow |

---

## Key Files

| File | Description |
|------|-------------|
| `atomic_replace_config_v1.3.py` | Main ACR script |
| `get_target_config.py` | Helper to generate `candidate_target_config.xml` from the device |
| `target_config.xml` | The desired state config to apply — edit before running ACR |
| `candidate_target_config.xml` | Auto-generated from the device — use as starting point for `target_config.xml` |
| `.env` | Device credentials — never commit this file |
| `.env.sample` | Template for `.env` |
| `base_config.xml` | Auto-generated snapshot of current candidate datastore config |
| `netconf_capabilities.txt` | Auto-generated list of all NETCONF capabilities advertised by the device |
| `pre_shrun_<ts>.txt` | Pre-change `show run` snapshot |
| `post_shrun_<ts>.txt` | Post-change `show run` snapshot |
| `config_diff.html` | HTML diff of pre vs. post confirmed-commit |

---

## NETCONF Capability Notes

Confirmed on **Cisco IOS-XE 17.15.4**:

| Capability | Status |
|-----------|--------|
| `:candidate` | ✅ `urn:ietf:params:netconf:capability:candidate:1.0` |
| `:confirmed-commit` | ✅ `urn:ietf:params:netconf:capability:confirmed-commit:1.0` and `1.1` |
| `Cisco-IOS-XE-cli-rpc` | ⚠️ Not advertised in capabilities, but RPC works — known quirk on some IOS-XE versions |

The script writes the full capability list to `netconf_capabilities.txt` on each run.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `Unexpected session close` | NETCONF daemon still syncing at connect time | Script auto-retries; wait for `%DMI-5-SYNC_COMPLETE` on device console |
| `MissingCapabilityError: :candidate` | Candidate datastore not enabled | `conf t` → `netconf-yang feature candidate-datastore` |
| `XMLSyntaxError` on `target_config.xml` | Invalid XML characters (e.g. `<placeholder>`) in the file | Replace all placeholder values with real config before running |
| `unknown-namespace` on `get-modelled-config-clis` | `Cisco-IOS-XE-cli-rpc` module not loaded | Verify with `show netconf-yang capabilities \| include cli-rpc` |
| `syntax error: element does not exist` | `target_config.xml` contains a command not supported on this device | Use `get_target_config.py` to generate config from the target device itself |
| Missing credentials | `.env` file not found or incomplete | Copy `.env.sample` to `.env` and fill in all three values |
