import { describe, expect, it } from "vitest";

import { decryptText, encryptText, generateAesKey } from "@/lib/crypto";

describe("crypto", () => {
  it("round-trips text", async () => {
    const key = await generateAesKey();

    const ciphertext = await encryptText("sk-secret", key);

    expect(await decryptText(ciphertext, key)).toBe("sk-secret");
  });

  it("does not contain the plaintext", async () => {
    const key = await generateAesKey();

    const ciphertext = await encryptText("sk-secret", key);

    expect(ciphertext).not.toContain("sk-secret");
  });

  it("fails to decrypt with another key", async () => {
    const [key1, key2] = await Promise.all([generateAesKey(), generateAesKey()]);
    const ciphertext = await encryptText("sk-secret", key1);

    await expect(decryptText(ciphertext, key2)).rejects.toBeTruthy();
  });

  it("rejects malformed ciphertext", async () => {
    const key = await generateAesKey();

    await expect(decryptText("garbage", key)).rejects.toBeTruthy();
  });
});
