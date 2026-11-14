"use client";

import { useMemo, useState, type FormEvent } from "react";

import { OpeningRow } from "@/components/OpeningRow";
import { Badge, Button, Card, ExternalLink, Field, inputBase, inputClass, Loadable, Note } from "@/components/ui";
import { api, query, type Facility, type Notice, type Opening, type Slot, type SlotStatus } from "@/lib/api";
import { addDays, fmtDate, fmtDateTime, fmtTime, kstDateKey, STATUS_LABEL, STATUS_TONE, todayKey, WEEKDAYS, weekdayOf } from "@/lib/format";
import { groupOpenings } from "@/lib/openings";
import { useApi } from "@/lib/useApi";
import { useNow } from "@/lib/useNow";

function monthDays(month: string): string[] {
  const [y, m] = month.split("-").map(Number);
  const count = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return Array.from({ length: count }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`);
}

function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1 + delta, 1)).toISOString().slice(0, 7);
}

/** 롤링 오픈 공고에서 dateKey 이용분이 열리는 시각 (UTC ms). 한국시간은 UTC+9로 고정이다. */
function rollingOpenMs(dateKey: string, daysBefore: number, hour: number): number {
  const [y, m, d] = dateKey.split("-").map(Number);
  return Date.UTC(y, m - 1, d - daysBefore, hour - 9);
}

const DOT = { open: "bg-sky-500", bookable: "bg-emerald-500", memo: "bg-stone-400" };

type DayState = "open" | "later" | "closed" | "none";

/** 그 날짜에 이 공고로 예약할 수 있는지. 공고 단위 판단이며 실제 빈자리 여부는 알 수 없다. */
function noticeOnDate(notice: Notice, dateKey: string, now: number): { state: DayState; opensAt?: number } {
  if (!notice.use_start_date || !notice.use_end_date) return { state: "none" };
  if (dateKey < notice.use_start_date || dateKey > notice.use_end_date) return { state: "none" };
  const weekday = weekdayOf(dateKey);
  if (notice.day_type === "WEEKDAY" && weekday > 4) return { state: "none" };
  if (notice.day_type === "WEEKEND" && weekday < 5) return { state: "none" };
  if (notice.status !== "AVAILABLE") return { state: "closed" };
  if (notice.open_days_before !== null && notice.open_hour !== null) {
    const opensAt = rollingOpenMs(dateKey, notice.open_days_before, notice.open_hour);
    if (opensAt > now) return { state: "later", opensAt };
  }
  return { state: "open" };
}

export default function CalendarPage() {
  const now = useNow();
  const today = todayKey();
  const [month, setMonth] = useState(today.slice(0, 7));
  const [selected, setSelected] = useState(today);
  const [facilityId, setFacilityId] = useState<number | "all">("all");
  const [courtId, setCourtId] = useState<number | "all">("all");

  const days = useMemo(() => monthDays(month), [month]);
  const facilities = useApi<Facility[]>("/facilities?watched=true");
  const notices = useApi<Notice[]>("/notices?watched=true");
  const openings = useApi<Opening[]>(`/openings${query({ start: days[0], days: days.length })}`);
  const slots = useApi<Slot[]>(`/slots${query({ date_from: days[0], date_to: days[days.length - 1] })}`);

  const facilityById = useMemo(() => new Map((facilities.data ?? []).map((f) => [f.id, f])), [facilities.data]);
  const noticeById = useMemo(() => new Map((notices.data ?? []).map((n) => [n.id, n])), [notices.data]);
  const courts = facilityId === "all" ? [] : (facilityById.get(facilityId)?.courts ?? []);

  const matches = (item: { facility_id: number | null; court_id: number | null }) =>
    (facilityId === "all" || item.facility_id === facilityId) && (courtId === "all" || item.court_id === courtId);

  const shownNotices = (notices.data ?? []).filter(matches);
  const shownOpenings = (openings.data ?? []).filter(matches);
  const shownSlots = (slots.data ?? []).filter(matches);

  const openingGroupsByDay = useMemo(() => {
    const map = new Map<string, ReturnType<typeof groupOpenings>>();
    for (const group of groupOpenings(shownOpenings)) {
      const key = kstDateKey(group.opens_at);
      map.set(key, [...(map.get(key) ?? []), group]);
    }
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openings.data, facilityId, courtId]);

  const leading = weekdayOf(days[0]);
  const dayNotices = shownNotices
    .map((notice) => ({ notice, ...noticeOnDate(notice, selected, now) }))
    .filter((entry) => entry.state !== "none")
    .sort((a, b) => a.notice.title.localeCompare(b.notice.title, "ko"));
  const daySlots = shownSlots.filter((slot) => slot.use_date === selected);
  const dayOpenings = openingGroupsByDay.get(selected) ?? [];

  function pickDay(day: string) {
    setSelected(day);
  }

  function moveMonth(delta: number) {
    const next = shiftMonth(month, delta);
    setMonth(next);
    setSelected(next === today.slice(0, 7) ? today : `${next}-01`);
  }

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex items-center gap-1">
            <Button onClick={() => moveMonth(-1)} aria-label="이전 달">‹</Button>
            <h1 className="w-28 text-center text-lg font-bold tabular-nums">
              {month.slice(0, 4)}년 {Number(month.slice(5))}월
            </h1>
            <Button onClick={() => moveMonth(1)} aria-label="다음 달">›</Button>
            <Button onClick={() => { setMonth(today.slice(0, 7)); setSelected(today); }}>오늘</Button>
          </div>
          <div className="flex basis-full gap-2 sm:basis-auto sm:flex-1">
            <select
              aria-label="시설"
              className={`${inputBase} min-w-0 flex-1 sm:w-56 sm:flex-none`}
              value={facilityId}
              onChange={(e) => { setFacilityId(e.target.value === "all" ? "all" : Number(e.target.value)); setCourtId("all"); }}
            >
              <option value="all">관심 시설 전체</option>
              {(facilities.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            {courts.length > 0 && (
              <select
                aria-label="코트"
                className={`${inputBase} min-w-0 flex-1 sm:w-36 sm:flex-none`}
                value={courtId}
                onChange={(e) => setCourtId(e.target.value === "all" ? "all" : Number(e.target.value))}
              >
                <option value="all">코트 전체</option>
                {courts.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-7 gap-1 text-center text-xs font-medium text-stone-500 dark:text-stone-400">
          {WEEKDAYS.map((name, i) => (
            <div key={name} className={i === 5 ? "text-sky-700 dark:text-sky-400" : i === 6 ? "text-rose-700 dark:text-rose-400" : ""}>{name}</div>
          ))}
        </div>
        <div className="mt-1 grid grid-cols-7 gap-1">
          {Array.from({ length: leading }, (_, i) => <div key={`blank-${i}`} />)}
          {days.map((day) => {
            const opens = openingGroupsByDay.get(day)?.length ?? 0;
            const states = shownNotices.map((n) => noticeOnDate(n, day, now).state);
            const bookable = day >= today && states.includes("open");
            const manual = shownSlots.filter((s) => s.use_date === day && s.manual_status).length;
            const isSelected = day === selected;
            return (
              <button
                key={day}
                type="button"
                onClick={() => pickDay(day)}
                aria-pressed={isSelected}
                aria-label={`${fmtDate(day)}${opens ? `, 오픈 ${opens}건` : ""}${bookable ? ", 접수중 공고 있음" : ""}`}
                className={`flex min-h-12 flex-col items-stretch rounded-lg border p-1 text-left transition-colors sm:min-h-20 sm:p-1.5 ${
                  isSelected
                    ? "border-emerald-700 bg-emerald-50 dark:bg-emerald-950"
                    : "border-stone-200 hover:bg-stone-50 dark:border-stone-800 dark:hover:bg-stone-800"
                } ${day < today ? "opacity-50" : ""}`}
              >
                <span className={`text-sm tabular-nums ${day === today ? "font-bold text-emerald-700 dark:text-emerald-400" : ""}`}>
                  {Number(day.slice(8))}
                </span>
                {/* 좁은 화면에서는 점으로, 넓은 화면에서는 글자로 표시한다. 뜻은 aria-label과 범례에 있다. */}
                <span className="mt-auto flex gap-1 sm:hidden">
                  {opens > 0 && <span className={`h-2 w-2 rounded-full ${DOT.open}`} />}
                  {bookable && <span className={`h-2 w-2 rounded-full ${DOT.bookable}`} />}
                  {manual > 0 && <span className={`h-2 w-2 rounded-full ${DOT.memo}`} />}
                </span>
                <span className="mt-auto hidden flex-col gap-0.5 text-xs leading-tight whitespace-nowrap sm:flex">
                  {opens > 0 && <span className="rounded bg-sky-100 px-1 text-sky-800 dark:bg-sky-950 dark:text-sky-300">오픈 {opens}</span>}
                  {bookable && <span className="rounded bg-emerald-100 px-1 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">접수중</span>}
                  {manual > 0 && <span className="rounded bg-stone-200 px-1 text-stone-700 dark:bg-stone-800 dark:text-stone-300">메모 {manual}</span>}
                </span>
              </button>
            );
          })}
        </div>
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500 dark:text-stone-400">
          <li className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${DOT.open}`} />오픈: 그날 예약이 열림</li>
          <li className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${DOT.bookable}`} />접수중: 그날 이용분 공고가 접수중</li>
          <li className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${DOT.memo}`} />메모: 직접 적은 시간대</li>
        </ul>
      </Card>

      <Card title={`${fmtDate(selected)} 에 열리는 예약`}>
        <Loadable state={openings}>
          {() =>
            dayOpenings.length === 0 ? (
              <p className="text-sm text-stone-500">이 날 열리는 예약이 없습니다.</p>
            ) : (
              <ul className="divide-y divide-stone-200 dark:divide-stone-800">
                {dayOpenings.map((group) => (
                  <OpeningRow key={group.key} group={group} facility={facilityById.get(group.facility_id)} notices={noticeById} now={now} />
                ))}
              </ul>
            )
          }
        </Loadable>
      </Card>

      <Card
        title={`${fmtDate(selected)} 이용분 공고`}
        hint="공고 단위 상태입니다. 시간대별 빈자리는 예약 사이트에서 확인하세요. 공휴일은 구분하지 못합니다."
      >
        <Loadable state={notices}>
          {() =>
            dayNotices.length === 0 ? (
              <p className="text-sm text-stone-500">이 날 이용분을 다루는 공고가 없습니다.</p>
            ) : (
              <ul className="divide-y divide-stone-200 dark:divide-stone-800">
                {dayNotices.map(({ notice, state, opensAt }) => (
                  <li key={notice.id} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        {selected < today ? (
                          <Badge>지난 날짜</Badge>
                        ) : state === "open" ? (
                          <Badge tone="good">접수중</Badge>
                        ) : state === "later" ? (
                          <Badge tone="info">접수 전</Badge>
                        ) : (
                          <Badge tone={STATUS_TONE[notice.status]}>{notice.raw_status ?? STATUS_LABEL[notice.status]}</Badge>
                        )}
                        <span className="text-sm">{notice.title}</span>
                      </div>
                      <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">
                        {facilityById.get(notice.facility_id ?? 0)?.name}
                        {notice.daily_open_time && ` · 운영 ${fmtTime(notice.daily_open_time)}~${fmtTime(notice.daily_close_time)}`}
                        {state === "later" && opensAt && ` · ${fmtDateTime(new Date(opensAt).toISOString())} 오픈`}
                      </p>
                    </div>
                    {notice.detail_url && <ExternalLink href={notice.detail_url}>예약</ExternalLink>}
                  </li>
                ))}
              </ul>
            )
          }
        </Loadable>
      </Card>

      <Card title="직접 확인한 시간대" hint="예약 사이트에서 본 빈 시간을 적어 두는 메모입니다. 자동 수집값과 따로 저장되며 알림에는 쓰이지 않습니다.">
        <ul className="mb-4 divide-y divide-stone-200 dark:divide-stone-800">
          {daySlots.filter((s) => s.manual_status).length === 0 && <li className="text-sm text-stone-500">적어 둔 시간대가 없습니다.</li>}
          {daySlots.filter((s) => s.manual_status).map((slot) => {
            const facility = facilityById.get(slot.facility_id);
            return (
              <li key={slot.id} className="flex items-center justify-between gap-3 py-2 first:pt-0">
                <div className="min-w-0 text-sm">
                  <span className="font-medium tabular-nums">{fmtTime(slot.start_time)}~{fmtTime(slot.end_time)}</span>{" "}
                  <Badge tone={STATUS_TONE[slot.manual_status!]}>{STATUS_LABEL[slot.manual_status!]}</Badge>
                  {slot.has_conflict && <> <Badge tone="bad">자동 확인값과 다름</Badge></>}
                  <p className="text-xs text-stone-500 dark:text-stone-400">
                    {facility?.name}
                    {slot.court_id && ` · ${facility?.courts.find((c) => c.id === slot.court_id)?.name ?? ""}`}
                    {slot.manual_note && ` · ${slot.manual_note}`}
                    {slot.manual_updated_at && ` · ${fmtDateTime(slot.manual_updated_at)} 기록`}
                  </p>
                </div>
                <Button
                  variant="danger"
                  onClick={async () => {
                    await api("/slots/manual", { method: "PUT", body: { facility_id: slot.facility_id, court_id: slot.court_id, use_date: slot.use_date, start_time: slot.start_time, end_time: slot.end_time, status: null } });
                    void slots.reload();
                  }}
                >
                  지우기
                </Button>
              </li>
            );
          })}
        </ul>
        <SlotForm
          key={`${selected}-${facilityId}`}
          date={selected}
          facilities={facilities.data ?? []}
          defaultFacilityId={facilityId === "all" ? undefined : facilityId}
          onSaved={() => void slots.reload()}
        />
      </Card>
    </div>
  );
}

function SlotForm({
  date,
  facilities,
  defaultFacilityId,
  onSaved,
}: {
  date: string;
  facilities: Facility[];
  defaultFacilityId?: number;
  onSaved: () => void;
}) {
  const [facilityId, setFacilityId] = useState<number | "">(defaultFacilityId ?? facilities[0]?.id ?? "");
  const [courtId, setCourtId] = useState<number | "">("");
  const [start, setStart] = useState("18:00");
  const [end, setEnd] = useState("20:00");
  const [status, setStatus] = useState<SlotStatus>("AVAILABLE");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const effectiveFacility = facilityId === "" ? (facilities[0]?.id ?? "") : facilityId;
  const courts = facilities.find((f) => f.id === effectiveFacility)?.courts ?? [];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/slots/manual", {
        method: "PUT",
        body: { facility_id: effectiveFacility, court_id: courtId === "" ? null : courtId, use_date: date, start_time: start, end_time: end, status, note: note || null },
      });
      setNote("");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장하지 못했습니다");
    }
  }

  if (facilities.length === 0) return <Note>관심 시설을 먼저 등록하세요.</Note>;
  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-3 sm:grid-cols-6">
      <div className="col-span-2">
        <Field label="시설">
          <select className={inputClass} value={effectiveFacility} onChange={(e) => { setFacilityId(Number(e.target.value)); setCourtId(""); }}>
            {facilities.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </Field>
      </div>
      <Field label="코트">
        <select className={inputClass} value={courtId} onChange={(e) => setCourtId(e.target.value === "" ? "" : Number(e.target.value))}>
          <option value="">전체</option>
          {courts.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </Field>
      <Field label="상태">
        <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as SlotStatus)}>
          <option value="AVAILABLE">예약 가능</option>
          <option value="UNAVAILABLE">예약 불가</option>
          <option value="CLOSED">운영 중단</option>
        </select>
      </Field>
      <Field label="시작"><input type="time" required className={inputClass} value={start} onChange={(e) => setStart(e.target.value)} /></Field>
      <Field label="종료"><input type="time" required className={inputClass} value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      <div className="col-span-2 sm:col-span-5">
        <Field label="메모"><input className={inputClass} value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="선택" /></Field>
      </div>
      <div className="col-span-2 flex items-end sm:col-span-1">
        <Button type="submit" variant="primary" className="w-full">{fmtDate(date).split(" (")[0]} 기록</Button>
      </div>
      {error && <div className="col-span-2 sm:col-span-6"><Note tone="bad">{error}</Note></div>}
    </form>
  );
}
