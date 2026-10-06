const ALGORITHM = "AES-GCM";
const KEY_LENGTH = 256;
const IV_LENGTH = 12;

export class SecureCryptoUnavailableError extends Error {
  constructor() {
    super("Secure cryptography is not available in this browser.");
    this.name = "SecureCryptoUnavailableError";
  }
}

export function isSecureCryptoAvailable(): boolean {
  return (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.subtle !== "undefined" &&
    typeof globalThis.crypto.getRandomValues === "function"
  );
}

/** Generate a non-extractable AES-GCM key. */
export async function generateAesKey(): Promise<CryptoKey> {
  if (!isSecureCryptoAvailable()) throw new SecureCryptoUnavailableError();
  return globalThis.crypto.subtle.generateKey(
    { name: ALGORITHM, length: KEY_LENGTH },
    false,
    ["encrypt", "decrypt"],
  );
}

/** Encrypt UTF-8 text; returns `base64(iv).base64(ciphertext)`. */
export async function encryptText(plaintext: string, key: CryptoKey): Promise<string> {
  const iv = globalThis.crypto.getRandomValues(new Uint8Array(IV_LENGTH));
  const encoded = new TextEncoder().encode(plaintext);
  const ciphertext = await globalThis.crypto.subtle.encrypt(
    { name: ALGORITHM, iv },
    key,
    encoded,
  );
  return `${toBase64(iv)}.${toBase64(new Uint8Array(ciphertext))}`;
}

export async function decryptText(payload: string, key: CryptoKey): Promise<string> {
  const [ivPart, dataPart] = payload.split(".");
  if (!ivPart || !dataPart) throw new Error("Malformed ciphertext");
  const plaintext = await globalThis.crypto.subtle.decrypt(
    { name: ALGORITHM, iv: fromBase64(ivPart) },
    key,
    fromBase64(dataPart),
  );
  return new TextDecoder().decode(plaintext);
}

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}
