import { describe, expect, it } from "vitest";
import { hasPermission, isAdministrator } from "./permissions";

describe("hasPermission", () => {
  it("grants Administrator every permission", () => {
    expect(hasPermission(["Administrator"], "manage_users")).toBe(true);
    expect(hasPermission(["Administrator"], "anything-at-all")).toBe(true);
  });

  it("grants Operator only its listed permissions", () => {
    expect(hasPermission(["Operator"], "scale")).toBe(true);
    expect(hasPermission(["Operator"], "manage_users")).toBe(false);
  });

  it("grants Viewer only view", () => {
    expect(hasPermission(["Viewer"], "view")).toBe(true);
    expect(hasPermission(["Viewer"], "deploy")).toBe(false);
  });

  it("checks every role a user holds", () => {
    expect(hasPermission(["Viewer", "Operator"], "scale")).toBe(true);
  });

  it("denies an unknown role", () => {
    expect(hasPermission(["NotARole"], "view")).toBe(false);
  });
});

describe("isAdministrator", () => {
  it("is true only when Administrator is among the roles", () => {
    expect(isAdministrator(["Administrator", "Viewer"])).toBe(true);
    expect(isAdministrator(["Operator"])).toBe(false);
  });
});
