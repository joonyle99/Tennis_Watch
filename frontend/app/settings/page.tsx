"use client";

import { useState, type FormEvent } from "react";

import { Badge, Button, Card, Field, inputBase, inputClass, Loadable, Note, Toggle } from "@/components/ui";
import {
  api, type AppSettings, type Facility, type NotificationEvent, type OpeningRule, type RuleType, type SystemStatus,
} from "@/lib/api"; // prettier-ignore
import { fmtDateTime, fmtOffset, fmtTime, RULE_LABEL, VERIFICATION_LABEL, VERIFICATION_TONE } from "@/lib/format";
import { useApi } from "@/lib/useApi";

interface TelegramStatus {
  token_set: boolean;
  chat_id_set: boolean;
  notifications_enabled: boolean;
}

const NOTIFICATION_LABEL: Record<NotificationEvent["type"], string> = {
  OPENING_SOON: "오픈 예정",
  OPENED: "오픈 확인",
  REOPENED: "접수 재개",
  SYSTEM_ERROR: "수집 오류",
};
const SEND_LABEL = { PENDING: "대기", SENT: "전송됨", FAILED: "실패", SKIPPED: "보내지 않음" } as const;
const SEND_TONE = { PENDING: "info", SENT: "good", FAILED: "bad", SKIPPED: "muted" } as const;

export default function SettingsPage() {
  const telegram = useApi<TelegramStatus>("/telegram");
  const settings = useApi<AppSettings>("/settings");
  const status = useApi<SystemStatus>("/status", 60000);
  const rules = useApi<OpeningRule[]>("/opening-rules");
  const facilities = useApi<Facility[]>("/facilities?watched=true");
  const notifications = useApi<NotificationEvent[]>("/notifications?limit=20", 60000);
  const auth = useApi<{ required: boolean }>("/auth/status");
  const [message, setMessage] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const [testing, setTesting] = useState(false);

  async function save(values: Partial<AppSettings>, done = "저장했습니다") {
    try {
      await api("/settings", { method: "PUT", body: { values } });
      setMessage({ tone: "good", text: done });
    } catch (e) {
      setMessage({ tone: "bad", text: e instanceof Error ? e.message : "저장하지 못했습니다" });
    } finally {
      void settings.reload();
      void telegram.reload();
    }
  }

  async function testTelegram() {
    setTesting(true);
    try {
      const result = await api<{ ok: boolean; bot_name: string | null; error: string | null }>("/telegram/test", { method: "POST" });
      setMessage(
        result.ok
          ? { tone: "good", text: `테스트 메시지를 보냈습니다 (@${result.bot_name}). Telegram을 확인하세요.` }
          : { tone: "bad", text: `전송 실패: ${result.error}` },
      );
    } catch (e) {
      setMessage({ tone: "bad", text: e instanceof Error ? e.message : "전송하지 못했습니다" });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-4">
      {message && <Note tone={message.tone}>{message.text}</Note>}

      <Card title="Telegram 알림">
        <Loadable state={telegram}>
          {(t) => (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={t.token_set ? "good" : "bad"}>봇 토큰 {t.token_set ? "설정됨" : "없음"}</Badge>
                <Badge tone={t.chat_id_set ? "good" : "bad"}>채팅 ID {t.chat_id_set ? "설정됨" : "없음"}</Badge>
                <Button onClick={testTelegram} disabled={testing}>{testing ? "보내는 중…" : "연결 테스트"}</Button>
              </div>
              {(!t.token_set || !t.chat_id_set) && (
                <Note tone="warn">토큰과 채팅 ID는 서버의 .env 파일에 넣습니다. 방법은 docs/TELEGRAM_SETUP.md에 있습니다.</Note>
              )}
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>
                  <span className="font-medium">알림 보내기</span>
                  <span className="block text-xs text-stone-500 dark:text-stone-400">꺼 둔 동안의 알림은 이력에만 남고, 다시 켜도 뒤늦게 보내지 않습니다.</span>
                </span>
                <Toggle checked={t.notifications_enabled} label="알림 보내기" onChange={(next) => save({ notifications_enabled: next }, next ? "알림을 켰습니다" : "알림을 껐습니다")} />
              </label>
            </div>
          )}
        </Loadable>
      </Card>

      <Card title="예약 오픈 알림 시점" hint="오픈 몇 분 전에 알릴지 정합니다. 매일 열리는 시설에는 1일 미만 시점만 적용됩니다.">
        <Loadable state={settings}>
          {(s) => <OffsetEditor offsets={s.opening_alert_offsets_minutes} onChange={(next) => save({ opening_alert_offsets_minutes: next })} />}
        </Loadable>
      </Card>

      <Card title="자동 수집">
        <Loadable state={status}>
          {(st) => (
            <div className="space-y-3">
              {st.paused_reason && (
                <Note tone="bad">
                  수집이 멈춰 있습니다: {st.paused_reason}.{" "}
                  <button
                    type="button"
                    className="font-semibold underline"
                    onClick={async () => {
                      await api("/sync/resume", { method: "POST" });
                      setMessage({ tone: "good", text: "수집을 다시 켰습니다" });
                      void status.reload();
                    }}
                  >
                    다시 켜기
                  </button>
                </Note>
              )}
              <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-stone-500 dark:text-stone-400">마지막 정상 수집</dt>
                  <dd className="font-medium">{st.sites[0]?.last_success_at ? fmtDateTime(st.sites[0].last_success_at) : "아직 없음"}</dd>
                </div>
                <div>
                  <dt className="text-stone-500 dark:text-stone-400">연속 실패</dt>
                  <dd className="font-medium">{st.sites[0]?.consecutive_failures ?? 0}회</dd>
                </div>
                {st.sites[0]?.backoff_until && (
                  <div>
                    <dt className="text-stone-500 dark:text-stone-400">다음 시도</dt>
                    <dd className="font-medium">{fmtDateTime(st.sites[0].backoff_until)} 이후</dd>
                  </div>
                )}
              </dl>
              {settings.data && <IntervalEditor key={settings.data.sync_interval_minutes} minutes={settings.data.sync_interval_minutes} onSave={(m) => save({ sync_interval_minutes: m })} />}
            </div>
          )}
        </Loadable>
      </Card>

      <Card title="예약 오픈 규칙" hint="자동 규칙은 사이트에서 수집한 값입니다. 사이트에 없는 반복 규칙은 직접 등록하세요.">
        <Loadable state={rules}>
          {(list) => (
            <RuleList
              rules={list}
              facilities={facilities.data ?? []}
              onDelete={async (id) => {
                await api(`/opening-rules/${id}`, { method: "DELETE" });
                void rules.reload();
              }}
            />
          )}
        </Loadable>
        <div className="mt-4">
          <RuleForm facilities={facilities.data ?? []} onSaved={() => void rules.reload()} />
        </div>
      </Card>

      <Card title="수집 기록" hint="최근 30건">
        <Loadable state={status}>
          {(st) =>
            st.recent_logs.length === 0 ? (
              <p className="text-sm text-stone-500">기록이 없습니다.</p>
            ) : (
              <div className="-mx-4 overflow-x-auto px-4">
                <table className="w-full min-w-[32rem] text-left text-sm">
                  <thead className="text-xs whitespace-nowrap text-stone-500 dark:text-stone-400">
                    <tr>
                      <th className="py-1 pr-3 font-medium">시각</th>
                      <th className="py-1 pr-3 font-medium">작업</th>
                      <th className="py-1 pr-3 font-medium">결과</th>
                      <th className="py-1 pr-3 text-right font-medium">건수</th>
                      <th className="py-1 font-medium">오류</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-200 dark:divide-stone-800">
                    {st.recent_logs.map((log) => (
                      <tr key={log.id}>
                        <td className="py-1.5 pr-3 whitespace-nowrap tabular-nums">{fmtDateTime(log.started_at)}</td>
                        <td className="py-1.5 pr-3 whitespace-nowrap">{log.job === "list" ? "목록" : "상세"}</td>
                        <td className="py-1.5 pr-3">
                          <Badge tone={log.success ? "good" : log.success === false ? "bad" : "info"}>{log.success ? "성공" : log.success === false ? "실패" : "진행 중"}</Badge>
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{log.item_count ?? "-"}</td>
                        <td className="py-1.5 text-xs text-stone-600 dark:text-stone-400">{log.error_type && `${log.error_type}: ${log.error_message ?? ""}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
        </Loadable>
      </Card>

      <Card title="알림 이력" hint="최근 20건">
        <Loadable state={notifications} empty="아직 알림이 없습니다.">
          {(list) => (
            <ul className="divide-y divide-stone-200 dark:divide-stone-800">
              {list.map((event) => (
                <li key={event.id} className="py-2 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="tabular-nums text-stone-500 dark:text-stone-400">{fmtDateTime(event.sent_at ?? event.created_at)}</span>
                    <Badge tone="info">{NOTIFICATION_LABEL[event.type]}</Badge>
                    <Badge tone={SEND_TONE[event.status]}>{SEND_LABEL[event.status]}</Badge>
                    {event.last_error && <span className="text-xs text-stone-500">{event.last_error}</span>}
                  </div>
                  <p className="mt-1 text-xs text-stone-600 dark:text-stone-400">{event.message.split("\n").filter(Boolean).slice(1, 4).join(" · ")}</p>
                </li>
              ))}
            </ul>
          )}
        </Loadable>
      </Card>

      {auth.data?.required && (
        <Button
          onClick={async () => {
            await api("/auth/logout", { method: "POST" });
            window.location.href = "/login";
          }}
        >
          로그아웃
        </Button>
      )}
    </div>
  );
}

function OffsetEditor({ offsets, onChange }: { offsets: number[]; onChange: (next: number[]) => void }) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState(1);
  const sorted = [...offsets].sort((a, b) => b - a);

  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-2">
        {sorted.length === 0 && <li className="text-sm text-stone-500">알림 시점이 없습니다. 오픈 예정 알림이 가지 않습니다.</li>}
        {sorted.map((minutes) => (
          <li key={minutes} className="flex items-center gap-1 rounded-full border border-stone-300 py-1 pr-1 pl-3 text-sm dark:border-stone-700">
            {fmtOffset(minutes)}
            <button type="button" aria-label={`${fmtOffset(minutes)} 삭제`} className="h-6 w-6 rounded-full text-stone-500 hover:bg-stone-200 dark:hover:bg-stone-800" onClick={() => onChange(sorted.filter((m) => m !== minutes))}>
              ×
            </button>
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          const minutes = Number(value) * unit;
          if (!Number.isInteger(minutes) || minutes < 1 || sorted.includes(minutes)) return;
          onChange([...sorted, minutes]);
          setValue("");
        }}
      >
        <input type="number" min={1} aria-label="알림 시점 값" className={`${inputBase} w-24`} value={value} onChange={(e) => setValue(e.target.value)} />
        <select aria-label="단위" className={`${inputBase} w-24`} value={unit} onChange={(e) => setUnit(Number(e.target.value))}>
          <option value={1}>분 전</option>
          <option value={60}>시간 전</option>
          <option value={1440}>일 전</option>
        </select>
        <Button type="submit" disabled={!value}>추가</Button>
      </form>
    </div>
  );
}

function IntervalEditor({ minutes, onSave }: { minutes: number; onSave: (minutes: number) => void }) {
  const [value, setValue] = useState(String(minutes));
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSave(Number(value));
      }}
    >
      <Field label="수집 주기 (분)" hint="접수 시작 10분 전부터는 해당 공고만 1분마다 확인합니다.">
        <input type="number" min={1} max={1440} required className={`${inputBase} w-28`} value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
      <Button type="submit" disabled={Number(value) === minutes} className="mb-5">저장</Button>
    </form>
  );
}

function describeRule(rule: OpeningRule): string {
  if (rule.rule_type === "MONTHLY") return `매월 ${rule.day_of_month}일 ${fmtTime(rule.open_time)}`;
  if (rule.rule_type === "DAYS_BEFORE_USE") return `이용일 ${rule.days_before}일 전 ${fmtTime(rule.open_time)}`;
  return fmtDateTime(rule.opens_at);
}

function RuleList({ rules, facilities, onDelete }: { rules: OpeningRule[]; facilities: Facility[]; onDelete: (id: number) => void }) {
  const watchedIds = new Set(facilities.map((f) => f.id));
  const shown = rules.filter((r) => watchedIds.has(r.facility_id));
  if (shown.length === 0) return <p className="text-sm text-stone-500">관심 시설의 오픈 규칙이 없습니다.</p>;

  return (
    <div className="space-y-4">
      {facilities
        .filter((f) => shown.some((r) => r.facility_id === f.id))
        .map((facility) => {
          // 같은 내용의 자동 규칙(코트별 공고마다 하나씩)은 한 줄로 합쳐 보여 준다.
          const merged = new Map<string, { rule: OpeningRule; targets: string[] }>();
          for (const rule of shown.filter((r) => r.facility_id === facility.id)) {
            const key = rule.source === "MANUAL" ? `m${rule.id}` : `${rule.rule_type}|${describeRule(rule)}|${rule.verification_status}`;
            const entry = merged.get(key) ?? { rule, targets: [] };
            if (rule.target_description) entry.targets.push(rule.target_description);
            merged.set(key, entry);
          }
          return (
            <div key={facility.id}>
              <h3 className="mb-1.5 text-sm font-semibold">{facility.name}</h3>
              <ul className="divide-y divide-stone-200 dark:divide-stone-800">
                {[...merged.values()].map(({ rule, targets }) => (
                  <li key={rule.id} className="flex items-start justify-between gap-3 py-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="font-medium">{describeRule(rule)}</span>
                        <Badge>{RULE_LABEL[rule.rule_type]}</Badge>
                        <Badge tone={rule.source === "AUTO" ? "info" : "muted"}>{rule.source === "AUTO" ? "자동" : "수동"}</Badge>
                        <Badge tone={VERIFICATION_TONE[rule.verification_status]}>{VERIFICATION_LABEL[rule.verification_status]}</Badge>
                      </div>
                      <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">
                        {targets.length > 1 ? `${targets.length}개 공고` : targets[0]}
                        {rule.note && ` · ${rule.note}`}
                        {rule.last_verified_at && ` · ${fmtDateTime(rule.last_verified_at)} 확인`}
                      </p>
                    </div>
                    {rule.source === "MANUAL" && <Button variant="danger" onClick={() => onDelete(rule.id)}>삭제</Button>}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
    </div>
  );
}

function RuleForm({ facilities, onSaved }: { facilities: Facility[]; onSaved: () => void }) {
  const [facilityId, setFacilityId] = useState("");
  const [type, setType] = useState<RuleType>("MONTHLY");
  const [day, setDay] = useState("10");
  const [daysBefore, setDaysBefore] = useState("14");
  const [time, setTime] = useState("00:00");
  const [date, setDate] = useState("");
  const [target, setTarget] = useState("");
  const [inferred, setInferred] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const chosen = facilityId || String(facilities[0]?.id ?? "");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/opening-rules", {
        method: "POST",
        body: {
          facility_id: Number(chosen),
          rule_type: type,
          day_of_month: type === "MONTHLY" ? Number(day) : null,
          days_before: type === "DAYS_BEFORE_USE" ? Number(daysBefore) : null,
          open_time: type === "ONE_TIME" ? null : time,
          // 입력한 날짜와 시각은 한국시간이다.
          opens_at: type === "ONE_TIME" ? `${date}T${time}:00+09:00` : null,
          target_description: target || null,
          verification_status: inferred ? "INFERRED" : "UNVERIFIED",
        },
      });
      setTarget("");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "등록하지 못했습니다");
    }
  }

  if (facilities.length === 0) return <Note>관심 시설을 먼저 등록하세요.</Note>;
  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-3 rounded-lg border border-dashed border-stone-300 p-3 sm:grid-cols-4 dark:border-stone-700">
      <div className="col-span-2">
        <Field label="시설">
          <select className={inputClass} value={chosen} onChange={(e) => setFacilityId(e.target.value)}>
            {facilities.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </Field>
      </div>
      <div className="col-span-2">
        <Field label="규칙">
          <select className={inputClass} value={type} onChange={(e) => setType(e.target.value as RuleType)}>
            <option value="MONTHLY">매월 특정 날짜</option>
            <option value="DAYS_BEFORE_USE">이용일 기준 N일 전</option>
            <option value="ONE_TIME">특정 날짜 한 번</option>
          </select>
        </Field>
      </div>
      {type === "MONTHLY" && <Field label="매월 며칠"><input type="number" min={1} max={31} required className={inputClass} value={day} onChange={(e) => setDay(e.target.value)} /></Field>}
      {type === "DAYS_BEFORE_USE" && <Field label="이용일 며칠 전"><input type="number" min={0} max={365} required className={inputClass} value={daysBefore} onChange={(e) => setDaysBefore(e.target.value)} /></Field>}
      {type === "ONE_TIME" && <Field label="날짜"><input type="date" required className={inputClass} value={date} onChange={(e) => setDate(e.target.value)} /></Field>}
      <Field label="오픈 시각"><input type="time" required className={inputClass} value={time} onChange={(e) => setTime(e.target.value)} /></Field>
      <div className="col-span-2"><Field label="대상 설명"><input className={inputClass} value={target} maxLength={200} onChange={(e) => setTarget(e.target.value)} placeholder="예: 16일~말일 이용분" /></Field></div>
      <label className="col-span-2 flex items-center gap-2 text-sm sm:col-span-3">
        <input type="checkbox" checked={inferred} onChange={(e) => setInferred(e.target.checked)} />
        관측에서 추정한 규칙 (알림에 &quot;추정&quot;으로 표시되고, 새 공고가 올라오면 실제 일시와 대조합니다)
      </label>
      <div className="col-span-2 flex items-end sm:col-span-1"><Button type="submit" variant="primary" className="w-full">규칙 등록</Button></div>
      {error && <div className="col-span-2 sm:col-span-4"><Note tone="bad">{error}</Note></div>}
    </form>
  );
}
