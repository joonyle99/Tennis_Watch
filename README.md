# Tennis Watch

테니스 코트 예약 오픈 일정과 접수 상태를 모니터링해 Telegram으로 알려 주는 개인용 서비스.

## 빠른 실행 (Docker)

```bash
cp .env.example .env   # 인증키와 토큰 입력
docker compose up -d --build
```

대시보드: http://localhost:3000 · 자세한 내용은 [배포와 운영](docs/DEPLOY.md)

아래는 Docker 없이 터미널에서 직접 실행하는 방법이다.

## 실행

```bash
cp .env.example .env   # SEOUL_OPENAPI_KEY 입력
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

API 문서: http://localhost:8000/docs

다른 터미널에서 대시보드를 켠다.

```bash
cd frontend
npm install
npm run build
npm run start
```

대시보드: http://localhost:3000

## 휴대폰에서 보기

1. `.env`에 `DASHBOARD_PASSWORD=원하는비밀번호`를 넣고 백엔드를 다시 시작한다. 비밀번호가 없으면 다른 기기의 접속은 거절된다.
2. 대시보드를 `npm run start` 대신 `npm run start:lan`으로 켠다.
3. Mac의 주소를 확인한다: `ipconfig getifaddr en0`
4. 같은 Wi-Fi에 연결된 휴대폰에서 `http://(Mac 주소):3000`을 연다.

- 같은 Wi-Fi 안에서는 암호화되지 않은 HTTP다. 공용 Wi-Fi에서는 쓰지 않는다.
- 집 밖에서 보려면 Mac과 휴대폰을 Tailscale 같은 사설망으로 묶는 방법이 있다(이 저장소에서 검증하지는 않았다). 공유기 포트를 인터넷에 직접 여는 것은 권하지 않는다.
- 백엔드(8000번)는 이 컴퓨터에서만 열려 있고, 다른 기기는 대시보드(3000번)를 거쳐서만 접근한다.

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

```bash
cd frontend
npm run e2e
```

화면 테스트는 임시 DB와 가짜 수집기를 쓴다. 실제 예약 사이트와 Telegram에는 요청하지 않는다.

## 문서

- [요구사항](docs/PRD.md)
- [사이트 조사](docs/SITE_RESEARCH.md)
- [배포와 운영](docs/DEPLOY.md)
- [Telegram 설정](docs/TELEGRAM_SETUP.md)
- [아키텍처](docs/ARCHITECTURE.md)
- [데이터베이스](docs/DATABASE.md)

## 데이터 출처

서울특별시, 서울 열린데이터광장 「서울시 체육시설 공공서비스예약 정보」 (공공누리 1유형).
