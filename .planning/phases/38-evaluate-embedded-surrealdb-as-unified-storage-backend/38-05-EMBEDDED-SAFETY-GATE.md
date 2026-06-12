# Phase 38 Plan 05 Embedded Safety Gate

- generated_at: 2026-06-12T14:38:46.886752+00:00
- downstream_plan: 38-02
- go_no_go: PASS
- requirement: STOR-04

## Evidence Paths
- `/tmp/dotmd-phase38-embedded-gate/embedded-gate.db`
- `/tmp/dotmd-phase38-embedded-gate/embedded-gate.db.surreal-writer-guard.json`

## Embedded Probe Results
### embedded: surrealkv:///tmp/dotmd-phase38-embedded-gate/embedded-gate.db
- control_result: no
- go_no_go: PASS
- atomicity_commit_visible_after_reconnect: True
- atomicity_rollback_clean_after_failure: True
- notes:
  - Multi-session and client-side transactions are only supported for WebSocket connections
  - commit statuses: OK, OK
  - rollback statuses: ERR, ERR

### writer: surrealkv:///tmp/dotmd-phase38-embedded-gate/embedded-gate.db
- control_result: no
- go_no_go: PASS
- writer_guard_blocked_second_writer: True
- stale_owner_ttl_recovered: True
- force-release_recorded_previous_owner: True
- previous_owner_metadata: `{"acquired_at": "2026-06-12T14:38:46.885520+00:00", "hostname": "senbonzakura", "owner_id": "guard-owner-a", "pid": "221466", "target_path": "/tmp/dotmd-phase38-embedded-gate/embedded-gate.db"}`
- stale_owner_metadata: `{"acquired_at": "2026-06-12T14:38:40.885896+00:00", "hostname": "senbonzakura", "owner_id": "stale-owner", "pid": "221466", "released_at": "2026-06-12T14:38:46.886032+00:00", "released_reason": "stale_ttl", "target_path": "/tmp/dotmd-phase38-embedded-gate/embedded-gate.db"}`
- force_released_owner_metadata: `{"acquired_at": "2026-06-12T14:38:46.886235+00:00", "hostname": "senbonzakura", "owner_id": "force-owner", "pid": "221466", "released_at": "2026-06-12T14:38:46.886638+00:00", "released_reason": "force_release", "target_path": "/tmp/dotmd-phase38-embedded-gate/embedded-gate.db"}`
- notes:
  - target /tmp/dotmd-phase38-embedded-gate/embedded-gate.db is already guarded by guard-owner-a

## Decision
Embedded `surrealkv://` atomicity and writer-safety evidence passed. `38-02` may continue.
