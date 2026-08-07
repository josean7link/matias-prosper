import { NextResponse, type NextRequest } from "next/server";
import { jwtVerify } from "jose";

/**
 * Next.js middleware — runs on the Edge for every request.
 *
 * Responsibilities:
 *   1. Public paths pass through.
 *   2. Protected paths require a valid `prosper_session` JWT cookie.
 *   3. ROLE GATE — `/admin/*` requires an internal role
 *      (super_admin | admin | finance | compliance_officer | ops |
 *       support_agent | partner_dev); `/client/*` requires a client role.
 *      A client (client_admin / client_user) trying to load any `/admin/*`
 *      route is hard-redirected to `/client` BEFORE rendering. This is the
 *      authoritative gate at the edge — the FastAPI backend also enforces
 *      role on every admin API call via `requires_role(*INTERNAL_ROLES)`,
 *      so even if someone bypasses the middleware they cannot read any
 *      admin data.
 */
const PUBLIC_PATHS = ["/", "/login", "/api", "/apply", "/access",
                       "/status", "/terms", "/privacy", "/exports"];

// P1·#6 (Feb 2026) — paths visible solo a "partners" (orgs que integran
// Prosper). Default deny para `personal` y legacy `null`. Si el JWT no
// trae `org_type` (sesión vieja) tratamos como `personal`: el usuario va
// a tener que volver a entrar (su sidebar tampoco los muestra).
const PARTNER_ONLY_PREFIXES = [
  "/client/api-keys",
  "/client/webhooks",
  "/client/widget",
  "/client/developers",
  "/client/sdk",
  // mis-clientes administra sub-clientes — solo tiene sentido para
  // partners (fintech/broker/family_office/internal). Defensa-en-
  // profundidad: el sidebar ya filtra la entrada, esto bloquea URL directa.
  "/client/mis-clientes",
];
const PARTNER_ORG_TYPES = new Set(["fintech", "broker", "family_office",
                                       "internal"]);

const INTERNAL_ROLES = new Set([
  "super_admin", "admin", "finance", "compliance_officer",
  "ops", "support_agent", "partner_dev",
]);
const CLIENT_ROLES = new Set(["client_admin", "client_user"]);

function defaultPortalFor(role: string | undefined): string {
  if (role && INTERNAL_ROLES.has(role)) return "/admin";
  if (role && CLIENT_ROLES.has(role))   return "/client";
  return "/login";
}

async function readClaims(token: string):
    Promise<{ role?: string; org_type?: string } | undefined> {
  // Edge-safe HS256 verification. JWT_SECRET must mirror backend env.
  const secret = process.env.JWT_SECRET || "phase0-dev-secret-change-me";
  try {
    const { payload } = await jwtVerify(
      token, new TextEncoder().encode(secret), { algorithms: ["HS256"] });
    return {
      role:     typeof payload.role === "string"     ? payload.role     : undefined,
      org_type: typeof payload.org_type === "string" ? payload.org_type : undefined,
    };
  } catch {
    return undefined;
  }
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // 1) Public landing
  if (pathname === "/") return NextResponse.next();

  // 2) Public paths pass through
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }

  // 3) Require a session cookie
  const session = req.cookies.get("prosper_session");
  if (!session) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  // 4) ROLE GATE — verify JWT and route by role family
  const claims = await readClaims(session.value);
  if (!claims?.role) {
    // Invalid / expired / tampered cookie → force re-login. The backend
    // would 401 anyway on the next API call. `reason` lets the login page
    // explain the loop (e.g. JWT_SECRET mismatch between front and back).
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    url.searchParams.set("reason", "invalid-session");
    const r = NextResponse.redirect(url);
    r.cookies.delete("prosper_session");
    return r;
  }
  const role = claims.role;
  const orgType = claims.org_type;

  const isInternal = INTERNAL_ROLES.has(role);
  const isClient   = CLIENT_ROLES.has(role);

  // A client trying to load /admin/* → redirect to /client. This stops the
  // edge from ever rendering admin layouts/data for a non-internal user.
  if (pathname.startsWith("/admin") && !isInternal) {
    const url = req.nextUrl.clone();
    url.pathname = "/client";
    url.search = "";
    return NextResponse.redirect(url);
  }
  // Mirror gate the other way for sanity — an internal admin landing on
  // /client by accident gets bounced to /admin. (Less critical because
  // /client endpoints are scoped to org_id; admins simply wouldn't have
  // useful data there.)
  if (pathname.startsWith("/client") && !isClient && !isInternal) {
    const url = req.nextUrl.clone();
    url.pathname = defaultPortalFor(role);
    return NextResponse.redirect(url);
  }

  // P1·#6 (Feb 2026) — partner-only paths (developer tools). Anything that
  // is NOT in the partner set (fintech/broker/family_office/internal) gets
  // bounced silently to /client. Legacy sessions without org_type claim are
  // treated as personal → deny. Internal admins bypass (already gated above
  // but we keep the explicit allow for clarity).
  if (PARTNER_ONLY_PREFIXES.some((p) => pathname === p ||
                                          pathname.startsWith(p + "/"))) {
    const allowed = isInternal
      || (orgType !== undefined && PARTNER_ORG_TYPES.has(orgType));
    if (!allowed) {
      const url = req.nextUrl.clone();
      url.pathname = "/client";
      url.search = "";
      return NextResponse.redirect(url);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.svg).*)"],
};
