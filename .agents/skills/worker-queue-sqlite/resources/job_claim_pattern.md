# Claim pattern (conceptual)

1) BEGIN IMMEDIATE;
2) SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1;
3) UPDATE jobs SET status='processing', started_at=NOW() WHERE id=? AND status='queued';
4) COMMIT;

If update affected 0 rows, someone else claimed it.
