"use client";

import type { Facility, Notice } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtRelative, VERIFICATION_LABEL } from "@/lib/format";
import { groupUseRange, type OpeningGroup } from "@/lib/openings";

import { Badge, ExternalLink } from "./ui";

export function OpeningRow({
  group,
  facility,
  notices,
  now,
}: {
  group: OpeningGroup;
  facility: Facility | undefined;
  notices: Map<number, Notice>;
  now: number;
}) {
  const range = groupUseRange(group);
  const targets = [...new Set(group.items.map((o) => o.description).filter(Boolean))] as string[];
  const flags = new Set(group.items.map((o) => o.verification_status));
  const noticeIds = [...new Set(group.items.map((o) => o.notice_id).filter((id) => id !== null))] as number[];
  // 공고가 하나면 그 공고로, 여럿이면 시설의 예약 페이지로 보낸다.
  const url =
    (noticeIds.length === 1 ? notices.get(noticeIds[0])?.detail_url : null) ??
    facility?.booking_url ??
    (noticeIds.length ? notices.get(noticeIds[0])?.detail_url : null);
  const past = new Date(group.opens_at).getTime() < now;

  return (
    <li className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold tabular-nums">{fmtDateTime(group.opens_at)}</span>
          <Badge tone={past ? "muted" : "info"}>{fmtRelative(group.opens_at, now)}</Badge>
          {flags.has("INFERRED") && <Badge tone="info">{VERIFICATION_LABEL.INFERRED}</Badge>}
          {flags.has("CONFLICT") && <Badge tone="bad">{VERIFICATION_LABEL.CONFLICT}</Badge>}
        </div>
        <p className="mt-1 text-sm">{facility?.name ?? "알 수 없는 시설"}</p>
        <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">
          {range &&
            (range.start === range.end
              ? `이용일 ${fmtDate(range.start)}`
              : `이용일 ${fmtDate(range.start)} ~ ${fmtDate(range.end)}`)}
          {range && targets.length > 0 && " · "}
          {targets.length === 1 ? targets[0] : targets.length > 1 ? `${targets.length}개 공고` : ""}
        </p>
      </div>
      {url && <ExternalLink href={url}>예약 사이트</ExternalLink>}
    </li>
  );
}
