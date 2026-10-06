const DB_NAME = "ja-postgres-mcp-client";
const DB_VERSION = 1;
const STORE_NAME = "keys";
const KEY_ID = "api-key";

export class KeyStoreUnavailableError extends Error {
  constructor() {
    super("IndexedDB is unavailable.");
    this.name = "KeyStoreUnavailableError";
  }
}

/** Storage for the non-extractable AES key (IndexedDB by default; injectable in tests). */
export interface KeyStore {
  load(): Promise<CryptoKey | null>;
  save(key: CryptoKey): Promise<void>;
  remove(): Promise<void>;
}

export function isIndexedDbAvailable(): boolean {
  return typeof indexedDB !== "undefined";
}

export function createIndexedDbKeyStore(): KeyStore {
  return {
    load: async () => {
      if (!isIndexedDbAvailable()) throw new KeyStoreUnavailableError();
      const key = await withStore<CryptoKey | undefined>("readonly", (store) => store.get(KEY_ID));
      return key ?? null;
    },
    save: async (key) => {
      if (!isIndexedDbAvailable()) throw new KeyStoreUnavailableError();
      await withStore<IDBValidKey>("readwrite", (store) => store.put(key, KEY_ID));
    },
    remove: async () => {
      if (!isIndexedDbAvailable()) throw new KeyStoreUnavailableError();
      await withStore<undefined>("readwrite", (store) => store.delete(KEY_ID));
    },
  };
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB error"));
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const database = await openDatabase();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      transaction.onabort = () =>
        reject(transaction.error ?? new Error("IndexedDB transaction aborted"));
      const request = run(transaction.objectStore(STORE_NAME));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error("IndexedDB error"));
    });
  } finally {
    database.close();
  }
}
