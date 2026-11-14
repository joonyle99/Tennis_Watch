import type { Opening } from "./api";

export interface OpeningGroup {
  key: string;
  facility_id: number;
  opens_at: string;
  items: Opening[];
}

/** 같은 시설에서 같은 시각에 열리는 오픈을 한 줄로 묶는다. 알림도 같은 단위로 간다. */
export function groupOpenings(openings: Opening[]): OpeningGroup[] {
  const groups = new Map<string, OpeningGroup>();
  for (const opening of openings) {
    const key = `${opening.facility_id}|${opening.opens_at}`;
    const group = groups.get(key) ?? { key, facility_id: opening.facility_id, opens_at: opening.opens_at, items: [] };
    group.items.push(opening);
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => a.opens_at.localeCompare(b.opens_at) || a.facility_id - b.facility_id);
}

/** 묶음이 여는 이용일 범위. 하나로 정해지지 않으면 null. */
export function groupUseRange(group: OpeningGroup): { start: string; end: string } | null {
  const ranges = new Set(group.items.filter((o) => o.use_start).map((o) => `${o.use_start}|${o.use_end}`));
  if (ranges.size !== 1) return null;
  const [start, end] = [...ranges][0].split("|");
  return { start, end };
}
