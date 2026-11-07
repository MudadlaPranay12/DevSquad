import type {
  CapturePreview,
  CaptureRequest,
  CaseDetail,
  CaseSummary,
  Decision,
  EventsResponse,
  Timeline,
  VerdictResponse,
} from "./types";

const DEFAULT_BRIDGE_URL = "http://127.0.0.1:8000";

export class BridgeError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(BridgeError.describe(status, detail));
    this.name = "BridgeError";
    this.status = status;
    this.detail = detail;
  }

  static describe(status: number, detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const record = detail as Record<string, unknown>;
      if (typeof record.error === "string") {
        const extra =
          Array.isArray(record.validation_errors)
            ? ` — ${record.validation_errors.join("; ")}`
            : typeof record.output === "string" && record.output
              ? ` — ${record.output}`
              : "";
        return `${record.error}${extra}`;
      }
      if (typeof record.detail === "string") return record.detail;
    }
    return `Bridge request failed with HTTP ${status}.`;
  }
}

export function normalizeBridgeUrl(value: string): string {
  const trimmed = (value || DEFAULT_BRIDGE_URL).trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(trimmed)) {
    return `http://${trimmed}`;
  }
  return trimmed;
}

async function request<T>(
  baseUrl: string,
  token: string,
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${normalizeBridgeUrl(baseUrl)}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-DevSquad-Token": token,
      ...(options.headers || {}),
    },
  });

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in (payload as Record<string, unknown>)
        ? (payload as Record<string, unknown>).detail
        : payload;
    throw new BridgeError(response.status, detail);
  }

  return payload as T;
}

export function createBridgeClient(getBaseUrl: () => string, getToken: () => string) {
  const call = <T>(path: string, options: RequestInit = {}) =>
    request<T>(getBaseUrl(), getToken(), path, options);

  return {
    health: () => call<Record<string, unknown>>("/health"),

    previewCapture: (body: CaptureRequest) =>
      call<CapturePreview>("/capture/preview", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    submitCapture: (body: CaptureRequest) =>
      call<Record<string, unknown>>("/capture", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    submitBundle: (bundle: unknown) =>
      call<Record<string, unknown>>("/cases", {
        method: "POST",
        body: JSON.stringify(bundle),
      }),

    listCases: () => call<{ cases: CaseSummary[]; count: number }>("/cases"),

    getDetail: (caseId: string) => call<CaseDetail>(`/cases/${caseId}/detail`),

    getStatus: (caseId: string) => call<CaseSummary>(`/cases/${caseId}/status`),

    getEvents: (caseId: string, afterId = 0) =>
      call<EventsResponse>(`/cases/${caseId}/events?after_id=${afterId}`),

    getTimeline: (caseId: string) => call<Timeline>(`/cases/${caseId}/timeline`),

    getVerdict: (caseId: string) =>
      call<VerdictResponse>(`/cases/${caseId}/verdict`),

    investigate: (caseId: string) =>
      call<Record<string, unknown>>(`/cases/${caseId}/investigate`, { method: "POST" }),

    decide: (caseId: string, decision: Decision, note = "") =>
      call<Record<string, unknown>>(`/cases/${caseId}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, note }),
      }),
  };
}

export type BridgeClient = ReturnType<typeof createBridgeClient>;
