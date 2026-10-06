import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createIndexedDbKeyStore,
  isIndexedDbAvailable,
  KeyStoreUnavailableError,
} from "@/lib/api-key-store";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("indexeddb key store", () => {
  it("reports availability as a boolean", () => {
    expect(typeof isIndexedDbAvailable()).toBe("boolean");
  });

  it("fails safely when IndexedDB is unavailable", async () => {
    vi.stubGlobal("indexedDB", undefined);

    expect(isIndexedDbAvailable()).toBe(false);
    await expect(createIndexedDbKeyStore().load()).rejects.toBeInstanceOf(
      KeyStoreUnavailableError,
    );
    await expect(createIndexedDbKeyStore().save({} as CryptoKey)).rejects.toBeInstanceOf(
      KeyStoreUnavailableError,
    );
  });
});
