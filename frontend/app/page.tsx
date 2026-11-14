"use client";

import { useMemo, useState } from "react";

import { OpeningRow } from "@/components/OpeningRow";
import { Badge, Button, Card, ExternalLink, Loadable, Note } from "@/components/ui";
import { api, type Facility, type Notice, type Opening, type StatusChange, type SyncResult, type SystemStatus } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtRelative, fmtTime } from "@/lib/format";
import { groupOpenings } from "@/lib/openings";
import { useApi } from "@/lib/useApi";
import { useNow } from "@/lib/useNow";

const REFRESH = 60000;

export default function DashboardPage() {
  const now = useNow();
  const status = useApi<SystemStatus>("/status", REFRESH);
  const facilities = useApi<Facility[]>("/facilities?watched=true", REFRESH);
  const notices = useApi<Notice[]>("/notices?watched=true", REFRESH);
  const openings = useApi<Opening[]>("/openings?days=14", REFRESH);
  const reopenings = useApi<StatusChange[]>("/changes?kind=REOPENED&limit=10", REFRESH);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  const facilityById = useMemo(() => new Map((facilities.data ?? []).map((f) => [f.id, f])), [facilities.data]);
  const noticeById = useMemo(() => new Map((notices.data ?? []).map((n) => [n.id, n])), [notices.data]);

  async function syncNow() {
    setSyncing(true);
    setSyncNote(null);
    try {
      const results = await api<SyncResult[]>("/sync", { method: "POST" });
      const problem = results.find((r) => !r.ok);
      setSyncNote(
        problem ? `수집 실패: ${problem.skipped ?? problem.error ?? "알 수 없는 오류"}` : `수집 완료 (공고 ${results[0]?.seen ?? 0}건 확인)`,
      );
    } catch (e) {
      setSyncNote(`수집 실패: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSyncing(false);
      for (const source of [status, facilities, notices, openings, reopenings]) void source.reload();
    }
  }

  return (
    <div className="space-y-4">
      <Card
        title="수집 상태"
        action={
          <Button onClick={syncNow} disabled={syncing}>
            {syncing ? "수집 중…" : "지금 수집"}
          </Button>
        }
      >
        <Loadable state={status}>
          {(s) => {
            const site = s.sites[0];
            const failures = s.recent_logs.filter((log) => log.success === false).slice(0, 3);
            return (
              <div className="space-y-3">
                {s.paused_reason && (
                  <Note tone="bad">수집이 멈춰 있습니다: {s.paused_reason}. 시스템 화면에서 다시 켤 수 있습니다.</Note>
                )}
                <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                  <div>
                    <dt className="text-stone-500 dark:text-stone-400">마지막 정상 수집</dt>
                    <dd className="mt-0.5 font-medium">
                      {site?.last_success_at ? (
                        <>
                          {fmtRelative(site.last_success_at, now)}
                          <span className="ml-1 font-normal text-stone-500">({fmtTime(site.last_success_at)})</span>
                        </>
                      ) : (
                        "아직 없음"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-stone-500 dark:text-stone-400">연속 실패</dt>
                    <dd className="mt-0.5">
                      <Badge tone={site?.consecutive_failures ? "bad" : "good"}>
                        {site?.consecutive_failures ? `${site.consecutive_failures}회` : "없음"}
                      </Badge>
                    </dd>
                  </div>
                  <div className="col-span-2 sm:col-span-1">
                    <dt className="text-stone-500 dark:text-stone-400">관심 시설</dt>
                    <dd className="mt-0.5 font-medium">{facilities.data?.map((f) => f.name).join(", ") || "없음"}</dd>
                  </div>
                </dl>
                {syncNote && <Note tone={syncNote.startsWith("수집 실패") ? "bad" : "good"}>{syncNote}</Note>}
                {failures.length > 0 && (
                  <ul className="space-y-1 text-xs text-stone-600 dark:text-stone-400">
                    {failures.map((log) => (
                      <li key={log.id}>
                        <span className="tabular-nums">{fmtDateTime(log.started_at)}</span> · {log.error_type}:{" "}
                        {log.error_message}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          }}
        </Loadable>
      </Card>

      <Card title="예약 오픈 예정" hint="앞으로 14일. 같은 시각에 열리는 공고는 한 줄로 묶었습니다.">
        <Loadable state={openings} empty="예정된 오픈이 없습니다. 시스템 화면에서 오픈 규칙을 등록할 수 있습니다.">
          {(list) => (
            <ul className="divide-y divide-stone-200 dark:divide-stone-800">
              {groupOpenings(list)
                .slice(0, 8)
                .map((group) => (
                  <OpeningRow
                    key={group.key}
                    group={group}
                    facility={facilityById.get(group.facility_id)}
                    notices={noticeById}
                    now={now}
                  />
                ))}
            </ul>
          )}
        </Loadable>
      </Card>

      <Card
        title="지금 접수중인 공고"
        hint="공고 단위 상태입니다. 날짜·시간대별 빈자리는 사이트가 자동 조회를 막고 있어 예약 사이트에서 확인해야 합니다."
      >
        <Loadable state={notices}>
          {(list) => {
            const open = list.filter((n) => n.status === "AVAILABLE");
            if (open.length === 0) return <p className="text-sm text-stone-500">접수중인 공고가 없습니다.</p>;
            const byFacility = new Map<number, Notice[]>();
            for (const notice of open) {
              const key = notice.facility_id ?? 0;
              byFacility.set(key, [...(byFacility.get(key) ?? []), notice]);
            }
            return (
              <div className="space-y-4">
                {[...byFacility.entries()].map(([facilityId, items]) => (
                  <div key={facilityId}>
                    <h3 className="mb-1.5 text-sm font-semibold">{facilityById.get(facilityId)?.name ?? items[0].place_name}</h3>
                    <ul className="divide-y divide-stone-200 dark:divide-stone-800">
                      {items
                        .sort((a, b) => a.title.localeCompare(b.title, "ko"))
                        .map((notice) => (
                          <li key={notice.id} className="flex items-center justify-between gap-3 py-2">
                            <div className="min-w-0">
                              <p className="text-sm">{notice.title}</p>
                              <p className="text-xs text-stone-500 dark:text-stone-400">
                                {notice.open_days_before !== null
                                  ? `이용일 ${notice.open_days_before}일 전 ${notice.open_hour}시 오픈`
                                  : `이용 ${fmtDate(notice.use_start_date)} ~ ${fmtDate(notice.use_end_date)}`}
                                {notice.last_checked_at && ` · 확인 ${fmtRelative(notice.last_checked_at, now)}`}
                              </p>
                            </div>
                            {notice.detail_url && <ExternalLink href={notice.detail_url}>예약</ExternalLink>}
                          </li>
                        ))}
                    </ul>
                  </div>
                ))}
              </div>
            );
          }}
        </Loadable>
      </Card>

      <Card title="최근 접수 재개" hint="예약마감이던 공고가 다시 접수중으로 바뀐 기록입니다.">
        <Loadable state={reopenings} empty="아직 기록이 없습니다.">
          {(list) => (
            <ul className="divide-y divide-stone-200 dark:divide-stone-800">
              {list.map((change) => (
                <li key={change.id} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <p className="text-sm">{change.notice.title}</p>
                    <p className="text-xs text-stone-500 dark:text-stone-400">
                      {fmtDateTime(change.changed_at)} · {change.old_raw_status} → {change.new_raw_status}
                      {!change.notifiable && " · 알림 제외"}
                    </p>
                  </div>
                  {change.notice.detail_url && <ExternalLink href={change.notice.detail_url}>예약</ExternalLink>}
                </li>
              ))}
            </ul>
          )}
        </Loadable>
      </Card>
    </div>
  );
}
