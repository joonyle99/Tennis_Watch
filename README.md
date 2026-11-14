# Tennis Watch

테니스 코트 예약 오픈 일정과 접수 상태를 모니터링해 Telegram으로 알려 주는 개인용 서비스.

현재 상태: Telegram 알림(Phase 4)까지 구현. 서버를 띄우면 5분마다 수집하고 알림을 보낸다. 웹 대시보드는 아직 없다.

## 실행

```bash
cp .env.example .env   # SEOUL_OPENAPI_KEY 입력
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

API 문서: http://localhost:8000/docs

```bash
curl -X POST localhost:8000/api/sync        # 지금 한 번 수집
curl localhost:8000/api/status              # 마지막 성공 시각, 연속 실패, 최근 로그
curl "localhost:8000/api/notices?watched=true"
curl "localhost:8000/api/openings?days=14"  # 앞으로의 예약 오픈
```

## 테스트

```bash
cd backend
python -m pytest -q
```

## 문서

- [요구사항](docs/PRD.md)
- [사이트 조사](docs/SITE_RESEARCH.md)
- [Telegram 설정](docs/TELEGRAM_SETUP.md)
- [아키텍처](docs/ARCHITECTURE.md)
- [데이터베이스](docs/DATABASE.md)

## 데이터 출처

서울특별시, 서울 열린데이터광장 「서울시 체육시설 공공서비스예약 정보」 (공공누리 1유형).
