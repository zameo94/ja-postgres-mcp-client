import {
  createIndexedDbKeyStore,
  KeyStoreUnavailableError,
  type KeyStore,
} from "./api-key-store";
import {
  decryptText,
  encryptText,
  generateAesKey,
  isSecureCryptoAvailable,
  SecureCryptoUnavailableError,
} from "./crypto";
import type { ProviderId } from "./types";

const SETTINGS_KEY = "ja-postgres-mcp-client.provider";
const API_KEY_CIPHERTEXT_KEY = "ja-postgres-mcp-client.apiKey";

const defaultKeyStore = createIndexedDbKeyStore();

export class ApiKeyMissingError extends Error {
  constructor() {
    super("No API key is stored.");
    this.name = "ApiKeyMissingError";
  }
}

export class ApiKeyUnavailableError extends Error {
  constructor() {
    super("Secure storage is unavailable in this browser.");
    this.name = "ApiKeyUnavailableError";
  }
}

export class ApiKeyUnreadableError extends Error {
  constructor() {
    super("The stored API key could not be read.");
    this.name = "ApiKeyUnreadableError";
  }
}

export interface StoredProviderSettings {
  provider: ProviderId;
  model: string;
  base_url: string;
}

export function loadProviderSettings(): StoredProviderSettings | null {
  const raw = localStorage.getItem(SETTINGS_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredProviderSettings>;
    if (
      (parsed.provider === "ollama" || parsed.provider === "external_api") &&
      typeof parsed.model === "string"
    ) {
      return {
        provider: parsed.provider,
        model: parsed.model,
        base_url: typeof parsed.base_url === "string" ? parsed.base_url : "",
      };
    }
  } catch {
    // ignore malformed stored settings
  }
  return null;
}

export function saveProviderSettings(settings: StoredProviderSettings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export function hasStoredApiKey(): boolean {
  return localStorage.getItem(API_KEY_CIPHERTEXT_KEY) !== null;
}

/** Whether a base URL is acceptable to the backend (https, or http for localhost). */
export function isAllowedBaseUrl(url: string): boolean {
  try {
    const parsed = new URL(url.trim());
    if (parsed.protocol === "https:") return true;
    if (parsed.protocol === "http:") {
      return ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname);
    }
    return false;
  } catch {
    return false;
  }
}

/** Encrypt and persist the API key; the plaintext never reaches storage. */
export async function saveApiKey(
  plaintext: string,
  keyStore: KeyStore = defaultKeyStore,
): Promise<void> {
  if (!isSecureCryptoAvailable()) throw new SecureCryptoUnavailableError();

  let key: CryptoKey | null;
  try {
    key = await keyStore.load();
  } catch (error) {
    throw unavailableFrom(error);
  }
  if (!key) {
    key = await generateAesKey();
    try {
      await keyStore.save(key);
    } catch (error) {
      throw unavailableFrom(error);
    }
  }
  localStorage.setItem(API_KEY_CIPHERTEXT_KEY, await encryptText(plaintext, key));
}

/**
 * Return the decrypted API key, or throw a typed error distinguishing missing,
 * unavailable and unreadable states.
 */
export async function requireApiKey(keyStore: KeyStore = defaultKeyStore): Promise<string> {
  const ciphertext = localStorage.getItem(API_KEY_CIPHERTEXT_KEY);
  if (!ciphertext) throw new ApiKeyMissingError();
  if (!isSecureCryptoAvailable()) throw new ApiKeyUnavailableError();

  let key: CryptoKey | null;
  try {
    key = await keyStore.load();
  } catch (error) {
    if (error instanceof KeyStoreUnavailableError) throw new ApiKeyUnavailableError();
    throw error;
  }
  if (!key) throw new ApiKeyUnreadableError();

  try {
    return await decryptText(ciphertext, key);
  } catch {
    throw new ApiKeyUnreadableError();
  }
}

export function clearApiKey(keyStore: KeyStore = defaultKeyStore): void {
  localStorage.removeItem(API_KEY_CIPHERTEXT_KEY);
  void keyStore.remove().catch(() => undefined);
}

function unavailableFrom(error: unknown): Error {
  if (error instanceof KeyStoreUnavailableError) return new SecureCryptoUnavailableError();
  return error instanceof Error ? error : new Error("Key storage failed");
}
