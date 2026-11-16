# 아키텍처

```
frontend (Next.js) ──HTTP──▶ backend (FastAPI)
                               ├─ api/        REST 엔드포인트
                               ├─ services/   수집·상태 비교·알림 (Phase 3~4)
                               ├─ scheduler/  APScheduler 작업 (Phase 3)
                               ├─ adapters/   사이트별 수집기
                               └─ models/     SQLAlchemy 모델 ─▶ SQLite 파일
```

Phase 6까지 구현되어 있다. 실행과 운영 방법은 [DEPLOY.md](DEPLOY.md).

## 계층별 책임

| 계층 | 책임 | 하지 않는 것 |
|---|---|---|
| `adapters` | 사이트에서 값을 가져와 공통 자료형(`NoticeData`, `NoticeDetail`)으로 변환 | DB 접근, 알림 판단 |
| `services` | 수집 결과를 DB와 비교해 저장, 변경 감지, 알림 생성 | HTTP 요청, HTML 해석 |
| `scheduler` | 주기 실행, 중복 실행 방지 | 업무 로직 |
| `api` | 대시보드용 조회와 수동 입력 | 사이트 직접 호출 |

## Adapter

`adapters/base.py`의 `SiteAdapter`가 인터페이스다.

| 메서드 | 역할 |
|---|---|
| `fetch_notices(area)` | 공고 목록 |
| `fetch_notice_detail(id)` | 공고 한 건의 상세(접수 일시, 롤링 오픈 규칙) |
| `notice_url(id)` | 사용자가 예약하러 갈 주소 |
| `parse_title(title)` | 공고명에서 코트·요일·시간대 후보 추출 |

오류는 네 종류로 구분한다. 수집 엔진의 대응이 다르기 때문이다.

| 예외 | 의미 | 대응 |
|---|---|---|
| `AdapterError` | 일시적 실패(타임아웃, 5xx) | 백오프 후 재시도 |
| `AuthError` | 인증키 문제 | 재시도 무의미, 사용자에게 알림 |
| `BlockedError` | 사이트가 차단 | 즉시 수집 중단, 사용자에게 알림 |
| `ParseError` | 응답 구조가 달라짐 | 값을 추측하지 않고 실패 처리, 사용자에게 알림 |

2차 사이트는 `SiteAdapter`를 구현하고 `adapters/registry.py`에 등록한다.

### 서울시 어댑터 (`adapters/seoul.py`)

- 목록: Open API 1회 요청(최대 1,000건). 인증키가 없으면 HTML 목록을 페이지 단위로 수집하며, 페이지 수 한도를 넘으면 중단한다.
- 상세: 상세 페이지 HTML에서 접수 일시와 롤링 오픈 규칙을 읽는다.
- 달력(날짜·시간대별 잔여)은 수집하지 않는다.
- 같은 어댑터 인스턴스의 요청은 최소 간격(기본 2초)을 둔다.
- 오류 메시지와 예외에 인증키가 들어가지 않게 한다.
- 파서는 순수 함수(`parse_openapi_response`, `parse_list_html`, `parse_detail_html`, `parse_title`)라 fixture로 테스트한다.

## 수집 엔진

`scheduler.jobs.Collector`가 한 번의 수집을 실행한다. 스케줄러와 수동 실행(`POST /api/sync`)이 같은 인스턴스를 쓰고, 잠금으로 겹쳐 돌지 않게 한다.

```
Collector.run
 ├─ 수집 중지 상태면 아무 요청도 하지 않음
 ├─ 연속 실패 중이면 백오프 시각까지 건너뜀 (수동 실행은 건너뛰지 않음)
 ├─ run_list_sync    목록 → 시설·코트·공고 저장, 상태 변경 기록, 공고 오픈 규칙 기록
 └─ run_detail_sync  관심 시설 공고의 상세 → 접수 일시, 롤링 오픈 규칙, 상태 교차 확인
```

| 작업 | 주기 | 대상 |
|---|---|---|
| `sync` | `sync_interval_minutes` (기본 5분), 시작 5초 뒤 첫 실행 | 목록 전체 + 상세 최대 `detail_batch_size`건 |
| `hot` | 1분 | 접수 시작 10분 전 ~ 5분 후 구간에 있고 아직 열리지 않은 관심 공고의 상세 |

상세는 공고당 `detail_refresh_hours`(기본 24시간)에 한 번만 다시 확인한다.

### 목록 수집 경로

1. 인증키가 있으면 Open API(전체 목록, 요청 1회).
2. Open API가 실패하거나 키가 없으면 HTML 목록. 관심 시설이 있는 지역만 수집하고, 관심 시설이 아직 없으면 `DEFAULT_WATCHED_AREAS`(기본 강남구)부터 시작한다.
3. 차단(`BlockedError`)이면 다른 경로로 넘어가지 않고 멈춘다.

지역을 좁혀 수집한 경우, 목록에서 빠진 공고를 비활성으로 바꾸는 것도 그 지역 안에서만 한다.

### 상태 변경과 알림 대상

`services/availability.classify_change`가 변경 종류와 알림 가능 여부를 정한다. 결과는 `notice_status_history`에 `kind`, `notifiable`로 남고, Phase 4의 알림 발송이 `notifiable` 행을 읽는다.

| 변경 | 종류 | 알림 대상 |
|---|---|---|
| 처음 본 공고 | `INITIAL` | 아니오 |
| 접수 시작 전 → 예약 가능 | `OPENED` | 예 |
| 예약 불가 → 예약 가능 | `REOPENED` | 예. 단, 수집 실패 직후의 첫 성공 수집에서 발견된 것은 아니오 |
| 확인 불가·휴장 → 예약 가능 | `OTHER` | 아니오 |
| 그 밖 | `OTHER` | 아니오 |
| 공고명·기간만 수정 | (기록 없음) | 아니오 |

알림 대상이 되려면 추가로 관심 조건을 통과해야 한다(`services/watch.should_notify`): 관심 시설이어야 하고, 그 시설에 켜진 관심 조건이 있으면 그중 하나에 해당해야 한다. 공고에서 알 수 없는 항목(요일 구분, 운영 시각)은 제외 사유로 쓰지 않는다.

### 수집 실패 정책

| 상황 | 동작 |
|---|---|
| 실패 1회 | 저장된 상태를 그대로 둔다. `crawl_logs`에 오류 기록 |
| 연속 실패 | 다음 시도까지의 간격을 두 배씩 늘린다(5, 10, 20, 40, 60분, 최대 60분) |
| 연속 `failure_threshold`회(기본 3) | 진행 중인 공고의 상태를 `UNKNOWN`으로 바꾼다 |
| 복구 | 정상 수집 재개. 복구 시점에 발견된 접수 재개는 알리지 않는다 |
| 차단 감지 | `collection_paused_reason`을 기록하고 모든 수집을 멈춘다. `POST /api/sync/resume`으로만 재개 |
| 상세 1건 실패 | 그 공고의 값은 그대로 두고 나머지를 계속 확인 |

상태는 모두 DB에 있으므로 재시작하면 직전 상태와 비교를 이어간다.

### 오픈 규칙

- 회차별 공고: 관심 시설 공고의 접수 시작 일시를 `NOTICE` 규칙(자동, 검증됨)으로 기록한다.
- 롤링 오픈: 상세 페이지의 "이용일 N일 전 HH시"를 `DAYS_BEFORE_USE` 규칙으로 기록한다. 값이 바뀌면 기존 행을 닫고 새 행을 만든다.
- 수동 `DAYS_BEFORE_USE` 규칙은 자동 규칙과 비교해 `VERIFIED` 또는 `CONFLICT`로 표시한다.
- 수동 `MONTHLY` 규칙은 새 공고가 올라올 때 실제 접수 시작 일시와 대조한다. 맞으면 `VERIFIED`, 맞는 규칙이 없으면 날짜가 가장 가까운 규칙을 `CONFLICT`로 표시한다.
- `services/opening_rules.upcoming_openings`가 규칙에서 앞으로의 오픈 시각을 계산한다. 롤링 규칙은 관심 조건(날짜·요일)이 있으면 그 이용일이 열리는 날만 남긴다.

## 알림

`services/notifier.run_notifications`가 30초마다, 그리고 수집 직후에 실행된다.

```
run_notifications
 ├─ enqueue_changes        notifiable 상태 변경 → 오픈 확인 / 접수 재개
 ├─ enqueue_openings       오픈 규칙에서 계산한 예정 시각 → 오픈 예정
 ├─ enqueue_system_alerts  연속 실패, 수집 중지 → 수집 오류
 └─ send_pending           PENDING 알림을 Telegram으로 발송
```

| 항목 | 방식 |
|---|---|
| 중복 방지 | `notification_events.dedupe_key` 유일 키. 상태 변경은 `change:{이력 id}`, 오픈 예정은 `opening:{시설}:{오픈 시각}:{분 전}`, 장애는 `sysfail:{사이트}:{첫 실패 로그 id}` |
| 묶음 | 같은 시설에서 같은 시각에 열리는 오픈은 한 메시지 |
| 오픈 예정 시점 | `opening_alert_offsets_minutes`(기본 1440, 60, 10). 매일 열리는 롤링 규칙은 1일 미만 시점만 |
| 밀린 알림 | 보낼 시점이 여러 개 지나 있으면 가장 가까운 하나만 보내고 나머지는 `SKIPPED` |
| 만료 | 오픈 예정은 오픈 시각, 상태 변경은 30분이 지나면 보내지 않음. 수집 오류는 만료 없음 |
| 재시도 | 실패 시 30초부터 두 배씩(최대 10분) 간격을 두고 최대 5회. 4xx는 즉시 `FAILED` |
| 429 | 응답의 `retry_after`만큼 기다리고, 그 차례의 나머지 발송도 멈춤. 실패 횟수에 넣지 않음 |
| 끄기 | `notifications_enabled=false`이거나 Telegram 미설정이면 `SKIPPED`로 기록만 함 |
| 재시작 | `PENDING` 행이 DB에 남아 있어 이어서 발송 |

`services/telegram.TelegramClient`는 요청 주소에 토큰이 들어가므로 예외에 주소와 원래 예외를 싣지 않는다. `main.py`에서 `httpx` 요청 로그도 끈다.

## 대시보드

`frontend/`는 Next.js(App Router)다. 화면은 모두 클라이언트 컴포넌트이고 데이터는 `/api`에서 가져온다.

| 경로 | 화면 | 내용 |
|---|---|---|
| `/` | 대시보드 | 수집 상태, 오픈 예정(14일), 접수중 공고, 최근 접수 재개 |
| `/calendar` | 달력 | 월간 격자와 선택한 날의 오픈·이용분 공고·직접 적은 시간대. 시설·코트 필터 |
| `/watch` | 관심 설정 | 시설 검색과 관심 켜기, 코트 확인, 관심 조건, 시설 직접 등록 |
| `/settings` | 시스템 | Telegram 테스트와 켜기/끄기, 알림 시점, 수집 주기, 오픈 규칙, 수집 기록, 알림 이력 |
| `/login` | 로그인 | 비밀번호 입력 |

- **프록시**: 브라우저는 대시보드 서버의 `/api/...`만 호출한다. `app/api/[...path]/route.ts`가 `BACKEND_URL`로 넘기고 쿠키를 그대로 전달한다. 백엔드 주소는 실행할 때 정한다.
- **시각**: 서버가 준 UTC를 `lib/format.ts`가 한국시간으로 바꾼다. 화면이 현재 시각에 따라 달라지므로 `ClientOnly`로 감싸 브라우저에서만 그린다.
- **묶음**: 같은 시설·같은 시각의 오픈은 `lib/openings.ts`가 한 줄로 묶는다(알림과 같은 단위).
- **달력의 "접수중"**: 그 날짜가 공고의 이용 기간과 요일 구분에 들고, 공고가 접수중이며, 롤링 오픈이면 그 날짜분이 이미 열렸을 때다. 공고 단위 판단이고 실제 빈자리는 아니다.
- **좁은 화면**: 탭은 아래에 고정하고, 달력 칸은 점으로 표시한다.

### 접근 제한

- `DASHBOARD_PASSWORD`가 있으면 `/api/health`와 `/api/auth/*`를 뺀 모든 API가 로그인 세션을 요구한다(`main.py`의 미들웨어).
- 세션은 만료 시각에 비밀번호로 만든 키로 서명한 HttpOnly, SameSite=Lax 쿠키다(30일). 비밀번호를 바꾸면 기존 세션은 모두 무효가 된다.
- 비밀번호를 5번 연속 틀리면 5분간 로그인 시도를 막는다.
- 대시보드 서버는 기본으로 이 컴퓨터(127.0.0.1)에서만 열린다. `npm run start:lan`으로 다른 기기에 열 수 있고, 이때 비밀번호가 없으면 프록시가 이 컴퓨터 밖에서 온 요청을 거절한다. 이 거절은 실수 방지용이고, 실제 보호는 로그인이 한다.

## 배포와 백업

- `docker-compose.yml`은 `backend`와 `frontend` 두 서비스다. 백엔드는 컨테이너 네트워크 안에서만 열리고, 대시보드 포트만 호스트에 연결한다(기본 `127.0.0.1:3000`).
- DB는 호스트의 `backend/data/`에 둔다. 컨테이너를 지우거나 다시 만들어도 남는다.
- 백엔드 컨테이너는 시작할 때 데이터 폴더의 소유자를 맞춘 뒤 일반 사용자로 권한을 내려 실행한다(`docker-entrypoint.sh`).
- `services/backup.py`는 SQLite 온라인 백업으로 복사하고, 무결성 검사를 통과한 뒤에만 정식 이름을 붙인다. 스케줄러가 매일 04:00(KST)에 실행하고 최근 14개를 남긴다.

## 테스트

| 종류 | 위치 | 대상 |
|---|---|---|
| 단위·통합 | `backend/tests/test_*.py` | 파서, 수집 엔진, 상태 전이, 오픈 규칙, 알림, API, 로그인, 백업 |
| 화면 E2E | `frontend/e2e/*.spec.ts` | 로그인, 대시보드, 달력, 관심 설정, 시스템, 휴대폰 너비 |

E2E는 `backend/tests/e2e_server.py`가 임시 DB에 예시 데이터를 넣고 가짜 수집기와 가짜 Telegram을 붙여 띄운 서버를 상대로 실행한다.

## 시간

- DB와 내부 로직은 UTC. `db.UTCDateTime` 타입이 시간대 없는 값의 저장을 거부한다.
- 사이트가 주는 일시는 한국시간으로 해석해 UTC로 바꾼다(`timeutil.kst_to_utc`).
- 이용 날짜와 하루 운영 시각처럼 한국 달력 기준인 값은 `Date`·`Time`으로 그대로 저장한다.
- API는 UTC ISO 8601로 응답하고, 화면에서 한국시간으로 표시한다.

## 수동 데이터 보호

- 시설·공고: 사용자가 고친 필드 이름을 `locked_fields`에 기록하고, 자동 수집은 그 필드를 건드리지 않는다. 시설의 빈 칸은 수집값으로 채운다.
- 오픈 규칙: 자동 규칙과 수동 규칙을 별도 행으로 둔다. 다르면 `CONFLICT`로 표시한다.
- 슬롯: `auto_status`와 `manual_status`를 별도 열로 둔다.

## 스키마 변경

현재는 시작 시 `create_all`로 테이블을 만든다. 운영 데이터가 생긴 뒤 열을 바꿔야 하면 Alembic을 도입한다.
