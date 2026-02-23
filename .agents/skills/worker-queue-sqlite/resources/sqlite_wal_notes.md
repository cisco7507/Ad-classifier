Enable:
- PRAGMA journal_mode=WAL;
- PRAGMA busy_timeout=5000;

Rationale: reduces "database is locked" with concurrent workers.
