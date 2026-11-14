# 아키텍처

```
frontend (Next.js) ──HTTP──▶ backend (FastAPI)
                               ├─ api/        REST 엔드포인트
                               ├─ services/   수집·상태 비교·알림 (Phase 3~4)
                               ├─ scheduler/  APScheduler 작업 (Phase 3)
                               ├─ adapters/   사이트별 수집기
                               └─ models/     SQLAlchemy 모델 ─▶ SQLite 파일
```

현재 구현된 것은 `models`, `adapters`, `api`(시설·코트·공고 조회)다. `services`와 `scheduler`는 빈 패키지다.

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

## 시간

- DB와 내부 로직은 UTC. `db.UTCDateTime` 타입이 시간대 없는 값의 저장을 거부한다.
- 사이트가 주는 일시는 한국시간으로 해석해 UTC로 바꾼다(`timeutil.kst_to_utc`).
- 이용 날짜와 하루 운영 시각처럼 한국 달력 기준인 값은 `Date`·`Time`으로 그대로 저장한다.
- API는 UTC ISO 8601로 응답하고, 화면에서 한국시간으로 표시한다.

## 수동 데이터 보호

- 시설: 사용자가 고친 필드 이름을 `locked_fields`에 기록하고, 자동 수집은 그 필드를 건드리지 않는다.
- 오픈 규칙: 자동 규칙과 수동 규칙을 별도 행으로 둔다. 다르면 `CONFLICT`로 표시한다.
- 슬롯: `auto_status`와 `manual_status`를 별도 열로 둔다.

## 스키마 변경

현재는 시작 시 `create_all`로 테이블을 만든다. 운영 데이터가 생긴 뒤 열을 바꿔야 하면 Alembic을 도입한다.
