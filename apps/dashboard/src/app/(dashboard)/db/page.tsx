"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { DBTableInfo } from "@/lib/types";

export default function DatabaseTablesPage() {
  const [tables, setTables] = useState<DBTableInfo[] | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    async function load() {
      const response = await apiFetch("/admin/db/tables");
      if (response.status === 403) {
        setForbidden(true);
        return;
      }
      if (response.ok) setTables(await response.json());
    }
    load();
  }, []);

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

  const visible = tables?.filter((t) => t.name.includes(filter.trim().toLowerCase())) ?? null;

  return (
    <div>
      <h1 className="healer-page-title">Database</h1>
      <p className="healer-page-description">
        Every table is fully browsable, editable and deletable — including users, deployments,
        secrets and the audit log itself. Two narrow exceptions: the primary key column of every
        row is never editable (it would break every foreign-key reference to that row), and four
        columns (password hashes, credential/token hashes, encrypted secret values) are always
        redacted and can&apos;t be edited, since there&apos;s no legitimate value to type into a
        password hash. Every edit and delete is recorded in the audit log — including edits to
        the audit log&apos;s own rows.
      </p>

      <div className="healer-card" style={{ maxWidth: 320, marginTop: 16, marginBottom: 16 }}>
        <label className="healer-field">
          Filter tables
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="e.g. server"
          />
        </label>
      </div>

      {visible === null ? (
        <p className="healer-card-description">Loading…</p>
      ) : visible.length === 0 ? (
        <p className="healer-card-description">No tables match &quot;{filter}&quot;.</p>
      ) : (
        <table className="healer-table">
          <thead>
            <tr>
              <th>Table</th>
              <th>Rows</th>
              <th>Columns</th>
              <th>Edit</th>
              <th>Delete</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t) => (
              <tr key={t.name}>
                <td>
                  <Link href={`/db/${t.name}`}>{t.name}</Link>
                </td>
                <td>{t.row_count.toLocaleString()}</td>
                <td>{t.columns.length}</td>
                <td>{t.editable ? "yes" : "view only"}</td>
                <td>{t.deletable ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
