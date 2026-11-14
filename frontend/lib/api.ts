export type SlotStatus = "AVAILABLE" | "UNAVAILABLE" | "NOT_OPEN" | "CLOSED" | "UNKNOWN";
export type RuleType = "MONTHLY" | "DAYS_BEFORE_USE" | "ONE_TIME" | "NOTICE";
export type Verification = "VERIFIED" | "INFERRED" | "UNVERIFIED" | "CONFLICT";
export type DataSource = "AUTO" | "MANUAL";

export interface Court {
  id: number;
  facility_id: number;
  name: string;
  source: DataSource;
  verified: boolean;
  is_watched: boolean;
  memo: string | null;
}

export interface Facility {
  id: number;
  name: string;
  external_name: string | null;
  area: string | null;
  phone: string | null;
  booking_url: string | null;
  memo: string | null;
  source: DataSource;
  locked_fields: string[];
  is_watched: boolean;
  courts: Court[];
}

export interface Notice {
  id: number;
  facility_id: number | null;
  court_id: number | null;
  external_id: string;
  title: string;
  place_name: string | null;
  area: string | null;
  detail_url: string | null;
  status: SlotStatus;
  raw_status: string | null;
  reception_start_at: string | null;
  reception_end_at: string | null;
  use_start_date: string | null;
  use_end_date: string | null;
  daily_open_time: string | null;
  daily_close_time: string | null;
  open_days_before: number | null;
  open_hour: number | null;
  day_type: "WEEKDAY" | "WEEKEND" | "UNKNOWN";
  time_band: "DAY" | "NIGHT" | "UNKNOWN";
  is_active: boolean;
  last_checked_at: string | null;
  status_changed_at: string | null;
}

export interface Opening {
  rule_id: number;
  facility_id: number;
  court_id: number | null;
  notice_id: number | null;
  rule_type: RuleType;
  source: DataSource;
  verification_status: Verification;
  opens_at: string;
  use_start: string | null;
  use_end: string | null;
  description: string | null;
}

export interface OpeningRule {
  id: number;
  facility_id: number;
  court_id: number | null;
  notice_id: number | null;
  rule_type: RuleType;
  source: DataSource;
  day_of_month: number | null;
  days_before: number | null;
  open_time: string | null;
  opens_at: string | null;
  target_description: string | null;
  verification_status: Verification;
  last_verified_at: string | null;
  note: string | null;
  is_active: boolean;
}

export interface StatusChange {
  id: number;
  notice: { id: number; facility_id: number | null; title: string; place_name: string | null; detail_url: string | null };
  old_raw_status: string | null;
  new_raw_status: string | null;
  kind: "INITIAL" | "OPENED" | "REOPENED" | "OTHER";
  notifiable: boolean;
  changed_at: string;
}

export interface WatchRule {
  id: number;
  facility_id: number;
  name: string | null;
  court_id: number | null;
  date_from: string | null;
  date_to: string | null;
  weekdays: number[];
  time_from: string | null;
  time_to: string | null;
  min_consecutive_hours: number | null;
  notify_opening: boolean;
  notify_vacancy: boolean;
  enabled: boolean;
}

export interface Slot {
  id: number;
  facility_id: number;
  court_id: number | null;
  use_date: string;
  start_time: string;
  end_time: string;
  auto_status: SlotStatus;
  manual_status: SlotStatus | null;
  manual_updated_at: string | null;
  manual_note: string | null;
  has_conflict: boolean;
}

export interface CrawlLog {
  id: number;
  job: string;
  started_at: string;
  finished_at: string | null;
  success: boolean | null;
  item_count: number | null;
  error_type: string | null;
  error_message: string | null;
}

export interface SystemStatus {
  paused_reason: string | null;
  sites: {
    site: { id: number; name: string };
    last_success_at: string | null;
    consecutive_failures: number;
    backoff_until: string | null;
  }[];
  recent_logs: CrawlLog[];
}

export interface SyncResult {
  job: string;
  ok: boolean;
  source: string | null;
  seen: number;
  created: number;
  changed: number;
  error: string | null;
  skipped: string | null;
}

export interface NotificationEvent {
  id: number;
  type: "OPENING_SOON" | "OPENED" | "REOPENED" | "SYSTEM_ERROR";
  status: "PENDING" | "SENT" | "FAILED" | "SKIPPED";
  message: string;
  last_error: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface AppSettings {
  sync_interval_minutes: number;
  opening_alert_offsets_minutes: number[];
  notifications_enabled: boolean;
  failure_threshold: number;
  [key: string]: unknown;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function describe(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d?.msg === "string" ? d.msg : JSON.stringify(d))).join(" / ");
  }
  return `요청이 실패했습니다 (${status})`;
}

export async function api<T = void>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: init?.method ?? "GET",
      headers: init?.body === undefined ? undefined : { "content-type": "application/json" },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError("서버에 연결할 수 없습니다", 0);
  }
  if (response.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
    window.location.href = "/login";
    throw new ApiError("로그인이 필요합니다", 401);
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(describe(data?.detail, response.status), response.status);
  return data as T;
}

export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
