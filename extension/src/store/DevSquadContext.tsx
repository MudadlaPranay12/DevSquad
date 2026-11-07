import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { BridgeError, createBridgeClient, normalizeBridgeUrl } from "../lib/bridge";
import { DEFAULT_SETTINGS, loadSettings, saveSettings, type Settings } from "../lib/settings";
import type {
  CapturePreview,
  CaptureRequest,
  CaseDetail,
  CaseSummary,
  Decision,
  EventsResponse,
  Timeline,
  Verdict,
  VerdictResponse,
} from "../lib/types";

type DevSquadContextValue = {
  settings: Settings;
  settingsReady: boolean;
  updateSettings: (next: Settings) => Promise<void>;

  caseId: string;
  setCaseId: (value: string) => void;

  preview: CapturePreview | null;
  detail: CaseDetail | null;
  status: CaseSummary | null;
  events: EventsResponse | null;
  timeline: Timeline | null;
  verdict: Verdict | null;
  decision: Record<string, unknown> | null;

  busy: boolean;
  error: string | null;
  notice: string | null;
  polling: boolean;

  clearMessages: () => void;
  runPreview: (request: CaptureRequest) => Promise<CapturePreview | null>;
  runSubmit: (request: CaptureRequest) => Promise<boolean>;
  investigate: () => Promise<void>;
  refresh: (caseIdOverride?: string, includeVerdict?: boolean) => Promise<void>;
  decide: (decision: Decision, note?: string) => Promise<void>;
};

const DevSquadContext = createContext<DevSquadContextValue | null>(null);

function describeError(error: unknown): string {
  if (error instanceof BridgeError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

export function DevSquadProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [settingsReady, setSettingsReady] = useState(false);
  const [caseId, setCaseIdState] = useState("DS-001");
  const [preview, setPreview] = useState<CapturePreview | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [status, setStatus] = useState<CaseSummary | null>(null);
  const [events, setEvents] = useState<EventsResponse | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [decision, setDecision] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  const settingsRef = useRef(settings);
  const caseIdRef = useRef(caseId);
  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);
  useEffect(() => {
    caseIdRef.current = caseId;
  }, [caseId]);

  const client = useMemo(
    () =>
      createBridgeClient(
        () => settingsRef.current.bridgeUrl,
        () => settingsRef.current.token,
      ),
    [],
  );

  useEffect(() => {
    loadSettings().then((loaded) => {
      setSettings({
        bridgeUrl: loaded.bridgeUrl || DEFAULT_SETTINGS.bridgeUrl,
        token: loaded.token || "",
      });
      setSettingsReady(true);
    });
    const storedCase = localStorage.getItem("devsquad-case-id");
    if (storedCase) setCaseIdState(storedCase);
  }, []);

  const updateSettings = useCallback(async (next: Settings) => {
    const normalized: Settings = { ...next, bridgeUrl: normalizeBridgeUrl(next.bridgeUrl) };
    setSettings(normalized);
    settingsRef.current = normalized;
    await saveSettings(normalized);
    setNotice("Bridge settings saved.");
  }, []);

  const setCaseId = useCallback((value: string) => {
    const cleaned = value.trim().toUpperCase();
    setCaseIdState(cleaned);
    caseIdRef.current = cleaned;
    localStorage.setItem("devsquad-case-id", cleaned);
  }, []);

  const clearMessages = useCallback(() => {
    setError(null);
    setNotice(null);
  }, []);

  const refresh = useCallback(
    async (caseIdOverride?: string, includeVerdict = true) => {
      const target = (caseIdOverride || caseIdRef.current).trim();
      if (!target) return;
      const [nextStatus, nextEvents, nextDetail] = await Promise.all([
        client.getStatus(target),
        client.getEvents(target),
        client.getDetail(target).catch(() => null),
      ]);
      setStatus(nextStatus);
      setEvents(nextEvents);
      if (nextDetail) {
        setDetail(nextDetail);
        setTimeline(nextDetail.timeline || null);
        setVerdict(nextDetail.verdict || null);
        setDecision(nextDetail.decision || null);
      }
      if (includeVerdict && nextStatus.verdict_available) {
        try {
          const result: VerdictResponse = await client.getVerdict(target);
          setVerdict(result.verdict);
          setDecision(result.decision || null);
        } catch {
          /* verdict may not be committed yet */
        }
      }
    },
    [client],
  );

  const runPreview = useCallback(
    async (request: CaptureRequest) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      setPreview(null);
      try {
        const result = await client.previewCapture(request);
        setPreview(result);
        setCaseId(result.case_id);
        setNotice(
          `Captured ${result.evidence_count} evidence items. Review the redacted preview, then submit.`,
        );
        return result;
      } catch (err) {
        setError(describeError(err));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [client, setCaseId],
  );

  const runSubmit = useCallback(
    async (request: CaptureRequest) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        const result = await client.submitCapture(request);
        const acceptedId = String(result.case_id || request.case_id);
        setCaseId(acceptedId);
        setPreview(null);
        setNotice(
          `Case ${acceptedId} accepted (${String(result.evidence_count ?? "?")} evidence items).`,
        );
        await refresh(acceptedId, false);
        return true;
      } catch (err) {
        setError(describeError(err));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [client, refresh, setCaseId],
  );

  const investigate = useCallback(async () => {
    const target = caseIdRef.current;
    if (!target) return;
    setBusy(true);
    setError(null);
    setNotice("Investigation queued. Live progress will appear below.");
    try {
      await client.investigate(target);
      await refresh(target, false);
      setPolling(true);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }, [client, refresh]);

  const decide = useCallback(
    async (nextDecision: Decision, note = "") => {
      const target = caseIdRef.current;
      if (!target) return;
      setBusy(true);
      setError(null);
      try {
        const result = await client.decide(target, nextDecision, note);
        setDecision((result.decision as Record<string, unknown>) || null);
        setNotice(`Decision recorded: ${nextDecision}.`);
        await refresh(target, false);
      } catch (err) {
        setError(describeError(err));
      } finally {
        setBusy(false);
      }
    },
    [client, refresh],
  );

  // Live polling while an investigation is running.
  useEffect(() => {
    if (!polling) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const target = caseIdRef.current;
        const nextStatus = await client.getStatus(target);
        if (cancelled) return;
        setStatus(nextStatus);
        const nextEvents = await client.getEvents(target);
        if (cancelled) return;
        setEvents(nextEvents);
        if (["completed", "failed", "timed_out"].includes(nextStatus.status)) {
          setPolling(false);
          await refresh(target, true);
        }
      } catch (err) {
        if (!cancelled) {
          setError(describeError(err));
          setPolling(false);
        }
      }
    };
    void tick();
    const handle = window.setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [polling, client, refresh]);

  const value: DevSquadContextValue = {
    settings,
    settingsReady,
    updateSettings,
    caseId,
    setCaseId,
    preview,
    detail,
    status,
    events,
    timeline,
    verdict,
    decision,
    busy,
    error,
    notice,
    polling,
    clearMessages,
    runPreview,
    runSubmit,
    investigate,
    refresh,
    decide,
  };

  return <DevSquadContext.Provider value={value}>{children}</DevSquadContext.Provider>;
}

export function useDevSquad(): DevSquadContextValue {
  const context = useContext(DevSquadContext);
  if (!context) {
    throw new Error("useDevSquad must be used inside DevSquadProvider");
  }
  return context;
}
