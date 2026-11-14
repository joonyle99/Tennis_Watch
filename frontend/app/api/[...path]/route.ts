// 브라우저의 /api 요청을 백엔드로 넘긴다.
// 브라우저는 이 서버 하나만 알면 되고, 백엔드 주소(BACKEND_URL)는 실행할 때 정한다.

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const FORWARDED_REQUEST_HEADERS = ["content-type", "cookie", "accept"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "set-cookie"];

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
let passwordRequired: { value: boolean; checkedAt: number } | null = null;

async function isPasswordRequired(): Promise<boolean> {
  if (passwordRequired && Date.now() - passwordRequired.checkedAt < 30000) return passwordRequired.value;
  const response = await fetch(`${BACKEND_URL}/api/auth/status`, { cache: "no-store" });
  const value = Boolean((await response.json()).required);
  passwordRequired = { value, checkedAt: Date.now() };
  return value;
}

async function proxy(request: Request): Promise<Response> {
  const url = new URL(request.url);

  // 이 컴퓨터가 아닌 주소로 들어왔는데 비밀번호가 없으면 거절한다.
  // 실수로 열어 두는 것을 막는 장치일 뿐이고(Host는 꾸밀 수 있다), 실제 보호는 비밀번호 로그인이 한다.
  const host = (request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? "").replace(/:\d+$/, "");
  if (!LOCAL_HOSTS.has(host)) {
    try {
      if (!(await isPasswordRequired())) {
        return Response.json(
          { detail: "다른 기기에서 접속하려면 서버의 .env에 DASHBOARD_PASSWORD를 설정하고 다시 시작하세요." },
          { status: 403 },
        );
      }
    } catch {
      return Response.json({ detail: "백엔드 서버에 연결할 수 없습니다" }, { status: 502 });
    }
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // 로그인 쿠키에 Secure를 붙일지 백엔드가 판단할 수 있게 원래 프로토콜을 알려 준다.
  headers.set("x-forwarded-proto", request.headers.get("x-forwarded-proto") ?? url.protocol.replace(":", ""));

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}${url.pathname}${url.search}`, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json({ detail: "백엔드 서버에 연결할 수 없습니다" }, { status: 502 });
  }

  const responseHeaders = new Headers({ "cache-control": "no-store" });
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
  return new Response(body, { status: upstream.status, headers: responseHeaders });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
