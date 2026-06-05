"""Pure domain model — entities and the sync decision, with no I/O.

Nothing in this package may import a gateway, the filesystem, the clock, or a
tool adapter. It is unit-tested entirely in memory (see the proposal §5).
"""
