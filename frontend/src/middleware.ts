import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/api", "/apply", "/access"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }
  // Protected: require a session cookie. The cookie is set by the FastAPI
  // backend (httpOnly), so we just check for its presence here.
  const session = req.cookies.get("prosper_session");
  if (!session) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.svg).*)"],
};
