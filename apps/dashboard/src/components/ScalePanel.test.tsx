import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurrentUserProvider } from "./CurrentUserProvider";
import { ScalePanel } from "./ScalePanel";

function renderWithRole(role: string) {
  return render(
    <CurrentUserProvider user={{ id: "u1", email: "a@b.test", roles: [role] }}>
      <ScalePanel applicationId="app-1" minReplicas={1} maxReplicas={5} initialDesiredReplicas={2} />
    </CurrentUserProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ScalePanel", () => {
  it("hides the scaling control entirely for a Viewer", () => {
    renderWithRole("Viewer");
    expect(screen.getByText(/requires the Operator or Administrator role/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/increase desired replica count/i)).not.toBeInTheDocument();
  });

  it("steps the desired count up and down within [min, max]", () => {
    renderWithRole("Operator");
    const increase = screen.getByLabelText(/increase desired replica count/i);
    const decrease = screen.getByLabelText(/decrease desired replica count/i);

    fireEvent.click(increase);
    expect(screen.getByText("3")).toBeInTheDocument();
    fireEvent.click(decrease);
    fireEvent.click(decrease);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(decrease).toBeDisabled(); // at minReplicas
  });

  it("requires an explicit confirm step before calling the scale API", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ deployment_id: "dep-1", desired_replicas: 3 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithRole("Administrator");
    fireEvent.click(screen.getByLabelText(/increase desired replica count/i));

    const changeButton = screen.getByRole("button", { name: /change to 3/i });
    fireEvent.click(changeButton);

    // Not called yet — only a confirmation prompt should be showing.
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/apply 3 replica\(s\)\?/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ desired_replicas: 3 });
  });

  it("cancel returns to the unconfirmed state without calling the API", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderWithRole("Administrator");
    fireEvent.click(screen.getByLabelText(/increase desired replica count/i));
    fireEvent.click(screen.getByRole("button", { name: /change to 3/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByText(/apply 3 replica\(s\)\?/i)).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
