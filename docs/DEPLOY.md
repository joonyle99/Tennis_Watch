# 배포와 운영

Docker Compose로 백엔드(수집·알림)와 대시보드를 함께 띄운다. 아래는 MacBook을 계속 켜 두고 쓰는 경우의 안내다.

검증 범위: 이미지 빌드, 실행, 로그인, 종료, 재시작 후 데이터 유지, 백업은 Linux의 Docker에서 확인했다. macOS의 Docker Desktop에서는 확인하지 못했다.

## 1. 준비

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/)을 설치하고 실행한다.
2. Docker Desktop 설정에서 로그인할 때 자동으로 시작하도록 켠다. Mac을 재부팅해도 서비스가 다시 올라오게 하기 위해서다.
3. 저장소 최상위에 `.env`가 있는지 확인한다(`.env.example` 참고).

## 2. 실행

터미널로 직접 켜 둔 서버(`uvicorn`, `npm run start`)가 있으면 먼저 끈다. 같은 DB 파일을 두 곳에서 동시에 쓰면 안 된다.

```bash
docker compose up -d --build
```

```bash
docker compose ps
```

두 서비스가 `Up (healthy)`이면 http://localhost:3000 에서 대시보드가 열린다. 첫 빌드는 몇 분 걸린다.

- DB는 `backend/data/tennis_watch.db`에 저장된다. 터미널로 직접 실행할 때 쓰던 파일과 같으므로 기존 데이터가 이어진다.
- 백엔드는 컨테이너 밖으로 열리지 않는다. 대시보드를 거쳐서만 접근한다.

## 3. 휴대폰에서 보기

`.env`에 두 줄을 넣는다.

```
DASHBOARD_PASSWORD=원하는비밀번호
DASHBOARD_BIND=0.0.0.0
```

```bash
docker compose up -d
```

```bash
ipconfig getifaddr en0
```

같은 Wi-Fi의 휴대폰에서 `http://(위 주소):3000`을 열고 비밀번호를 입력한다.

- `DASHBOARD_BIND=0.0.0.0`만 넣고 비밀번호를 비워 두면, 다른 기기의 요청은 거절된다.
- 같은 Wi-Fi 안의 통신은 암호화되지 않는다. 공용 Wi-Fi에서는 쓰지 않는다.
- 집 밖에서는 이 방법으로 열리지 않는다.

## 4. MacBook을 계속 켜 두기

Mac이 잠들면 수집과 알림이 모두 멈춘다. 이때는 "수집 오류" 알림도 오지 않는다(알림을 보낼 프로그램 자체가 멈춰 있다).

- 전원 어댑터를 연결해 둔다.
- 시스템 설정의 배터리(또는 에너지) 항목에서, 전원에 연결되어 있을 때 디스플레이가 꺼져도 자동으로 잠들지 않게 하는 옵션을 켠다. 메뉴 이름과 위치는 macOS 버전에 따라 다르다.
- 덮개를 닫으면 Mac은 잠든다. 덮개를 열어 두거나, 외부 모니터·전원·키보드를 연결해 덮개를 닫고 쓰는 방식으로 둔다.

잠들었다 깨어나면 다음과 같이 동작한다.

| 항목 | 동작 |
|---|---|
| 수집 | 깨어난 뒤 다음 주기에 다시 시작한다 |
| 오픈 예정 알림 | 놓친 시점 중 가장 가까운 하나만 보낸다. 이미 열린 오픈의 예고는 보내지 않는다 |
| 접수 재개 알림 | 잠든 사이 바뀐 상태를 깨어난 뒤 발견하면 그때 알린다. 언제 바뀌었는지는 알 수 없다 |

## 5. 자주 쓰는 명령

| 하려는 일 | 명령 |
|---|---|
| 상태 보기 | `docker compose ps` |
| 수집·알림 로그 보기 | `docker compose logs -f backend` |
| 끄기 (데이터는 남는다) | `docker compose down` |
| 다시 켜기 | `docker compose up -d` |
| `.env`를 고친 뒤 반영 | `docker compose up -d` |
| 새 버전으로 올리기 | `git pull` 후 `docker compose up -d --build` |

컨테이너는 오류로 죽거나 Mac이 재부팅되면 자동으로 다시 시작한다(`restart: unless-stopped`). `docker compose down`으로 직접 끈 경우에는 다시 켤 때까지 꺼져 있다.

## 6. 백업과 복원

매일 새벽 4시(한국시간)에 DB를 `backend/data/backups/`에 복사하고 최근 14개를 남긴다. 서버가 돌고 있는 중에도 안전하게 복사되는 방식이며, 복사본을 검사한 뒤에만 저장한다.

지금 바로 백업:

```bash
docker compose exec backend python -m app.services.backup
```

복원(백업 파일 이름은 실제 파일로 바꾼다):

```bash
docker compose down
```

```bash
cp backend/data/backups/tennis_watch-20261114-040000.db backend/data/tennis_watch.db
```

```bash
rm -f backend/data/tennis_watch.db-wal backend/data/tennis_watch.db-shm
```

```bash
docker compose up -d
```

`-wal`, `-shm` 파일은 이전 DB의 미반영 기록이라, 남겨 두면 복원한 파일과 섞인다. 반드시 지운다.

백업은 같은 디스크에 있으므로 Mac 자체가 고장 나면 함께 사라진다. 다만 이 서비스의 데이터는 대부분 사이트에서 다시 수집된다. 잃으면 다시 넣어야 하는 것은 관심 설정, 수동 오픈 규칙, 직접 적은 시간대다.

## 7. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 대시보드가 안 열린다 | `docker compose ps`에서 두 서비스가 `healthy`인지. 아니면 `docker compose logs backend frontend` |
| "백엔드 서버에 연결할 수 없습니다" | 백엔드 컨테이너가 내려가 있다. `docker compose up -d` |
| 포트가 이미 사용 중이라는 오류 | 터미널로 켠 `npm run start`가 3000번을 쓰고 있다. 끄거나 `.env`에 `DASHBOARD_PORT=3001` |
| 휴대폰에서 "DASHBOARD_PASSWORD를 설정하세요" | `.env`에 비밀번호를 넣고 `docker compose up -d` |
| 알림이 안 온다 | 대시보드의 시스템 화면에서 연결 테스트, 알림 이력의 "보내지 않음" 사유 확인 |
| 수집이 멈췄다는 알림 | 시스템 화면의 수집 기록에서 원인 확인 후 "다시 켜기" |

## 8. 테스트

```bash
cd backend && python -m pytest -q
```

```bash
cd frontend && npm run e2e
```

화면 테스트(`npm run e2e`)는 임시 DB와 가짜 수집기로 서버를 띄워 실행한다. 실제 예약 사이트와 Telegram에는 요청하지 않는다. 처음 한 번은 `npx playwright install chromium`이 필요하다.
