"""agents_sync — thin clean rebuild (parallel build tree).

This package is the greenfield rebuild described in
``docs/architecture_simplification_proposal.md`` and built step by step per
``docs/architecture_implementation_plan.md``. It lives under ``src_new/`` while
the existing ``src/agents_sync/`` keeps running; at cutover the directory is
renamed ``src_new/agents_sync`` → ``src/agents_sync`` (the package name never
changes, so no import is rewritten).
"""
