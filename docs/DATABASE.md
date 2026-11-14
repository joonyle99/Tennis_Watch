# 데이터베이스

SQLite 파일 하나를 쓴다(`DATABASE_URL`, 기본 `./data/tennis_watch.db`). 외래 키 검사와 WAL 모드를 켠다. 모델 정의는 `backend/app/models/`.

## 관계

```
sites ─┬─< facilities ─┬─< courts
       │               ├─< opening_rules
       │               ├─< court_slots ──< slot_history
       │               └─< watch_rules
       ├─< reservation_notices ──< notice_status_history
       └─< crawl_logs
notification_events ─▶ facilities / reservation_notices / court_slots (선택)
reservation_notices ─▶ facilities, courts (선택)
```

## 테이블

| 테이블 | 내용 | 유일 키 |
|---|---|---|
| `sites` | 예약 사이트. `seoul`이 기본으로 들어간다 | `code` |
| `facilities` | 테니스장. 사이트에 시설 엔터티가 없어 공고의 장소명으로 묶는다 | `site_id, external_name` |
| `courts` | 코트. 공고명에서 추출한 것은 `verified=false` | `facility_id, name` |
| `reservation_notices` | 예약 공고(서울시의 서비스 1건) | `site_id, external_id` |
| `notice_status_history` | 공고 접수 상태 변경 이력 | |
| `opening_rules` | 예약 오픈 규칙 | |
| `court_slots` | 코트·날짜·시간대 단위 상태 | `facility_id, court_id, use_date, start_time, end_time` |
| `slot_history` | 슬롯 상태 변경 이력 | |
| `watch_rules` | 개인 관심 조건 | |
| `notification_events` | 알림 발송 이력 | `dedupe_key` |
| `crawl_logs` | 수집 실행 기록 | |
| `app_settings` | 웹에서 바꾸는 설정(수집 주기, 알림 시점 등). 값은 JSON | `key` |

지침의 기본 테이블 10개에 두 개를 추가했다.

- `notice_status_history`: 서울시 사이트에서 자동 감지할 수 있는 변화가 슬롯이 아니라 공고 단위이기 때문이다. `kind`(변경 종류)와 `notifiable`(알림 대상 여부)을 함께 기록한다.
- `app_settings`: 수집 주기와 알림 시점을 화면에서 바꿀 수 있어야 하기 때문이다. 키와 기본값은 `services/settings.py`에 있다.

## 설계 메모

### 시설과 공고

- 공고 ID는 회차마다 바뀐다. 새 공고는 장소명이 `facilities.external_name` 또는 `aliases`와 일치하는 시설에 연결한다.
- `reservation_notices.is_active`는 최근 목록 수집에 포함되었는지다. 이용이 끝난 공고는 목록에서 빠진다.
- `status`는 공통 상태값, `raw_status`는 사이트 원문이다. `예약마감`과 `접수종료`는 둘 다 `UNAVAILABLE`이지만 접수 재개 판단에서 구분이 필요하다.
- `open_days_before`·`open_hour`는 롤링 오픈 규칙이며 상세 페이지를 조회한 공고에만 채워진다.

### 오픈 규칙

| `rule_type` | 쓰는 열 | 예 |
|---|---|---|
| `MONTHLY` | `day_of_month`, `open_time`, `target_description` | 매월 10일 00:00, 16일~말일분 |
| `DAYS_BEFORE_USE` | `days_before`, `open_time` | 이용일 14일 전 14:00 |
| `ONE_TIME` | `opens_at`, `target_use_start/end` | 특정 일시 1회 |
| `NOTICE` | `opens_at`, `notice_id`, `target_use_start/end` | 공고에 명시된 접수 시작 |

- 출처는 `source`(`AUTO`/`MANUAL`)로 구분한다. 지침의 "수동 등록 규칙"은 별도 유형이 아니라 `source=MANUAL`이다.
- `verification_status`: `VERIFIED`, `INFERRED`(관측에서 추정), `UNVERIFIED`, `CONFLICT`.
- 규칙을 고치면 기존 행을 `is_active=false`, `valid_to`로 닫고 `replaces_id`로 이어지는 새 행을 만든다.
- `open_time`은 한국 기준 시각이다.

### 슬롯

- `auto_status`는 서울시 사이트에서 채울 수 없어 `UNKNOWN`이다. 2차 사이트가 슬롯을 제공하면 쓴다.
- `manual_status`는 사용자가 직접 확인해 넣은 값이다. 둘 다 있고 다르면 충돌로 표시한다.
- `court_id`가 비어 있는 행은 SQLite 유일 제약이 걸리지 않으므로, 코드에서 조회 후 넣는다.

### 알림

- `dedupe_key`가 같은 알림은 한 번만 만들어진다(예: `opening:{notice}:{60m}`).
- `attempts`, `next_attempt_at`, `last_error`로 재시도를 추적한다. 재시작 후에도 `PENDING` 행에서 이어간다.

### 시간

`*_at` 열은 모두 UTC다. `use_date`, `start_time`, `open_time`처럼 한국 달력 기준인 값은 날짜·시각 그대로 저장한다.
