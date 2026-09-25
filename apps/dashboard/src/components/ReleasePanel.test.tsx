import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurrentUserProvider } from "./CurrentUserProvider";
import { ReleasePanel } from "./ReleasePanel";

const RELEASES = [
  { id: "r-active", ref: "v2", status: "ready", is_active: true, created_at: "2026-01-01T00:00:00Z" },
  { id: "r-prior", ref: "v1", status: "ready", is_active: false, created_at: "2025-12-01T00:00:00Z" },
];

function jsonResponse(body: unknown) {
  return { ok: true, json: async () => body };
}

function renderWithRole(role: string, fetchMock = vi.fn().mockResolvedValue(jsonResponse(RELEASES))) {
  vi.stubGlobal("fetch", fetchMock);
  const utils = render(
    <CurrentUserProvider user={{ id: "u1", email: "a@b.test", roles: [role] }}>
      <ReleasePanel applicationId="app-1" />
    </CurrentUserProvider>
  );
  return { ...utils, fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ReleasePanel", () => {
  it("hides deploy and rollback controls for a Viewer", async () => {
    renderWithRole("Viewer");
    await waitFor(() => expect(screen.getByText(/require the Operator or Administrator role/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /deploy new release/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /roll back/i })).not.toBeInTheDocument();
  });

  it("requires an explicit confirm step before deploying a new release", async () => {
    const { fetchMock } = renderWithRole("Operator");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    fetchMock.mockResolvedValueOnce(jsonResponse({ deployment_id: "dep-1", warnings: [] }));
    fireEvent.click(screen.getByRole("button", { name: /deploy new release/i }));

    expect(screen.getByText(/start a new release switch\?/i)).toBeInTheDocument();
    const callsBeforeConfirm = fetchMock.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBeforeConfirm));
    const [url, init] = fetchMock.mock.calls[callsBeforeConfirm];
    expect(url).toContain("/applications/app-1/releases");
    expect(init.method).toBe("POST");
  });

  it("requires selecting a release and an explicit confirm step before rolling back", async () => {
    const { fetchMock } = renderWithRole("Administrator");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("option", { name: /v1/ })).toBeInTheDocument());

    expect(screen.getByRole("button", { name: /roll back/i })).toBeDisabled();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "r-prior" } });
    expect(screen.getByRole("button", { name: /roll back/i })).toBeEnabled();

    fetchMock.mockResolvedValueOnce(jsonResponse({ deployment_id: "dep-2" }));
    fireEvent.click(screen.getByRole("button", { name: /roll back/i }));

    expect(screen.getByText(/roll back to the selected release\?/i)).toBeInTheDocument();
    const callsBeforeConfirm = fetchMock.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBeforeConfirm));
    const [url, init] = fetchMock.mock.calls[callsBeforeConfirm];
    expect(url).toContain("/applications/app-1/rollback");
    expect(JSON.parse(init.body)).toEqual({ release_id: "r-prior" });
  });
});
