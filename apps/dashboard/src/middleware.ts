import { NextRequest, NextResponse } from "next/server";
import { CONTROL_PLANE_INTERNAL_URL } from "@/lib/config";

const PUBLIC_PATHS = ["/login"];

// Runs server-side, so this fetch to the Control Plane is server-to-server
// (no browser CORS involved) — it just forwards the incoming cookie header
// and asks "is this session valid?" before letting the request through.
export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
    return NextResponse.next();
  }

  const cookieHeader = request.headers.get("cookie");
  const response = await fetch(`${CONTROL_PLANE_INTERNAL_URL}/auth/me`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });

  if (response.ok) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
