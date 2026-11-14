# Tennis Watch

개인용 테니스 코트 예약 모니터링 서비스. 요구사항은 `docs/PRD.md`, 사이트 조사 결과는 `docs/SITE_RESEARCH.md`, 구조는 `docs/ARCHITECTURE.md`와 `docs/DATABASE.md`.

## 명령

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --reload
```

## 규칙

- 자동 예약과 결제는 구현하지 않는다.
- CAPTCHA, 로그인 보호, 접근 제한을 우회하지 않는다. 서울시 사이트의 달력 AJAX(`selectListReservCalAjax.do` 등)는 호출하지 않는다.
- 사이트에서 확인하지 않은 주소, 선택자, 예약 규칙을 지어내지 않는다. 새로 확인한 사실은 `docs/SITE_RESEARCH.md`에 적는다.
- 테스트는 `backend/tests/fixtures/`의 fixture를 쓴다. 실제 사이트에 반복 요청하지 않는다.
- 시간은 UTC로 저장한다. 사이트 값은 `timeutil.kst_to_utc`로 변환한다.
- 수동 입력값을 자동 수집으로 덮어쓰지 않는다.
- 인증키와 토큰은 `.env`에만 둔다. 로그와 오류 메시지에도 넣지 않는다.
- 각 Phase가 끝나면 결과를 보고하고 승인을 받은 뒤 다음으로 넘어간다.

## 환경 메모

서울 Open API는 평문 HTTP 8088 포트라, 443만 허용하는 클라우드 환경에서는 호출되지 않는다. 사용자 로컬에서는 동작한다.
