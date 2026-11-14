# Telegram 알림 설정

Tennis Watch는 Telegram 봇으로 알림을 보낸다. 필요한 값은 두 개다.

| 값 | 의미 | 넣는 곳 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | 봇의 비밀번호. 이 값을 가진 사람은 봇으로 메시지를 보낼 수 있다 | `.env` |
| `TELEGRAM_CHAT_ID` | 알림을 받을 채팅(본인과 봇의 대화방) 번호 | `.env` |

두 값 모두 채팅이나 저장소에 올리지 않는다. `.env`는 Git에 포함되지 않는다.

## 1. 봇 만들기

1. Telegram 앱 검색창에 `BotFather`를 입력하고, 파란 체크 표시가 있는 공식 계정 **@BotFather**를 연다.
2. `/newbot`을 보낸다.
3. 봇의 표시 이름을 입력한다. 예: `Tennis Watch`
4. 봇의 사용자 이름을 입력한다. 영문이고 `bot`으로 끝나야 하며, 다른 사람이 쓰지 않는 이름이어야 한다. 예: `joon_tennis_watch_bot`
5. BotFather가 보내 주는 메시지에서 토큰을 복사한다. `1234567890:AAH...` 처럼 숫자, 콜론, 긴 문자열로 된 값이다.

## 2. 봇에게 말 걸기

봇은 먼저 말을 건 사람에게만 메시지를 보낼 수 있다.

1. BotFather의 메시지에 있는 `t.me/봇사용자이름` 링크를 누른다.
2. **시작**(또는 `/start`)을 누른다.
3. 아무 메시지나 하나 더 보낸다. 예: `hi`

## 3. 토큰을 `.env`에 넣고 서버 시작

저장소 최상위의 `.env` 파일에 토큰을 넣는다(파일이 없으면 `.env.example`을 복사한다).

```
TELEGRAM_BOT_TOKEN=1234567890:AAH...
TELEGRAM_CHAT_ID=
```

```bash
cd backend
```

```bash
python -m uvicorn app.main:app
```

## 4. 채팅 ID 찾기

다른 터미널에서 실행한다.

```bash
curl localhost:8000/api/telegram/chats
```

```json
[{"chat_id": "123456789", "type": "private", "name": "홍길동"}]
```

`type`이 `private`이고 `name`이 본인인 항목의 `chat_id`가 필요한 값이다.

결과가 `[]`이면 2번을 다시 하고(봇에게 메시지를 보낸 뒤) 바로 다시 호출한다. Telegram은 최근 메시지만 보관한다.

## 5. 채팅 ID를 넣고 다시 시작

```
TELEGRAM_CHAT_ID=123456789
```

`.env`는 서버가 시작될 때만 읽으므로, 서버를 껐다가(Ctrl+C) 다시 켠다.

## 6. 연결 테스트

```bash
curl -X POST localhost:8000/api/telegram/test
```

성공하면 `{"ok": true, "bot_name": "...", "error": null}`이 나오고, Telegram에 "[Tennis Watch] 연결 테스트" 메시지가 도착한다.

| `error` 내용 | 원인 | 조치 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN이 설정되지 않았습니다` | `.env`에 토큰이 없거나 서버를 다시 시작하지 않음 | 3번 확인 후 재시작 |
| `Telegram 오류 401: Unauthorized` | 토큰이 틀림 | BotFather에서 토큰을 다시 복사 |
| `TELEGRAM_CHAT_ID가 설정되지 않았습니다` | 채팅 ID가 없음 | 4~5번 |
| `Telegram 오류 400: Bad Request: chat not found` | 채팅 ID가 틀렸거나 봇에게 말을 건 적이 없음 | 2번, 4번 |
| `Telegram 오류 403: Forbidden: bot was blocked by the user` | 봇을 차단함 | Telegram에서 봇 차단 해제 |
| `Telegram 요청 실패 (...)` | 네트워크 문제 | 인터넷 연결 확인 |

## 받게 되는 알림

| 알림 | 시점 |
|---|---|
| 예약 오픈 예정 | 오픈 1일 전, 1시간 전, 10분 전 (설정에서 변경 가능) |
| 예약 오픈 확인 | 공고가 "안내중"에서 "접수중"으로 바뀐 것을 확인했을 때 |
| 접수 재개 (빈 코트 가능) | 공고가 "예약마감"에서 "접수중"으로 바뀌었을 때 |
| 수집 오류 | 수집이 3회 연속 실패했을 때, 사이트가 접근을 차단했을 때 |

- 같은 시설에서 같은 시각에 열리는 공고는 메시지 한 건으로 묶인다.
- 마루공원처럼 매일 열리는 시설은 매일 1시간 전과 10분 전에 온다. "1일 전" 알림은 전날 오픈 시각과 겹치므로 보내지 않는다.
- 접수 재개 알림은 어느 날짜·시간이 비었는지 알려 주지 못한다. 사이트가 그 정보를 자동 조회하지 못하게 막고 있기 때문이다.

## 알림 끄기와 시점 바꾸기

```bash
curl -X PUT localhost:8000/api/settings -H 'content-type: application/json' -d '{"values": {"notifications_enabled": false}}'
```

```bash
curl -X PUT localhost:8000/api/settings -H 'content-type: application/json' -d '{"values": {"opening_alert_offsets_minutes": [60, 10]}}'
```

꺼 둔 동안 생긴 알림은 이력에만 남고, 다시 켜도 뒤늦게 보내지 않는다. 발송 이력은 다음으로 본다.

```bash
curl localhost:8000/api/notifications
```

## 토큰이 노출되었을 때

BotFather에서 `/revoke`를 보내고 해당 봇을 고르면 기존 토큰이 무효가 되고 새 토큰이 나온다. `.env`를 새 값으로 바꾸고 서버를 다시 시작한다.
