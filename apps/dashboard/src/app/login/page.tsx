"use client";

import { type FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CONTROL_PLANE_URL } from "@/lib/config";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    let response: Response;
    try {
      response = await fetch(`${CONTROL_PLANE_URL}/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
    } catch {
      setSubmitting(false);
      setError("Could not reach the Control Plane.");
      return;
    }

    setSubmitting(false);

    if (!response.ok) {
      setError("Invalid email or password.");
      return;
    }

    // Only ever redirect same-origin: `next` comes from a query param an
    // attacker could craft into a shared link (middleware.ts always sets a
    // safe one itself, but nothing stops a hand-crafted
    // `/login?next=https://evil.example` from being shared).
    const rawNext = searchParams.get("next");
    const next = rawNext && rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";
    router.push(next);
    router.refresh();
  }

  return (
    <div className="healer-login">
      <form className="healer-login-card" onSubmit={handleSubmit}>
        <div className="healer-login-brand">Healer</div>
        <p className="healer-page-description">Sign in to manage servers and deployments.</p>

        <label className="healer-field">
          Email
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        <label className="healer-field">
          Password
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        {error && <div className="healer-error">{error}</div>}

        <button type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
