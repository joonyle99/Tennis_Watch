"use client";

import { useMemo, useState, type FormEvent } from "react";

import { Badge, Button, Card, ExternalLink, Field, inputBase, inputClass, Loadable, Note, Toggle } from "@/components/ui";
import { api, type Court, type Facility, type WatchRule } from "@/lib/api";
import { fmtDate, fmtTime, WEEKDAYS } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function WatchPage() {
  const facilities = useApi<Facility[]>("/facilities");
  const rules = useApi<WatchRule[]>("/watch-rules");
  const [search, setSearch] = useState("");
  const [area, setArea] = useState("");
  const [watchedOnly, setWatchedOnly] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const areas = useMemo(
    () => [...new Set((facilities.data ?? []).map((f) => f.area).filter(Boolean) as string[])].sort((a, b) => a.localeCompare(b, "ko")),
    [facilities.data],
  );

  async function act(work: () => Promise<unknown>) {
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장하지 못했습니다");
    } finally {
      void facilities.reload();
      void rules.reload();
    }
  }

  return (
    <div className="space-y-4">
      <Card title="테니스장" hint="관심 시설로 켠 곳만 오픈 일정과 알림 대상이 됩니다.">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            type="search"
            aria-label="시설명 검색"
            placeholder="시설명 검색"
            className={`${inputBase} min-w-0 flex-1 basis-40`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select aria-label="지역" className={`${inputBase} w-32`} value={area} onChange={(e) => setArea(e.target.value)}>
            <option value="">전체 지역</option>
            {areas.map((name) => <option key={name}>{name}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm">
            <Toggle checked={watchedOnly} onChange={setWatchedOnly} label="관심 시설만 보기" /> 관심만
          </label>
        </div>
        {error && <div className="mb-3"><Note tone="bad">{error}</Note></div>}
        <Loadable state={facilities} empty="아직 수집된 시설이 없습니다. 대시보드에서 '지금 수집'을 눌러 보세요.">
          {(list) => {
            const shown = list
              .filter((f) => (!watchedOnly || f.is_watched) && (!area || f.area === area) && f.name.includes(search.trim()))
              .sort((a, b) => Number(b.is_watched) - Number(a.is_watched) || a.name.localeCompare(b.name, "ko"));
            if (shown.length === 0) return <p className="text-sm text-stone-500">조건에 맞는 시설이 없습니다.</p>;
            return (
              <ul className="divide-y divide-stone-200 dark:divide-stone-800">
                {shown.map((facility) => (
                  <li key={facility.id} className="py-3 first:pt-0 last:pb-0">
                    <div className="flex items-center justify-between gap-3">
                      <button type="button" className="min-w-0 flex-1 text-left" aria-expanded={openId === facility.id} onClick={() => setOpenId(openId === facility.id ? null : facility.id)}>
                        <span className="font-medium">{facility.name}</span>
                        <span className="ml-2 text-xs text-stone-500 dark:text-stone-400">
                          {facility.area ?? "지역 미상"} · 코트 {facility.courts.length}
                          {facility.source === "MANUAL" && " · 수동 등록"}
                        </span>
                        <span className="ml-2 text-xs text-emerald-700 dark:text-emerald-400">{openId === facility.id ? "접기" : "자세히"}</span>
                      </button>
                      <Toggle
                        checked={facility.is_watched}
                        label={`${facility.name} 관심 시설`}
                        onChange={(next) => act(() => api(`/facilities/${facility.id}`, { method: "PATCH", body: { is_watched: next } }))}
                      />
                    </div>
                    {openId === facility.id && (
                      <FacilityDetail facility={facility} rules={(rules.data ?? []).filter((r) => r.facility_id === facility.id)} act={act} />
                    )}
                  </li>
                ))}
              </ul>
            );
          }}
        </Loadable>
      </Card>

      <Card title="시설 직접 등록" hint="서울시 공공서비스예약에 없는 시설을 추가합니다.">
        <ManualFacilityForm act={act} />
      </Card>
    </div>
  );
}

type Act = (work: () => Promise<unknown>) => Promise<void>;

function FacilityDetail({ facility, rules, act }: { facility: Facility; rules: WatchRule[]; act: Act }) {
  const [courtName, setCourtName] = useState("");
  const [bookingUrl, setBookingUrl] = useState(facility.booking_url ?? "");
  const [memo, setMemo] = useState(facility.memo ?? "");
  const courtName_ = (id: number | null) => facility.courts.find((c) => c.id === id)?.name;

  return (
    <div className="mt-3 space-y-4 rounded-lg bg-stone-50 p-3 dark:bg-stone-950">
      <div>
        <h3 className="mb-2 text-sm font-semibold">코트</h3>
        {facility.courts.length === 0 && <p className="mb-2 text-sm text-stone-500">등록된 코트가 없습니다.</p>}
        <ul className="space-y-1.5">
          {facility.courts.map((court: Court) => (
            <li key={court.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="flex min-w-0 flex-wrap items-center gap-2">
                {court.name}
                {court.verified ? (
                  <Badge tone="good">확인됨</Badge>
                ) : (
                  <button type="button" className="text-xs text-emerald-700 underline dark:text-emerald-400" onClick={() => act(() => api(`/courts/${court.id}`, { method: "PATCH", body: { verified: true } }))}>
                    공고명에서 추출 · 맞으면 확인
                  </button>
                )}
              </span>
              <span className="flex shrink-0 items-center gap-2 text-xs whitespace-nowrap text-stone-500">
                관심
                <Toggle checked={court.is_watched} label={`${court.name} 관심 코트`} onChange={(next) => act(() => api(`/courts/${court.id}`, { method: "PATCH", body: { is_watched: next } }))} />
              </span>
            </li>
          ))}
        </ul>
        <form
          className="mt-2 flex gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (!courtName.trim()) return;
            void act(() => api(`/facilities/${facility.id}/courts`, { method: "POST", body: { name: courtName.trim() } })).then(() => setCourtName(""));
          }}
        >
          <input aria-label="추가할 코트 이름" placeholder="코트 이름 (예: 2번코트)" className={inputClass} value={courtName} maxLength={100} onChange={(e) => setCourtName(e.target.value)} />
          <Button type="submit">추가</Button>
        </form>
      </div>

      <div>
        <h3 className="mb-1 text-sm font-semibold">관심 조건</h3>
        <p className="mb-2 text-xs text-stone-500 dark:text-stone-400">
          조건이 없으면 이 시설의 모든 공고를 알립니다. 조건이 있으면 그중 하나에 해당하는 공고만 알립니다.
        </p>
        <ul className="mb-3 space-y-2">
          {rules.map((rule) => (
            <li key={rule.id} className="flex items-start justify-between gap-2 rounded-lg border border-stone-200 bg-white p-2 text-sm dark:border-stone-800 dark:bg-stone-900">
              <div className="min-w-0">
                <p className="font-medium">{rule.name || "이름 없는 조건"} {!rule.enabled && <Badge>꺼짐</Badge>}</p>
                <p className="text-xs text-stone-500 dark:text-stone-400">
                  {[
                    rule.court_id ? courtName_(rule.court_id) : "모든 코트",
                    rule.weekdays.length ? rule.weekdays.map((d) => WEEKDAYS[d]).join("·") : "모든 요일",
                    rule.date_from || rule.date_to ? `${rule.date_from ? fmtDate(rule.date_from) : ""} ~ ${rule.date_to ? fmtDate(rule.date_to) : ""}` : null,
                    rule.time_from || rule.time_to ? `${fmtTime(rule.time_from)}~${fmtTime(rule.time_to)}` : null,
                    rule.min_consecutive_hours ? `연속 ${rule.min_consecutive_hours}시간 이상` : null,
                    [rule.notify_opening && "오픈 알림", rule.notify_vacancy && "접수 재개 알림"].filter(Boolean).join(" + ") || "알림 없음",
                  ].filter(Boolean).join(" · ")}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Toggle checked={rule.enabled} label="조건 사용" onChange={(next) => act(() => api(`/watch-rules/${rule.id}`, { method: "PUT", body: { ...rule, enabled: next } }))} />
                <Button variant="danger" onClick={() => act(() => api(`/watch-rules/${rule.id}`, { method: "DELETE" }))}>삭제</Button>
              </div>
            </li>
          ))}
        </ul>
        <WatchRuleForm facility={facility} act={act} />
      </div>

      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void act(() => api(`/facilities/${facility.id}`, { method: "PATCH", body: { booking_url: bookingUrl || null, memo: memo || null } }));
        }}
      >
        <Field label="예약 사이트 주소" hint="공고가 여러 개일 때 알림과 화면의 바로가기로 씁니다.">
          <input type="url" className={inputClass} value={bookingUrl} maxLength={500} onChange={(e) => setBookingUrl(e.target.value)} placeholder="https://" />
        </Field>
        <Field label="메모">
          <input className={inputClass} value={memo} onChange={(e) => setMemo(e.target.value)} />
        </Field>
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit">저장</Button>
          {facility.booking_url && <ExternalLink href={facility.booking_url}>예약 사이트 열기</ExternalLink>}
          {facility.source === "MANUAL" && (
            <Button variant="danger" onClick={() => confirm(`${facility.name}을(를) 삭제할까요? 코트와 관심 조건도 함께 삭제됩니다.`) && act(() => api(`/facilities/${facility.id}`, { method: "DELETE" }))}>
              시설 삭제
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}

function WatchRuleForm({ facility, act }: { facility: Facility; act: Act }) {
  const [name, setName] = useState("");
  const [courtId, setCourtId] = useState("");
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [timeFrom, setTimeFrom] = useState("");
  const [timeTo, setTimeTo] = useState("");
  const [minHours, setMinHours] = useState("");
  const [notifyOpening, setNotifyOpening] = useState(true);
  const [notifyVacancy, setNotifyVacancy] = useState(true);

  function submit(event: FormEvent) {
    event.preventDefault();
    void act(() =>
      api("/watch-rules", {
        method: "POST",
        body: {
          facility_id: facility.id, name: name || null, court_id: courtId ? Number(courtId) : null, weekdays,
          date_from: dateFrom || null, date_to: dateTo || null, time_from: timeFrom || null, time_to: timeTo || null,
          min_consecutive_hours: minHours ? Number(minHours) : null, notify_opening: notifyOpening, notify_vacancy: notifyVacancy,
        },
      }),
    ).then(() => { setName(""); setWeekdays([]); });
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-3 rounded-lg border border-dashed border-stone-300 p-3 sm:grid-cols-4 dark:border-stone-700">
      <div className="col-span-2"><Field label="조건 이름"><input className={inputClass} value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="예: 토요일 저녁" /></Field></div>
      <div className="col-span-2">
        <Field label="코트">
          <select className={inputClass} value={courtId} onChange={(e) => setCourtId(e.target.value)}>
            <option value="">모든 코트</option>
            {facility.courts.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
      </div>
      <fieldset className="col-span-2 sm:col-span-4">
        <legend className="mb-1 text-sm font-medium text-stone-700 dark:text-stone-300">요일 (선택하지 않으면 모든 요일)</legend>
        <div className="flex flex-wrap gap-1.5">
          {WEEKDAYS.map((label, day) => {
            const on = weekdays.includes(day);
            return (
              <button key={label} type="button" aria-pressed={on} onClick={() => setWeekdays(on ? weekdays.filter((d) => d !== day) : [...weekdays, day].sort())}
                className={`h-9 w-9 rounded-full border text-sm font-medium ${on ? "border-emerald-700 bg-emerald-700 text-white" : "border-stone-300 bg-white dark:border-stone-700 dark:bg-stone-900"}`}>
                {label}
              </button>
            );
          })}
        </div>
      </fieldset>
      <Field label="이용일 시작"><input type="date" className={inputClass} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></Field>
      <Field label="이용일 끝"><input type="date" className={inputClass} value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></Field>
      <Field label="시간대 시작"><input type="time" className={inputClass} value={timeFrom} onChange={(e) => setTimeFrom(e.target.value)} /></Field>
      <Field label="시간대 끝"><input type="time" className={inputClass} value={timeTo} onChange={(e) => setTimeTo(e.target.value)} /></Field>
      <Field label="최소 연속 시간"><input type="number" min={1} max={24} className={inputClass} value={minHours} onChange={(e) => setMinHours(e.target.value)} placeholder="제한 없음" /></Field>
      <div className="col-span-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm sm:self-end sm:pb-1.5">
        <label className="flex items-center gap-2"><input type="checkbox" checked={notifyOpening} onChange={(e) => setNotifyOpening(e.target.checked)} /> 오픈 알림</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={notifyVacancy} onChange={(e) => setNotifyVacancy(e.target.checked)} /> 접수 재개 알림</label>
      </div>
      <div className="col-span-2 flex items-end sm:col-span-1"><Button type="submit" variant="primary" className="w-full">조건 추가</Button></div>
    </form>
  );
}

function ManualFacilityForm({ act }: { act: Act }) {
  const [name, setName] = useState("");
  const [area, setArea] = useState("");
  const [bookingUrl, setBookingUrl] = useState("");

  return (
    <form
      className="grid gap-3 sm:grid-cols-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void act(() => api("/facilities", { method: "POST", body: { name: name.trim(), area: area || null, booking_url: bookingUrl || null } })).then(() => { setName(""); setArea(""); setBookingUrl(""); });
      }}
    >
      <Field label="시설명"><input required className={inputClass} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="지역"><input className={inputClass} value={area} maxLength={50} onChange={(e) => setArea(e.target.value)} placeholder="예: 강남구" /></Field>
      <Field label="예약 사이트 주소"><input type="url" className={inputClass} value={bookingUrl} maxLength={500} onChange={(e) => setBookingUrl(e.target.value)} placeholder="https://" /></Field>
      <div className="flex items-end"><Button type="submit" variant="primary" className="w-full" disabled={!name.trim()}>등록</Button></div>
    </form>
  );
}
