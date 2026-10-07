import type { ProviderId } from "./types";

const PROVIDER_KEY = "ja-postgres-mcp-client.provider";

/**
 * The only client-side preference is the selected provider. Model, base URL and
 * API key are server configuration (environment), so no secret is ever stored in
 * the browser.
 */
export function loadProvider(): ProviderId | null {
  const raw = localStorage.getItem(PROVIDER_KEY);
  if (raw === "ollama" || raw === "external_api") return raw;
  return null;
}

export function saveProvider(provider: ProviderId): void {
  localStorage.setItem(PROVIDER_KEY, provider);
}
