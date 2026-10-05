import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { supabase } from "@/integrations/supabase/client";
import { lovable } from "@/integrations/lovable/index";

export const Route = createFileRoute("/auth")({
  staticData: { sitemap: false },
  head: () => ({
    meta: [
      { title: "Hyd · Acceso de evaluadores" },
      { name: "description", content: "Inicia sesión o crea tu cuenta de evaluador de Hyd." },
      { property: "og:title", content: "Hyd · Acceso de evaluadores" },
      { property: "og:description", content: "Acceso para evaluadores del enrutador Hyd." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (data.user) navigate({ to: "/evaluar", replace: true });
    });
  }, [navigate]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    if (mode === "in") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) setMsg(error.message);
      else navigate({ to: "/evaluar", replace: true });
    } else {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: window.location.origin + "/auth" },
      });
      setMsg(error ? error.message : "Revisa tu correo y confirma la cuenta para entrar.");
    }
    setBusy(false);
  }

  async function google() {
    setMsg(null);
    const result = await lovable.auth.signInWithOAuth("google", { redirect_uri: window.location.origin + "/auth" });
    if (result.error) { setMsg(String(result.error.message ?? result.error)); return; }
    if (result.redirected) return;
    navigate({ to: "/evaluar", replace: true });
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6 font-mono text-foreground">
      <div className="w-full max-w-sm rounded-lg border border-border bg-card p-6">
        <p className="text-xs uppercase tracking-widest text-muted-foreground">HYDRA · Hyd</p>
        <h1 className="mt-2 text-2xl font-bold">{mode === "in" ? "Iniciar sesión" : "Crear cuenta"}</h1>
        <button onClick={google} className="mt-6 w-full rounded-md border border-border px-4 py-2 text-sm hover:bg-accent">
          Continuar con Google
        </button>
        <div className="my-4 text-center text-xs text-muted-foreground">o con email</div>
        <form onSubmit={submit} className="space-y-3">
          <input type="email" required placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" />
          <input type="password" required minLength={8} placeholder="contraseña (mín. 8)" value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" />
          <button disabled={busy} className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {mode === "in" ? "Entrar" : "Registrarme"}
          </button>
        </form>
        {msg && <p className="mt-3 text-sm text-muted-foreground">{msg}</p>}
        <button onClick={() => { setMode(mode === "in" ? "up" : "in"); setMsg(null); }}
          className="mt-4 text-xs text-muted-foreground underline">
          {mode === "in" ? "¿No tienes cuenta? Regístrate" : "¿Ya tienes cuenta? Inicia sesión"}
        </button>
      </div>
    </main>
  );
}
