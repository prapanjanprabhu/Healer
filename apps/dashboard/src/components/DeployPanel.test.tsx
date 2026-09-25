import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurrentUserProvider } from "./CurrentUserProvider";
import { DeployPanel } from "./DeployPanel";

function renderWithRole(role: string) {
  return render(
    <CurrentUserProvider user={{ id: "u1", email: "a@b.test", roles: [role] }}>
      <DeployPanel applicationId="app-1" />
    </CurrentUserProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DeployPanel", () => {
  it("hides the deploy control entirely for a Viewer", () => {
    renderWithRole("Viewer");
    expect(screen.getByText(/requires the Operator or Administrator role/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^deploy$/i })).not.toBeInTheDocument();
  });

  it("requires an explicit confirm step before calling the deploy API", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ deployment_id: "dep-1" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithRole("Operator");
    fireEvent.click(screen.getByRole("button", { name: /^deploy$/i }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/start a new deployment\?/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toContain("/applications/app-1/deploy");
  });

  it("cancel returns to the unconfirmed state without calling the API", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderWithRole("Administrator");
    fireEvent.click(screen.getByRole("button", { name: /^deploy$/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByText(/start a new deployment\?/i)).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
