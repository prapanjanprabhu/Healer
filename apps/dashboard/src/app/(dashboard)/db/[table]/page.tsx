"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CheckIcon, Cross2Icon, Pencil2Icon, TrashIcon } from "@radix-ui/react-icons";
import { apiFetch } from "@/lib/api";
import type { DBRowsResponse, DBTableInfo } from "@/lib/types";

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const SEARCH_DEBOUNCE_MS = 300;
const PAGER_WINDOW = 2; // page buttons shown on each side of the current page

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

/** Page numbers to render, with `null` standing in for an ellipsis gap —
 * always shows the first/last page and a window around the current one,
 * the same shape DataTables.net's own pagination uses.
 */
function pageWindow(current: number, totalPages: number): (number | null)[] {
  if (totalPages <= 1) return [1];
  const pages = new Set<number>([1, totalPages]);
  for (let p = current - PAGER_WINDOW; p <= current + PAGER_WINDOW; p++) {
    if (p >= 1 && p <= totalPages) pages.add(p);
  }
  const sorted = [...pages].sort((a, b) => a - b);
  const result: (number | null)[] = [];
  let previous: number | null = null;
  for (const page of sorted) {
    if (previous !== null && page - previous > 1) result.push(null);
    result.push(page);
    previous = page;
  }
  return result;
}

export default function DatabaseTableRowsPage({ params }: { params: { table: string } }) {
  const tableName = params.table;
  const [tableInfo, setTableInfo] = useState<DBTableInfo | null | undefined>(undefined);
  const [forbidden, setForbidden] = useState(false);
  const [rowsResponse, setRowsResponse] = useState<DBRowsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(25);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    async function loadInfo() {
      const response = await apiFetch("/admin/db/tables");
      if (response.status === 403) {
        setForbidden(true);
        return;
      }
      if (!response.ok) return;
      const all: DBTableInfo[] = await response.json();
      setTableInfo(all.find((t) => t.name === tableName) ?? null);
    }
    loadInfo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableName]);

  // Debounce the search box — one request 300ms after typing stops, not
  // one per keystroke — and jump back to page 1 whenever the query changes.
  useEffect(() => {
    const handle = setTimeout(() => {
      setSearch(searchInput);
      setOffset(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  async function loadRows() {
    setLoading(true);
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (search) query.set("search", search);
    if (sortBy) {
      query.set("sort_by", sortBy);
      query.set("sort_dir", sortDir);
    }
    const response = await apiFetch(`/admin/db/tables/${tableName}/rows?${query.toString()}`);
    setLoading(false);
    if (response.ok) setRowsResponse(await response.json());
  }

  useEffect(() => {
    if (tableInfo) loadRows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableInfo, offset, limit, search, sortBy, sortDir]);

  function toggleSort(columnName: string) {
    if (sortBy !== columnName) {
      setSortBy(columnName);
      setSortDir("asc");
    } else {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    }
    setOffset(0);
  }

  function pkOf(row: Record<string, unknown>): string {
    const pk = tableInfo?.single_column_pk;
    return pk ? String(row[pk]) : "";
  }

  function startEdit(row: Record<string, unknown>) {
    if (!tableInfo) return;
    const values: Record<string, string> = {};
    for (const col of tableInfo.editable_columns) {
      const raw = row[col.name];
      if (raw === null || raw === undefined) {
        values[col.name] = "";
      } else if (col.kind === "boolean") {
        values[col.name] = raw ? "true" : "false";
      } else if (col.kind === "json") {
        values[col.name] = JSON.stringify(raw, null, 2);
      } else {
        values[col.name] = String(raw);
      }
    }
    setEditingId(pkOf(row));
    setEditValues(values);
    setError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditValues({});
  }

  async function saveEdit(row: Record<string, unknown>) {
    const rowId = pkOf(row);
    setSavingId(rowId);
    setError(null);
    const response = await apiFetch(`/admin/db/tables/${tableName}/rows/${rowId}`, {
      method: "PATCH",
      body: JSON.stringify({ changes: editValues }),
    });
    setSavingId(null);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not save that row.");
      return;
    }
    setEditingId(null);
    setEditValues({});
    loadRows();
  }

  async function deleteRow(row: Record<string, unknown>) {
    const rowId = pkOf(row);
    if (!confirm(`Delete this row from "${tableName}"? This cannot be undone.`)) return;
    setDeletingId(rowId);
    setError(null);
    const response = await apiFetch(`/admin/db/tables/${tableName}/rows/${rowId}`, {
      method: "DELETE",
    });
    setDeletingId(null);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Could not delete that row.");
      return;
    }
    loadRows();
  }

  const total = rowsResponse?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + limit, total);
  const pages = useMemo(() => pageWindow(currentPage, totalPages), [currentPage, totalPages]);

  if (forbidden) {
    return (
      <div>
        <h1 className="healer-page-title">Database</h1>
        <p className="healer-card-description">
          Database management requires the Administrator role.
        </p>
      </div>
    );
  }

  if (tableInfo === undefined) {
    return <p className="healer-card-description">Loading…</p>;
  }

  if (tableInfo === null) {
    return (
      <div>
        <h1 className="healer-page-title">Database</h1>
        <p className="healer-error">No table named &quot;{tableName}&quot;.</p>
        <Link href="/db">Back to tables</Link>
      </div>
    );
  }

  const editableColumnNames = new Set(tableInfo.editable_columns.map((c) => c.name));
  const hasActionsColumn = tableInfo.editable || tableInfo.deletable;

  return (
    <div className="healer-wide-page">
      <Link href="/db">← All tables</Link>
      <h1 className="healer-page-title" style={{ marginTop: 8 }}>
        {tableName}
      </h1>
      <p className="healer-page-description">
        {tableInfo.editable
          ? "Every column is editable except the primary key (id) and any redacted column below."
          : "This table has a composite primary key, so individual rows can't be addressed for edit/delete here — browse only."}
        {tableInfo.deletable && " Rows can be deleted."} Changes and deletions are recorded in
        the audit log.
      </p>

      {error && <div className="healer-error" style={{ marginBottom: 12 }}>{error}</div>}

      <div className="healer-dt-toolbar">
        <label className="healer-dt-length">
          Show
          <select
            value={limit}
            onChange={(e) => {
              setLimit(Number(e.target.value));
              setOffset(0);
            }}
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          entries
        </label>
        <label className="healer-dt-search">
          Search
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder={`Search ${tableName}…`}
            aria-label={`Search ${tableName}`}
          />
        </label>
      </div>

      {rowsResponse === null ? (
        <p className="healer-card-description">Loading…</p>
      ) : (
        <>
          <div className="healer-dt-wrap">
            <table>
              <thead>
                <tr>
                  {tableInfo.columns.map((col) => {
                    const active = sortBy === col.name;
                    return (
                      <th
                        key={col.name}
                        className="healer-dt-sortable"
                        onClick={() => toggleSort(col.name)}
                        aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                      >
                        {col.name}
                        {col.primary_key && " (pk)"}
                        <span className="healer-dt-sort-arrow" data-active={active}>
                          {active ? (sortDir === "asc" ? "▲" : "▼") : "↕"}
                        </span>
                      </th>
                    );
                  })}
                  {hasActionsColumn && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {rowsResponse.rows.length === 0 ? (
                  <tr>
                    <td
                      colSpan={tableInfo.columns.length + (hasActionsColumn ? 1 : 0)}
                      style={{ textAlign: "center", padding: 24 }}
                    >
                      {search ? `No rows match "${search}".` : "No rows."}
                    </td>
                  </tr>
                ) : (
                  rowsResponse.rows.map((row) => {
                    const rowId = pkOf(row);
                    const isEditing = editingId === rowId;
                    return (
                      <tr key={rowId || JSON.stringify(row)}>
                        {tableInfo.columns.map((col) => {
                          const editSpec = tableInfo.editable_columns.find(
                            (c) => c.name === col.name
                          );
                          if (isEditing && editSpec) {
                            if (editSpec.kind === "select" && editSpec.choices) {
                              return (
                                <td key={col.name}>
                                  <select
                                    value={editValues[col.name] ?? ""}
                                    onChange={(e) =>
                                      setEditValues((v) => ({ ...v, [col.name]: e.target.value }))
                                    }
                                  >
                                    {editSpec.choices.map((choice) => (
                                      <option key={choice} value={choice}>
                                        {choice}
                                      </option>
                                    ))}
                                  </select>
                                </td>
                              );
                            }
                            if (editSpec.kind === "boolean") {
                              return (
                                <td key={col.name}>
                                  <input
                                    type="checkbox"
                                    checked={editValues[col.name] === "true"}
                                    onChange={(e) =>
                                      setEditValues((v) => ({
                                        ...v,
                                        [col.name]: e.target.checked ? "true" : "false",
                                      }))
                                    }
                                  />
                                </td>
                              );
                            }
                            if (editSpec.kind === "json" || editSpec.multiline) {
                              return (
                                <td key={col.name}>
                                  <textarea
                                    rows={4}
                                    style={{ minWidth: 220, fontFamily: "monospace", fontSize: 12 }}
                                    value={editValues[col.name] ?? ""}
                                    onChange={(e) =>
                                      setEditValues((v) => ({ ...v, [col.name]: e.target.value }))
                                    }
                                  />
                                </td>
                              );
                            }
                            return (
                              <td key={col.name}>
                                <input
                                  type="text"
                                  value={editValues[col.name] ?? ""}
                                  onChange={(e) =>
                                    setEditValues((v) => ({ ...v, [col.name]: e.target.value }))
                                  }
                                />
                              </td>
                            );
                          }
                          return (
                            <td key={col.name} title={formatCell(row[col.name])}>
                              {formatCell(row[col.name])}
                            </td>
                          );
                        })}
                        {hasActionsColumn && (
                          <td className="healer-dt-actions">
                            <div className="healer-dt-actions-inner">
                              {tableInfo.editable &&
                                (isEditing ? (
                                  <>
                                    <button onClick={() => saveEdit(row)} disabled={savingId === rowId}>
                                      <CheckIcon width={14} height={14} />
                                      {savingId === rowId ? "Saving…" : "Save"}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={cancelEdit}
                                      disabled={savingId === rowId}
                                    >
                                      <Cross2Icon width={14} height={14} />
                                      Cancel
                                    </button>
                                  </>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => startEdit(row)}
                                    disabled={editableColumnNames.size === 0}
                                  >
                                    <Pencil2Icon width={14} height={14} />
                                    Edit
                                  </button>
                                ))}
                              {tableInfo.deletable && !isEditing && (
                                <button
                                  type="button"
                                  className="healer-btn-danger"
                                  onClick={() => deleteRow(row)}
                                  disabled={deletingId === rowId}
                                >
                                  <TrashIcon width={14} height={14} />
                                  {deletingId === rowId ? "Deleting…" : "Delete"}
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          <div className="healer-dt-footer">
            <span className="healer-dt-footer-info" aria-live="polite">
              {loading
                ? "Loading…"
                : total === 0
                  ? "No entries"
                  : `Showing ${rangeStart} to ${rangeEnd} of ${total} entries`}
            </span>
            <nav className="healer-dt-pager" aria-label="Table pages">
              <button
                type="button"
                onClick={() => setOffset(0)}
                disabled={currentPage === 1}
              >
                « First
              </button>
              <button
                type="button"
                onClick={() => setOffset((o) => Math.max(0, o - limit))}
                disabled={currentPage === 1}
              >
                ‹ Prev
              </button>
              {pages.map((p, i) =>
                p === null ? (
                  <button key={`ellipsis-${i}`} type="button" disabled data-ellipsis="true">
                    …
                  </button>
                ) : (
                  <button
                    key={p}
                    type="button"
                    data-current={p === currentPage || undefined}
                    onClick={() => setOffset((p - 1) * limit)}
                  >
                    {p}
                  </button>
                )
              )}
              <button
                type="button"
                onClick={() => setOffset((o) => o + limit)}
                disabled={currentPage >= totalPages}
              >
                Next ›
              </button>
              <button
                type="button"
                onClick={() => setOffset((totalPages - 1) * limit)}
                disabled={currentPage >= totalPages}
              >
                Last »
              </button>
            </nav>
          </div>
        </>
      )}
    </div>
  );
}
