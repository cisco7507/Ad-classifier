# Feature: Job Selection & Bulk Delete

## Overview

Add the ability for operators to select individual jobs (or all jobs) in the Job Queue table and delete them. This requires:

1. **Backend**: A new bulk-delete endpoint `DELETE /jobs/bulk`
2. **Frontend API client**: A new `deleteJobsBulk` function
3. **Frontend UI**: Checkboxes on each row, a "Select All" checkbox, and a delete action bar

---

## Part 1: Backend — Bulk Delete Endpoint

### File: `video_service/app/main.py`

Add a new endpoint **after** the existing `delete_job` endpoint (after line 585):

```python
from pydantic import BaseModel

class BulkDeleteRequest(BaseModel):
    job_ids: list[str]
```

Note: `BaseModel` import likely already exists via the models module. Alternatively, put the model in `video_service/app/models/job.py`.

```python
@app.post("/jobs/bulk-delete", tags=["jobs"])
async def bulk_delete_jobs(req: Request, body: BulkDeleteRequest):
    """Delete multiple jobs by ID. Skips IDs that don't exist."""
    if not body.job_ids:
        raise HTTPException(400, "No job IDs provided")
    if len(body.job_ids) > 500:
        raise HTTPException(400, "Too many IDs (max 500)")

    deleted = 0
    with closing(get_db()) as conn:
        with conn:
            for job_id in body.job_ids:
                cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                deleted += cursor.rowcount

    logger.info("bulk_delete: requested=%d deleted=%d", len(body.job_ids), deleted)
    return {"status": "deleted", "requested": len(body.job_ids), "deleted": deleted}
```

Key points:

- Use `POST` with a body (not `DELETE`) because `DELETE` with a request body is non-standard and some proxies strip it.
- Limit to 500 IDs per request to prevent abuse.
- Return the count of actually deleted rows (some IDs may not exist).
- Each delete is in the same transaction for atomicity.
- Does NOT proxy to other cluster nodes — if you want cross-cluster delete, each job ID should be proxied individually. For simplicity, delete from **local DB only**. Since the cluster shares the same SQLite DB, this covers all jobs owned by this node. Cross-node delete can be a follow-up.

### Also add to CORS

The CORS config already allows `DELETE` (line 103). `POST` is also allowed. No changes needed.

---

## Part 2: Frontend API Client

### File: `frontend/src/lib/api.ts`

Add a new exported function after the existing `deleteJob` (line 131):

```typescript
export const deleteJobsBulk = (jobIds: string[]) =>
  safe(() =>
    api
      .post<{
        status: string;
        requested: number;
        deleted: number;
      }>("/jobs/bulk-delete", { job_ids: jobIds })
      .then((r) => r.data),
  );
```

The existing single `deleteJob` function should remain for use in the Job Detail page.

---

## Part 3: Frontend UI — Selection & Delete

### File: `frontend/src/pages/Jobs.tsx`

#### 3a. Add Selection State

```typescript
const [selectedJobs, setSelectedJobs] = useState<Set<string>>(new Set());
const [deleteLoading, setDeleteLoading] = useState(false);
```

#### 3b. Selection Helpers

```typescript
const toggleSelectJob = (jobId: string) => {
  setSelectedJobs((prev) => {
    const next = new Set(prev);
    if (next.has(jobId)) next.delete(jobId);
    else next.add(jobId);
    return next;
  });
};

const toggleSelectAll = () => {
  if (selectedJobs.size === filteredJobs.length) {
    setSelectedJobs(new Set());
  } else {
    setSelectedJobs(new Set(filteredJobs.map((j) => j.job_id)));
  }
};

const isAllSelected =
  filteredJobs.length > 0 && selectedJobs.size === filteredJobs.length;
const hasSelection = selectedJobs.size > 0;
```

#### 3c. Delete Handler

```typescript
const handleBulkDelete = async () => {
  if (!hasSelection) return;

  const count = selectedJobs.size;
  const confirmed = window.confirm(
    `Delete ${count} job${count > 1 ? "s" : ""}? This cannot be undone.`,
  );
  if (!confirmed) return;

  setDeleteLoading(true);
  try {
    await deleteJobsBulk([...selectedJobs]);
    setSelectedJobs(new Set());
    await fetchJobs();
  } catch (err) {
    console.error("Bulk delete failed:", err);
  } finally {
    setDeleteLoading(false);
  }
};
```

#### 3d. Add "Select All" Checkbox to Table Header

In the `<thead>` section (line 276), add a new first `<th>` with a checkbox:

```tsx
<thead className="text-[10px] uppercase font-bold tracking-wider text-slate-500 bg-slate-950/50">
  <tr>
    <th className="px-4 py-4 w-10">
      <input
        type="checkbox"
        checked={isAllSelected}
        onChange={toggleSelectAll}
        className="w-3.5 h-3.5 rounded border-slate-600 bg-slate-800 text-primary-500 focus:ring-primary-500/30 cursor-pointer"
        title={isAllSelected ? "Deselect all" : "Select all"}
      />
    </th>
    <th className="px-6 py-4">Job</th>
    {/* ... rest of existing headers ... */}
  </tr>
</thead>
```

#### 3e. Add Row Checkbox to Each Table Row

In the `<tbody>` row mapping (line 293), add a new first `<td>` with a checkbox:

```tsx
<tr
  key={job.job_id}
  className={`hover:bg-slate-800/20 transition-colors group ${selectedJobs.has(job.job_id) ? "bg-primary-500/5" : ""}`}
>
  <td className="px-4 py-4" onClick={(e) => e.stopPropagation()}>
    <input
      type="checkbox"
      checked={selectedJobs.has(job.job_id)}
      onChange={() => toggleSelectJob(job.job_id)}
      className="w-3.5 h-3.5 rounded border-slate-600 bg-slate-800 text-primary-500 focus:ring-primary-500/30 cursor-pointer"
    />
  </td>
  <td className="px-6 py-4">{/* ... existing Job cell content ... */}</td>
  {/* ... rest of existing cells ... */}
</tr>
```

**Important**: Update the `colSpan` on the empty-state rows (lines 289, 291) from `8` to `9` since we added a column.

#### 3f. Selection Action Bar

When jobs are selected, show a floating action bar above (or below) the table. Place this between the table header section (line 271) and the table container (line 273):

```tsx
{
  hasSelection && (
    <div className="px-6 py-3 bg-red-500/5 border-b border-red-500/20 flex items-center justify-between animate-in fade-in slide-in-from-top-2 duration-200">
      <div className="flex items-center gap-3">
        <span className="text-sm text-slate-300">
          <span className="font-bold text-white">{selectedJobs.size}</span> job
          {selectedJobs.size > 1 ? "s" : ""} selected
        </span>
        <button
          onClick={() => setSelectedJobs(new Set())}
          className="text-xs text-slate-500 hover:text-slate-300 transition-colors underline"
        >
          Clear selection
        </button>
      </div>
      <button
        onClick={handleBulkDelete}
        disabled={deleteLoading}
        className="flex items-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wider rounded-lg bg-red-600 hover:bg-red-500 active:bg-red-700 text-white transition-colors disabled:opacity-50 shadow-sm"
      >
        {deleteLoading ? (
          <UpdateIcon className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <TrashIcon className="w-3.5 h-3.5" />
        )}
        {deleteLoading
          ? "Deleting..."
          : `Delete ${selectedJobs.size} Job${selectedJobs.size > 1 ? "s" : ""}`}
      </button>
    </div>
  );
}
```

**Note**: Import `TrashIcon` from `@radix-ui/react-icons`. Add it to the import statement at the top of the file:

```typescript
import {
  PlayIcon,
  UpdateIcon,
  MagnifyingGlassIcon,
  ClockIcon,
  TrashIcon,
} from "@radix-ui/react-icons";
```

#### 3g. Selected Row Highlight

Selected rows should have a subtle background tint to visually distinguish them. This is already covered in step 3e with the conditional class:

```tsx
className={`... ${selectedJobs.has(job.job_id) ? 'bg-primary-500/5' : ''}`}
```

#### 3h. Clear Selection on Filter/Search Change

When the user changes the status filter or search text, clear the selection to avoid selecting invisible jobs:

```typescript
const handleSearchChange = (value: string) => {
  setSearch(value);
  setSelectedJobs(new Set());
};

const handleStatusFilterChange = (value: string) => {
  setStatusFilter(value);
  setSelectedJobs(new Set());
};
```

Update the `onChange` handlers for the search input and status `<select>` to use these wrapped functions.

---

## Edge Cases

1. **Deleting a processing job**: The backend deletes the DB row, but the worker may still be running. The worker will fail when it tries to update the deleted row — this is acceptable. The worker already handles missing-row errors gracefully.
2. **Empty selection**: The delete button should not appear when nothing is selected.
3. **Confirmation dialog**: Always confirm before delete. Use `window.confirm()` for simplicity. A custom modal is optional polish.
4. **After deletion**: Clear the selection set and re-fetch jobs immediately.
5. **Cross-node delete**: For now, the bulk endpoint deletes from the local DB. Since the Job Queue calls `/cluster/jobs` (which aggregates), and the single `deleteJob` endpoint already proxies to the owner node, consider iterating with individual `deleteJob` calls per job ID for correct cluster behavior. Alternatively, group job IDs by node prefix and proxy each batch to the correct node.

### Recommended approach for cluster-aware delete:

Since `deleteJob` already handles proxying (line 576–585 in `main.py`), the simplest correct approach is:

```typescript
// In api.ts — use individual deletes with Promise.allSettled for cluster safety
export const deleteJobsBulk = async (jobIds: string[]) => {
  const results = await Promise.allSettled(
    jobIds.map((id) => api.delete(`/jobs/${id}`)),
  );
  const deleted = results.filter((r) => r.status === "fulfilled").length;
  const failed = results.filter((r) => r.status === "rejected").length;
  return { status: "deleted", requested: jobIds.length, deleted, failed };
};
```

This uses the existing proxying infrastructure and avoids needing a new backend endpoint entirely. However, for large batches (50+ jobs), the concurrent requests may be slow. The backend bulk endpoint is faster for single-node deployments.

**Decision**: Implement BOTH:

- The backend `POST /jobs/bulk-delete` for speed on single-node
- The frontend fallback using individual `DELETE /jobs/{id}` calls with `Promise.allSettled` for cluster-aware delete

Use the individual-delete approach in the frontend for correctness:

```typescript
export const deleteJobsBulk = async (
  jobIds: string[],
): Promise<{ deleted: number; failed: number }> => {
  const results = await Promise.allSettled(jobIds.map((id) => deleteJob(id)));
  return {
    deleted: results.filter((r) => r.status === "fulfilled").length,
    failed: results.filter((r) => r.status === "rejected").length,
  };
};
```

---

## Files to modify

1. `video_service/app/main.py` — add optional `POST /jobs/bulk-delete` endpoint (for future use)
2. `frontend/src/lib/api.ts` — add `deleteJobsBulk` function
3. `frontend/src/pages/Jobs.tsx` — add selection state, checkboxes, action bar, delete handler

## Constraints

- **Confirmation required** — never delete without `window.confirm()`.
- **Match existing theme** — dark slate, red accent for destructive action.
- **Import `TrashIcon`** from `@radix-ui/react-icons`.
- **Update `colSpan`** on empty-state rows from 8 to 9.
- **Clear selection** when search/filter changes.
- **No CSS changes needed** — Tailwind utilities cover everything.
