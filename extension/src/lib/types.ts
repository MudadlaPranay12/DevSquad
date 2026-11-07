export type EvidenceItem = {
  id: string;
  legacy_id?: string;
  source?: string;
  type: string;
  timestamp?: string | null;
  message?: string;
  level?: string;
  url?: string;
  method?: string;
  status?: number;
  selector?: string;
  observation?: string;
  cookie_name?: string;
  [key: string]: unknown;
};

export type EvidenceBundle = {
  schema_version?: number;
  case_id: string;
  timestamp?: string | null;
  source?: string;
  capture_source?: string;
  page_url: string;
  incident_description?: string;
  evidence: EvidenceItem[];
  warnings?: string[];
  redaction_applied?: boolean;
  [key: string]: unknown;
};

export type CaptureRequest = {
  url: string;
  case_id: string;
  schema_version: 1 | 2;
  click?: string | null;
  incident_description?: string | null;
};

export type CapturePreview = {
  status: "preview";
  case_id: string;
  schema_version: number;
  evidence_count: number;
  warnings: string[];
  redaction_applied: boolean;
  bundle: EvidenceBundle;
  note: string;
};

export type CaseSummary = {
  case_id: string;
  status: string;
  stage: string;
  transport?: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  agent_rounds: number;
  verdict_available: boolean;
};

export type CaseEvent = {
  event_id: number;
  case_id: string;
  event_type: string;
  timestamp: string;
  data: Record<string, unknown>;
};

export type AgentMessage = {
  message_id: number;
  agent_id: string;
  message_type: string;
  timestamp: string;
  evidence_ids?: string[];
  content?: Record<string, unknown>;
  accepted?: boolean;
  round?: number;
};

export type TimelineEvent = {
  evidence_id: string;
  source?: string;
  type?: string;
  timestamp?: string | null;
  relative?: string | null;
  ordering?: string;
  summary: string;
  is_error?: boolean;
  is_app_failure?: boolean;
  related_evidence_ids?: string[];
};

export type Timeline = {
  case_id: string;
  base_time?: string;
  events: TimelineEvent[];
  relationships?: Array<Record<string, unknown>>;
  coverage?: Record<string, unknown>;
  timeline_text?: string;
  warnings?: string[];
  insufficient_evidence?: boolean;
};

export type Verdict = {
  root_cause: string;
  root_cause_determined: boolean;
  summary?: string;
  supporting_evidence?: string[];
  failure_chain?: Array<{ step: string; evidence_ids: string[] }>;
  rejected_hypotheses?: Array<{ hypothesis: string; reason: string; evidence_ids?: string[] }>;
  confidence?: string;
  confidence_reason?: string;
  confidence_factors?: Record<string, unknown>;
  confidence_method?: string;
  missing_evidence?: string[];
  suggested_next_action?: string | null;
  suggested_fix?: string | null;
  reported_confidence?: string;
  validated?: boolean;
  [key: string]: unknown;
};

export type VerdictResponse = {
  case_id: string;
  status: string;
  verdict: Verdict;
  decision?: Record<string, unknown> | null;
  error?: string | null;
};

export type CaseDetail = {
  case_id: string;
  created_at?: string;
  updated_at?: string;
  schema_version?: number;
  capture_source?: string;
  page_url?: string;
  incident_description?: string | null;
  status: string;
  stage: string;
  transport?: string;
  evidence: EvidenceItem[];
  evidence_count: number;
  warnings?: string[];
  timeline?: Timeline;
  verdict?: Verdict | null;
  decision?: Record<string, unknown> | null;
  error?: string | null;
};

export type EventsResponse = {
  case_id: string;
  status: string;
  stage: string;
  count: number;
  events: CaseEvent[];
  messages: AgentMessage[];
};

export type Decision = "approve" | "reject" | "need_more_evidence";
