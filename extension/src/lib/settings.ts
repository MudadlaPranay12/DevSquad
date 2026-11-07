export type Settings = {
  bridgeUrl: string;
  token: string;
};

const STORAGE_KEY = "devsquad-settings";
const DEFAULT_SETTINGS: Settings = { bridgeUrl: "http://127.0.0.1:8000", token: "" };

function hasChromeStorage(): boolean {
  return (
    typeof chrome !== "undefined" &&
    !!chrome.storage &&
    !!chrome.storage.local
  );
}

export async function loadSettings(): Promise<Settings> {
  if (hasChromeStorage()) {
    const result = await chrome.storage.local.get(STORAGE_KEY);
    return { ...DEFAULT_SETTINGS, ...(result[STORAGE_KEY] || {}) };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : { ...DEFAULT_SETTINGS };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export async function saveSettings(settings: Settings): Promise<void> {
  if (hasChromeStorage()) {
    await chrome.storage.local.set({ [STORAGE_KEY]: settings });
    return;
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export { DEFAULT_SETTINGS };
