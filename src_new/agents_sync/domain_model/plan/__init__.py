"""The sync brain — pure functions deciding what should change (no I/O).

Each module here is one cohesive step of ``compute_sync_plan`` (proposal §7):
identity recovery, per-known reconciliation, candidate adoption, and the whole-plan
assembly. Nothing in this package touches the filesystem, the clock, or randomness.
"""
