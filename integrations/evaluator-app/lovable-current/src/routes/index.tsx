import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { supabase } from "@/integrations/supabase/client";
import { getCorpusStats } from "@/lib/hyd-stats.functions";
import T from "@/data/hyd-training.json";
import I from "@/data/hyd-independent.json";
import R from "@/data/hyd-e3.json";
import RA from "@/data/hyd-e3-annotated.json";

type Pr = { precision: number | null; recall: number | null; false_alarm: number | null };
type AnnRow = { who: string; kind: "dangerous" | "missing_context"; n: number; neg_n: number; measured: boolean; e3: Pr; e2: Pr };
const annRows = RA.rows as unknown as AnnRow[];
const p0 = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)} %`);

function SessionLink() {
  const [email, setEmail] = useState<string | null>(null);
  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => setEmail(data.user?.email ?? null));
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setEmail(s?.user?.email ?? null));
    return () => data.subscription.unsubscribe();
  }, []);
  return (
    <Link to={email ? "/evaluar" : "/auth"} className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-accent">
      {email ? `Área de evaluadores · ${email}` : "Entrar como evaluador"}
    </Link>
  );
}

export const Route = createFileRoute("/")({
  staticData: { sitemap: true },
  head: () => ({
    meta: [
      { title: "Hyd · Panel de calibración" },
      { name: "description", content: "Resultados de calibración e adestramento do enrutador Hyd de HYDRA." },
      { property: "og:title", content: "Hyd · Panel de calibración" },
      { property: "og:description", content: "Cobertura, acerto e historial de cambios dos candidatos de Hyd." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Index,
});

const pct = (v: number) => `${(v * 100).toFixed(1)} %`;
// Fixed UTC format so server and browser render the same text.
const fmt = (iso: string) => (iso ? new Date(iso).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "—");

function Index() {
  const fetchStats = useServerFn(getCorpusStats);
  const { data: s, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["corpus-stats"],
    queryFn: () => fetchStats(),
    refetchInterval: 60_000,
  });
  const max = s ? Math.max(1, ...Object.values(s.perClass)) : 1;
  const classes = s ? Object.entries(s.perClass).sort((a, b) => b[1] - a[1]) : [];

  return (
    <main className="mx-auto max-w-5xl px-6 py-12 font-mono text-foreground">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-widest text-muted-foreground">HYDRA · Hyd · SHADOW_ONLY</p>
        <SessionLink />
      </div>
      <h1 className="mt-2 text-3xl font-bold">Panel de calibración</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Datos reais en directo da base de datos dos avaliadores. Actualízase cada minuto.
      </p>

      {isLoading && <p className="mt-10 text-sm text-muted-foreground">Cargando datos reais…</p>}
      {error && <p className="mt-10 text-sm text-destructive">Non se puideron ler os datos: {String((error as Error).message)}</p>}

      {s && (
        <>
          <section className="mt-10 grid gap-4 sm:grid-cols-5">
            {[
              ["Rexistros", s.total],
              ["Distintos", s.distinct],
              ["De molde (apartados)", s.suspect],
              ["Pasan o filtro técnico (procedencia descoñecida)", s.valid],
              ["Conflitos de etiqueta", s.conflicts],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-border bg-card p-4">
                <div className="text-xs text-muted-foreground">{k}</div>
                <div className="mt-1 text-2xl font-bold">{Number(v).toLocaleString("gl-ES")}</div>
              </div>
            ))}
          </section>

          <section className="mt-6 rounded-lg border border-border bg-card p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-semibold">Pasan o filtro técnico, por clase</h2>
              <button onClick={() => refetch()} className="text-xs underline text-muted-foreground">
                {isFetching ? "actualizando…" : "actualizar agora"}
              </button>
            </div>
            <div className="mt-4 space-y-2">
              {classes.map(([l, n]) => (
                <div key={l} className="grid grid-cols-[10rem_1fr_7rem] items-center gap-3 text-xs">
                  <span>{l}</span>
                  <div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${(n / max) * 100}%` }} /></div>
                  <span className="text-right">{n} · {s.valid ? pct(n / s.valid) : "—"}</span>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-muted-foreground">
              Último rexistro: {fmt(s.lastAt)} · lido: {fmt(s.generatedAt)}
            </p>
          </section>
        </>
      )}

      <section className="mt-6 rounded-lg border border-border p-5 text-sm leading-relaxed">
        <h2 className="font-semibold">Comparativa diagnóstica · Hyd actual vs E2</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Os dous adestrados coas mesmas {T.n_train} preguntas, calibrados con {T.n_calibration} e medidos sobre {T.test_n} preguntas
          apartadas. {T.corpus}. Resultado diagnóstico, non validación. Estado: <b>{T.status}</b> — ningún toma decisións.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {[T.current, T.e2].map((m) => (
            <div key={m.name} className="rounded-md border border-border bg-card p-4">
              <div className="font-semibold">{m.name}</div>
              <div className="text-xs text-muted-foreground">{m.desc}</div>
              <div className="text-xs text-muted-foreground">Adestrado: {fmt(m.trained_at)}</div>
              <ul className="mt-3 space-y-1 text-xs">
                <li>Acerto: <b>{pct(m.accuracy)}</b></li>
                <li>Macro-F1: <b>{m.macro_f1.toFixed(3)}</b></li>
                <li>ECE (calibración, menor é mellor): <b>{m.ece.toFixed(3)}</b></li>
                <li>Con confianza ≥ 0,85: decide no {pct(m.at085.coverage)} · acerta <b>{pct(m.at085.accuracy)}</b></li>
              </ul>
            </div>
          ))}
        </div>
        <h3 className="mt-5 text-xs font-semibold">F1 por clase (gris = Hyd actual, escuro = E2)</h3>
        <div className="mt-2 space-y-2">
          {Object.keys(T.current.per_class).map((l) => {
            const a = (T.current.per_class as Record<string, number>)[l] ?? 0;
            const b = (T.e2.per_class as Record<string, number>)[l] ?? 0;
            return (
              <div key={l} className="grid grid-cols-[10rem_1fr_7rem] items-center gap-3 text-xs">
                <span>{l}</span>
                <div className="space-y-1">
                  <div className="h-1.5 rounded bg-muted"><div className="h-1.5 rounded bg-muted-foreground/50" style={{ width: `${a * 100}%` }} /></div>
                  <div className="h-1.5 rounded bg-muted"><div className="h-1.5 rounded bg-primary" style={{ width: `${b * 100}%` }} /></div>
                </div>
                <span className="text-right">{a.toFixed(2)} → <b>{b.toFixed(2)}</b></span>
              </div>
            );
          })}
        </div>
        <p className="mt-4 text-xs text-muted-foreground">
          Con {T.test_n} preguntas de proba (~30 por clase), diferenzas de menos de 8 puntos nunha clase non son concluíntes.
          A proba vén dos mesmos avaliadores que o adestramento: non é aínda evidencia independente.
        </p>
      </section>

      <section className="mt-6 rounded-lg border border-border p-5 text-sm leading-relaxed">
        <h2 className="font-semibold">Avaliación independente de E2 · persoas que non participaron no adestramento</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Só conta preguntas de contas novas, distintas das que crearon o corpus de adestramento, e quita as que xa estaban nel.
          Estado: <b>{I.status}</b> — E2 non toma decisións.
        </p>
        <ul className="mt-3 space-y-1 text-xs">
          <li>Persoas (contas) externas: <b>{s?.external?.accounts ?? "—"}</b></li>
          <li>Preguntas externas: <b>{s?.external?.questions ?? "—"}</b></li>
          <li>Delas, abstain: <b>{s?.external?.perClass["abstain"] ?? "—"}</b></li>
        </ul>
        <p className="mt-3 text-xs">
          Medido: <b>{fmt(I.measured_at)}</b> · {I.counts.rows} filas → {I.counts.copies} copias, {I.counts.mould_excluded} de molde apartadas → <b>{I.counts.evaluated}</b> avaliadas.
          E2: {I.models.e2} · Hyd actual: {I.models.hyd}.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr className="text-left">
                <th className="py-1">Quen</th><th>Preguntas</th><th>Acerto E2 / Hyd</th><th>Macro-F1 E2 / Hyd</th><th>abstain (n)</th><th>abstain F1 E2 / Hyd</th><th>abstain P·R E2</th>
              </tr>
            </thead>
            <tbody>
              {I.rows.map((r) => (
                <tr key={r.who} className="border-t border-border">
                  <td className="py-1 font-semibold">{r.who}</td>
                  <td>{r.n}</td>
                  <td><b>{pct(r.e2.acc)}</b> / {pct(r.hyd.acc)}</td>
                  <td><b>{r.e2.f1.toFixed(2)}</b> / {r.hyd.f1.toFixed(2)}</td>
                  <td>{r.abstain_n}</td>
                  <td><b>{r.e2.abs_f1.toFixed(2)}</b> / {r.hyd.abs_f1.toFixed(2)}</td>
                  <td>{r.e2.abs_p.toFixed(2)} · {r.e2.abs_r.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
          {I.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </section>

      <section className="mt-6 rounded-lg border border-border p-5 text-sm leading-relaxed">
        <h2 className="font-semibold">Especialista de risco E3 · abstain perigosas (persoas externas)</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {R.model} · adestrado {fmt(R.trained_at)} · medido {fmt(R.measured_at)} · Estado: <b>{R.status}</b> — só observa, non decide.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr className="text-left">
                <th className="py-1">Quen</th><th>Perigosas</th><th>Vistas como abstain E3 / E2</th><th>Marcadas con algún risco E3 / E2</th><th>Falsas alarmas E3 / E2</th>
              </tr>
            </thead>
            <tbody>
              {R.rows.map((r) => (
                <tr key={r.who} className="border-t border-border">
                  <td className="py-1 font-semibold">{r.who}</td>
                  <td>{r.dang}</td>
                  <td><b>{pct(r.e3_abs)}</b> / {pct(r.e2_abs)}</td>
                  <td><b>{pct(r.e3_risk)}</b> / {pct(r.e2_risk)}</td>
                  <td><b>{pct(r.e3_fp)}</b> / {pct(r.e2_fp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
          {R.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </section>

      <section className="mt-6 rounded-lg border border-border p-5 text-sm leading-relaxed">
        <h2 className="font-semibold">E3 por tipo de abstain · marcas humanas</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Usa só as marcas «perigosa» / «falta de contexto» que cada persoa externa pon nas súas abstain en /evaluar. Molde apartado.
          Medido {fmt(RA.measured_at)} · {RA.annotations} marcas · Estado: <b>{RA.status}</b> — só observa.
        </p>
        {annRows.length === 0 ? (
          <p className="mt-3 text-xs text-muted-foreground">{(RA as { blocked_reason?: string }).blocked_reason ?? "Sen medir: aínda non hai marcas de persoas externas."}</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="text-left">
                  <th className="py-1">Quen</th><th>Tipo</th><th>n</th><th>Precisión E3 / E2</th><th>Recall E3 / E2</th><th>Falsas alarmas E3 / E2</th>
                </tr>
              </thead>
              <tbody>
                {annRows.map((r) => (
                  <tr key={r.who + r.kind} className="border-t border-border">
                    <td className="py-1 font-semibold">{r.who}</td>
                    <td>{r.kind === "dangerous" ? "perigosa" : "falta de contexto"}</td>
                    <td>{r.n}{r.measured ? "" : " (poucas)"}</td>
                    <td><b>{p0(r.e3.precision)}</b> / {p0(r.e2.precision)}</td>
                    <td><b>{p0(r.e3.recall)}</b> / {p0(r.e2.recall)}</td>
                    <td><b>{p0(r.e3.false_alarm)}</b> / {p0(r.e2.false_alarm)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-muted-foreground">
          Recall: abstain dese tipo que o modelo ve como abstain. Precisión: das que marca abstain, cantas son dese tipo. Falsas alarmas: preguntas doutras clases marcadas abstain. Con menos de {RA.min_n} marcas non é concluínte.
        </p>
      </section>
    </main>
  );
}
