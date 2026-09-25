"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { DBRowsResponse, DBTableInfo } from "@/lib/types";

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

export default function DatabaseTableRowsPage({ params }: { params: { table: string } }) {
  const tableName = params.table;
  const [tableInfo, setTableInfo] = useState<DBTableInfo | null | undefined>(undefined);
  const [forbidden, setForbidden] = useState(false);
  const [rowsResponse, setRowsResponse] = useState<DBRowsResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 25;
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

  async function loadRows() {
    const response = await apiFetch(
      `/admin/db/tables/${tableName}/rows?limit=${limit}&offset=${offset}`
    );
    if (response.ok) setRowsResponse(await response.json());
  }

  useEffect(() => {
    if (tableInfo) loadRows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableInfo, offset]);

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
  const total = rowsResponse?.total ?? 0;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + limit, total);

  return (
    <div>
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

      {rowsResponse === null ? (
        <p className="healer-card-description">Loading…</p>
      ) : rowsResponse.rows.length === 0 ? (
        <p className="healer-card-description">No rows.</p>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table className="healer-table">
              <thead>
                <tr>
                  {tableInfo.columns.map((col) => (
                    <th key={col.name}>
                      {col.name}
                      {col.primary_key && " (pk)"}
                    </th>
                  ))}
                  {(tableInfo.editable || tableInfo.deletable) && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {rowsResponse.rows.map((row) => {
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
                          <td
                            key={col.name}
                            style={{
                              maxWidth: 320,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                            title={formatCell(row[col.name])}
                          >
                            {formatCell(row[col.name])}
                          </td>
                        );
                      })}
                      {(tableInfo.editable || tableInfo.deletable) && (
                        <td style={{ display: "flex", gap: 6, whiteSpace: "nowrap" }}>
                          {tableInfo.editable &&
                            (isEditing ? (
                              <>
                                <button onClick={() => saveEdit(row)} disabled={savingId === rowId}>
                                  {savingId === rowId ? "Saving…" : "Save"}
                                </button>
                                <button type="button" onClick={cancelEdit} disabled={savingId === rowId}>
                                  Cancel
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                onClick={() => startEdit(row)}
                                disabled={editableColumnNames.size === 0}
                              >
                                Edit
                              </button>
                            ))}
                          {tableInfo.deletable && !isEditing && (
                            <button
                              type="button"
                              onClick={() => deleteRow(row)}
                              disabled={deletingId === rowId}
                            >
                              {deletingId === rowId ? "Deleting…" : "Delete"}
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12 }}>
            <button
              type="button"
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
              disabled={offset === 0}
            >
              Previous
            </button>
            <span className="healer-card-description">
              {rangeStart}–{rangeEnd} of {total}
            </span>
            <button
              type="button"
              onClick={() => setOffset((o) => o + limit)}
              disabled={offset + limit >= total}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
