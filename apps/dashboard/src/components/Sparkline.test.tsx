import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders a 'no data' label when given no values", () => {
    render(<Sparkline values={[]} />);
    expect(screen.getByRole("img", { name: /no data/i })).toBeInTheDocument();
  });

  it("renders an SVG polyline for real values", () => {
    const { container } = render(<Sparkline values={[10, 20, 30]} />);
    const polyline = container.querySelector("polyline");
    expect(polyline).not.toBeNull();
    expect(polyline?.getAttribute("points")).toBeTruthy();
  });
});
