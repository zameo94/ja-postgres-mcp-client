import { beforeEach, describe, expect, it } from "vitest";

import { KeyStoreUnavailableError, type KeyStore } from "@/lib/api-key-store";
import { SecureCryptoUnavailableError } from "@/lib/crypto";
import {
  ApiKeyMissingError,
  ApiKeyUnavailableError,
  ApiKeyUnreadableError,
  clearApiKey,
  hasStoredApiKey,
  isAllowedBaseUrl,
  loadProviderSettings,
  requireApiKey,
  saveApiKey,
  saveProviderSettings,
} from "@/lib/provider-settings";

const SETTINGS_KEY = "ja-postgres-mcp-client.provider";
const CIPHERTEXT_KEY = "ja-postgres-mcp-client.apiKey";

function memoryStore(): KeyStore {
  let key: CryptoKey | null = null;
  return {
    load: async () => key,
    save: async (next) => {
      key = next;
    },
    remove: async () => {
      key = null;
    },
  };
}

function unavailableStore(): KeyStore {
  return {
    load: async () => {
      throw new KeyStoreUnavailableError();
    },
    save: async () => {
      throw new KeyStoreUnavailableError();
    },
    remove: async () => {
      throw new KeyStoreUnavailableError();
    },
  };
}

describe("provider settings", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(loadProviderSettings()).toBeNull();
  });

  it("round-trips stored settings", () => {
    saveProviderSettings({
      provider: "external_api",
      model: "gpt-4o-mini",
      base_url: "https://api.example.com/v1",
    });

    expect(loadProviderSettings()).toEqual({
      provider: "external_api",
      model: "gpt-4o-mini",
      base_url: "https://api.example.com/v1",
    });
  });

  it("ignores malformed stored settings", () => {
    localStorage.setItem(SETTINGS_KEY, "{not-json");

    expect(loadProviderSettings()).toBeNull();
  });

  it("reports no stored api key by default", () => {
    expect(hasStoredApiKey()).toBe(false);
  });

  it("encrypts, persists and decrypts the api key", async () => {
    const store = memoryStore();

    await saveApiKey("sk-secret", store);

    expect(hasStoredApiKey()).toBe(true);
    expect(localStorage.getItem(CIPHERTEXT_KEY)).not.toContain("sk-secret");
    expect(await requireApiKey(store)).toBe("sk-secret");
  });

  it("throws missing when no key is stored", async () => {
    await expect(requireApiKey(memoryStore())).rejects.toBeInstanceOf(ApiKeyMissingError);
  });

  it("throws unreadable when the stored key is gone", async () => {
    localStorage.setItem(CIPHERTEXT_KEY, "AAAA.BBBB");

    await expect(requireApiKey(memoryStore())).rejects.toBeInstanceOf(ApiKeyUnreadableError);
  });

  it("throws unavailable when the key store is unavailable", async () => {
    localStorage.setItem(CIPHERTEXT_KEY, "AAAA.BBBB");

    await expect(requireApiKey(unavailableStore())).rejects.toBeInstanceOf(
      ApiKeyUnavailableError,
    );
  });

  it("fails safely when saving without a key store", async () => {
    await expect(saveApiKey("sk-secret", unavailableStore())).rejects.toBeInstanceOf(
      SecureCryptoUnavailableError,
    );
  });

  it("clears the stored key", async () => {
    const store = memoryStore();
    await saveApiKey("sk-secret", store);

    clearApiKey(store);

    expect(hasStoredApiKey()).toBe(false);
    await expect(requireApiKey(store)).rejects.toBeInstanceOf(ApiKeyMissingError);
  });
});

describe("isAllowedBaseUrl", () => {
  it("accepts https anywhere", () => {
    expect(isAllowedBaseUrl("https://api.example.com/v1")).toBe(true);
  });

  it("accepts http only for localhost", () => {
    expect(isAllowedBaseUrl("http://localhost:1234/v1")).toBe(true);
    expect(isAllowedBaseUrl("http://127.0.0.1:1234/v1")).toBe(true);
    expect(isAllowedBaseUrl("http://api.example.com/v1")).toBe(false);
  });

  it("rejects non-http(s) and malformed URLs", () => {
    expect(isAllowedBaseUrl("ftp://api.example.com")).toBe(false);
    expect(isAllowedBaseUrl("not-a-url")).toBe(false);
  });
});
