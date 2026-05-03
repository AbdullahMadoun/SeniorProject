# SkyLink System Baseline

This document is the software-side source of truth for the SkyLink flight, docking, and simulation stack.

It freezes the values extracted from [info.txt](/D:/downloads/SeniorProject/info.txt) and the later hardware decisions already made in this project. If another document conflicts with this file, this file wins unless it is explicitly revised.

## Source Priority

The baseline is resolved in this order:

1. Corrected values in the latest report text and reviewer replies inside `info.txt`
2. User-confirmed procured hardware and integration decisions made in this repo
3. Older appendix values only if they do not conflict with items 1 and 2

## Frozen System Definition

### Flight and Mission

| Item | Frozen value | Why it is binding |
| --- | --- | --- |
| Real autopilot target | `PX4` on `Pixhawk` | The project and hardware path are explicitly PX4-based |
| Mission radius | `100 m` | Repeated in the abstract and project constraints |
| Cruise speed band | `3-7 m/s` | Repeated in the abstract and AE requirements |
| Endurance requirement | `>= 20 min` | Reviewer-corrected requirement |
| Validated endurance used in planning | `21 min` | Repeated in the abstract and final analysis replies |
| RTL trigger | `20% battery` | Repeated in the abstract and project description |
| Wind operating limit | `<= 7 m/s` | Repeated in the abstract, AE text, and supplied materials |
| Max altitude in software safety layer | `100 m` | Matches earlier phase scope and remains compatible with the report |
| Processing latency target | `< 5 min` | Repeated in the abstract |
| Geo-tagging error bound | `<= 20 m` | Repeated in the abstract |

### Docking and Landing

| Item | Frozen value | Why it is binding |
| --- | --- | --- |
| Charging power | `50 W` | Reviewer reply explicitly replaced the older `15 W` value |
| Landing accuracy target | `<= 0.4 m` | Reviewer reply explicitly relaxed the earlier `0.3 m` claim |
| Dock landing platform diameter | `0.4-0.6 m` | Still consistent with the supplied materials table |
| Precision landing strategy | `camera marker + rangefinder` | IR path was removed; camera-assisted landing is the viable software baseline |
| RTL landing behavior | `return to dock area, then precision land if target lock exists` | Required to prove autonomous recovery and docking |

### Sensors and Hardware Assumptions

| Item | Frozen value | Why it is binding |
| --- | --- | --- |
| GPS module for software integration | `M9N` | User explicitly named this as the integrated part |
| Rangefinder path | `TFmini-S` primary, `MTF-01P` secondary | User explicitly named these sensors |
| IR precision landing | `not used` | Reviewer reply says IR sensing was removed |
| Ground control station | `QGroundControl` | Required for PX4 configuration and safety validation |
| Mission/control API | `MAVSDK-Python` | Correct path for PX4-facing automation |

### Vision and Processing

| Item | Frozen value | Why it is binding |
| --- | --- | --- |
| Minimum supported capture resolution | `1080p` | The abstract and processing story already depend on this |
| Preferred physical camera target | `4K` | The report later claims a visual 4K path; keep it as preferred, not required |
| Detection accuracy floor | `>= 75%` | Reviewer-corrected target |
| Dashboard/reporting model | post-mission or buffered upload | Matches the report's cloud-processing workflow |

## Resolved Contradictions

| Topic | Rejected value | Frozen value | Reason |
| --- | --- | --- | --- |
| Charging power | `15 W` | `50 W` | The report reply explicitly corrected this |
| Landing accuracy | `<= 0.3 m` | `<= 0.4 m` | The report reply explicitly corrected this for GPS-limited docking |
| Precision landing sensor path | `IR-based landing` | `camera marker + rangefinder` | IR was later removed from the system definition |
| Wind limit in old autonomy config | `3 m/s` | `7 m/s` max operating limit | `3 m/s` is still useful as a nominal validation case, but not the system limit |
| GPS module from generic references | `M10` | `M9N` | User-provided physical part takes precedence |

## Implementation Consequences

The autonomy stack must prove these behaviors in simulation before real flight:

1. Upload and execute a waypoint mission within a `100 m` operational envelope.
2. Hold speed logic inside the `3-7 m/s` band.
3. Monitor battery and trigger RTL at `20%`.
4. Reject or abort missions when simulated wind exceeds `7 m/s`.
5. Return to the dock area and complete a vision-assisted precision landing.
6. Produce a replay package showing mission path, telemetry, safety state, landing sequence, and captured imagery/results.

## What Is Not Frozen Yet

These items still need later team sign-off and are not treated as binding software requirements yet:

- Exact drone frame, motors, ESC, and propeller combination
- Final camera module part number
- Exact cloud provider and deployment topology
- Whether the final landing marker is ArUco, AprilTag, or a custom visual target

## Repo Contract

`autonomy/config/system.toml` must mirror the values in this document for any field that appears in both places.

`autonomy/tests/test_baseline_config.py` is the guardrail for the most critical values. If the baseline changes, the spec and the test must change in the same commit.
