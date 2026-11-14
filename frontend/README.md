# Tennis Watch 대시보드

Next.js(App Router) + TypeScript + Tailwind CSS. 실행 방법과 구조는 저장소 최상위의 `README.md`와 `docs/ARCHITECTURE.md`를 본다.

- 브라우저는 이 서버의 `/api/...`만 호출하고, `app/api/[...path]/route.ts`가 백엔드(`BACKEND_URL`, 기본 `http://127.0.0.1:8000`)로 넘긴다.
- 모든 시각은 한국시간으로 표시한다(`lib/format.ts`).
