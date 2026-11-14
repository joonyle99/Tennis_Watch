// 화면의 모든 시각은 한국시간으로 표시한다. 서버는 UTC로 준다.
import type { RuleType, SlotStatus, Verification } from "./api";

const TZ = "Asia/Seoul";
export const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];

const partsFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
}); // prettier-ignore

function parts(value: string | Date) {
  const map: Record<string, string> = {};
  for (const part of partsFormat.formatToParts(typeof value === "string" ? new Date(value) : value)) {
    map[part.type] = part.value;
  }
  return map;
}

/** 한국 기준 날짜 키 (YYYY-MM-DD) */
export function kstDateKey(value: string | Date): string {
  const p = parts(value);
  return `${p.year}-${p.month}-${p.day}`;
}

export function todayKey(): string {
  return kstDateKey(new Date());
}

/** 월요일 0 ~ 일요일 6 */
export function weekdayOf(dateKey: string): number {
  const [y, m, d] = dateKey.split("-").map(Number);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

export function addDays(dateKey: string, days: number): string {
  const [y, m, d] = dateKey.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

export function fmtDate(dateKey: string | null): string {
  if (!dateKey) return "-";
  const [, m, d] = dateKey.split("-").map(Number);
  return `${m}월 ${d}일 (${WEEKDAYS[weekdayOf(dateKey)]})`;
}

export function fmtTime(value: string | null): string {
  if (!value) return "-";
  if (/^\d{2}:\d{2}/.test(value)) return value.slice(0, 5); // "14:00:00" 같은 시각 값
  const p = parts(value);
  return `${p.hour}:${p.minute}`;
}

export function fmtDateTime(value: string | null): string {
  if (!value) return "-";
  return `${fmtDate(kstDateKey(value))} ${fmtTime(value)}`;
}

/** "3시간 후", "5분 전" */
export function fmtRelative(value: string | null, now: number = Date.now()): string {
  if (!value) return "-";
  const diff = new Date(value).getTime() - now;
  const minutes = Math.round(Math.abs(diff) / 60000);
  const suffix = diff >= 0 ? "후" : "전";
  if (minutes < 1) return "방금";
  if (minutes < 60) return `${minutes}분 ${suffix}`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}시간 ${minutes % 60 ? `${minutes % 60}분 ` : ""}${suffix}`;
  return `${Math.floor(minutes / 1440)}일 ${suffix}`;
}

export function fmtOffset(minutes: number): string {
  if (minutes % 1440 === 0) return `${minutes / 1440}일 전`;
  if (minutes % 60 === 0) return `${minutes / 60}시간 전`;
  return `${minutes}분 전`;
}

export const STATUS_LABEL: Record<SlotStatus, string> = {
  AVAILABLE: "예약 가능",
  UNAVAILABLE: "예약 불가",
  NOT_OPEN: "접수 전",
  CLOSED: "운영 중단",
  UNKNOWN: "확인 불가",
};

export const STATUS_TONE: Record<SlotStatus, Tone> = {
  AVAILABLE: "good",
  UNAVAILABLE: "muted",
  NOT_OPEN: "info",
  CLOSED: "warn",
  UNKNOWN: "warn",
};

export type Tone = "good" | "info" | "warn" | "bad" | "muted";

export const RULE_LABEL: Record<RuleType, string> = {
  MONTHLY: "매월",
  DAYS_BEFORE_USE: "이용일 기준",
  ONE_TIME: "1회",
  NOTICE: "공고",
};

export const VERIFICATION_LABEL: Record<Verification, string> = {
  VERIFIED: "검증됨",
  INFERRED: "추정",
  UNVERIFIED: "미확인",
  CONFLICT: "충돌",
};

export const VERIFICATION_TONE: Record<Verification, Tone> = {
  VERIFIED: "good",
  INFERRED: "info",
  UNVERIFIED: "muted",
  CONFLICT: "bad",
};
