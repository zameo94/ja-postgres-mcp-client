import { beforeEach, describe, expect, it } from "vitest";

import { loadProvider, saveProvider } from "@/lib/provider-settings";

describe("provider settings", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(loadProvider()).toBeNull();
  });

  it("round-trips the selected provider", () => {
    saveProvider("external_api");

    expect(loadProvider()).toBe("external_api");
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("ja-postgres-mcp-client.provider", "nope");

    expect(loadProvider()).toBeNull();
  });
});
