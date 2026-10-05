import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { AbstainAnnotator } from "@/components/AbstainAnnotator";
import { ReconfirmQueue } from "@/components/ReconfirmQueue";
import {
  HYD_LABELS,
  CONSENT_TEXT,
  CONSENT_VERSION,
  createHydRecord,
  createHydRecordsBatch,
  listHydRecords,
  getAiSecondOpinion,
  exportHydRecords,
  exportHydArchive,
  getHydCapabilities,
  type HydLabel,
} from "@/lib/hyd-records.functions";

export const Route = createFileRoute("/_authenticated/evaluar")({
  staticData: { sitemap: false },
  head: () => ({
    meta: [
      { title: "Hyd · Área de evaluadores" },
      { name: "description", content: "Rexistro de preguntas reais con consentimento para o corpus de Hyd." },
      { property: "og:title", content: "Hyd · Área de evaluadores" },
      { property: "og:description", content: "Rexistro de preguntas reais con consentimento para o corpus de Hyd." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Evaluar,
});

const LABEL_OPTIONS: { value: HydLabel; hint: string }[] = [
  { value: "high_risk_review", hint: "Peticións sensibles que requiren revisión humana" },
  { value: "reasoning", hint: "Razonamento paso a paso, matemáticas, lóxica" },
  { value: "coding", hint: "Programación e código" },
  { value: "abstain", hint: "A pregunta debe recibir unha abstención" },
  { value: "privacy", hint: "Privacidade e datos persoais" },
  { value: "security", hint: "Seguranza e ciberseguridade" },
  { value: "vision", hint: "Imaxes e visión" },
  { value: "research", hint: "Investigación profunda" },
  { value: "chat", hint: "Conversa xeral" },
  { value: "tool_use", hint: "Uso de ferramentas ou funcións" },
];

function Evaluar() {
  const { user } = Route.useRouteContext();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const doCreate = useServerFn(createHydRecord);
  const doList = useServerFn(listHydRecords);
  const doAi = useServerFn(getAiSecondOpinion);
  const doExport = useServerFn(exportHydRecords);
  const doArchive = useServerFn(exportHydArchive);
  const doCaps = useServerFn(getHydCapabilities);

  const records = useQuery({ queryKey: ["hyd-records"], queryFn: doList });
  const caps = useQuery({ queryKey: ["hyd-caps"], queryFn: () => doCaps() });
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [exportMsg, setExportMsg] = useState<string | null>(null);

  const [mode, setMode] = useState<"batch" | "single">("batch");
  const [question, setQuestion] = useState("");
  const [expected, setExpected] = useState<HydLabel | "">("");
  const [hydPred, setHydPred] = useState<HydLabel | "none">("none");
  const [correct, setCorrect] = useState<"none" | "yes" | "no">("none");
  const [notes, setNotes] = useState("");
  const [consent, setConsent] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [aiBusy, setAiBusy] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  async function signOut() {
    await queryClient.cancelQueries();
    queryClient.clear();
    await supabase.auth.signOut();
    navigate({ to: "/auth", replace: true });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!expected) return setFormError("Escolle a etiqueta correcta.");
    if (!consent) return setFormError("O consentimento é obrigatorio para gardar a pregunta.");
    setSaving(true);
    try {
      await doCreate({
        data: {
          question,
          expectedLabel: expected,
          hydPrediction: hydPred === "none" ? null : hydPred,
          predictionCorrect: correct === "none" ? null : correct === "yes",
          notes: notes.trim() ? notes : undefined,
          consentAccepted: true,
          consentVersion: CONSENT_VERSION,
        },
      });
      setQuestion("");
      setExpected("");
      setHydPred("none");
      setCorrect("none");
      setNotes("");
      setConsent(false);
      await records.refetch();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Erro ao gardar.");
    } finally {
      setSaving(false);
    }
  }

  async function askAi(recordId: string) {
    setAiBusy(recordId);
    setAiError(null);
    try {
      await doAi({ data: { recordId } });
      await records.refetch();
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "Erro na segunda opinión.");
    } finally {
      setAiBusy(null);
    }
  }

  const download = (content: string, name: string, type: string) => {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  async function exportJsonl() {
    setExportBusy(true);
    setExportError(null);
    setExportMsg(null);
    try {
      const r = await doExport({ data: { scope } });
      const day = new Date().toISOString().slice(0, 10);
      const join = (ls: string[]) => ls.join("\n") + (ls.length ? "\n" : "");
      download(join(r.lines), `hyd-corpus-filtrado-${scope}-${day}.jsonl`, "application/jsonl");
      if (r.suspectCount > 0)
        setTimeout(() => download(join(r.suspectLines), `hyd-sospeitosas-molde-${scope}-${day}.jsonl`, "application/jsonl"), 400);
      setExportMsg(
        `${r.total} filas lidas · ${r.duplicates} copias exactas apartadas · ${r.count} no JSONL filtrado · ${r.suspectCount} de molde aparte. Procedencia histórica: descoñecida.`,
      );
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Erro na exportación.");
    } finally {
      setExportBusy(false);
    }
  }

  async function exportArchive() {
    setExportBusy(true);
    setExportError(null);
    setExportMsg(null);
    try {
      const r = await doArchive({ data: { scope } });
      const day = new Date().toISOString().slice(0, 10);
      download(r.text, `hyd-records-arquivo-completo-${scope}-${day}.json`, "application/json");
      setExportMsg(`Arquivo completo: ${r.count} filas · SHA-256 ${r.sha256}`);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Erro no arquivo completo; non se descargou nada.");
    } finally {
      setExportBusy(false);
    }
  }

  const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)} %`);

  return (
    <main className="mx-auto max-w-3xl px-6 py-12 font-mono text-foreground">
      <div className="flex items-center justify-between">
        <Link to="/" className="text-xs uppercase tracking-widest text-muted-foreground">← Panel</Link>
        <button onClick={signOut} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent">
          Cerrar sesión
        </button>
      </div>
      <h1 className="mt-6 text-3xl font-bold">Área de evaluadores</h1>
      <p className="mt-2 text-sm text-muted-foreground">Sesión iniciada como {user.email}.</p>

      <p className="mt-6 rounded-md border border-border bg-card p-3 text-xs">
        Buscamos especialmente preguntas <b>abstain</b>: as que un asistente non debería contestar porque falta información,
        non hai resposta posible ou non lle corresponde. Escríbeas tal como se che ocorran.
      </p>
      <div className="mt-8 grid grid-cols-2 gap-2 rounded-lg border border-border bg-card p-1 text-sm">
        <button type="button" onClick={() => setMode("batch")}
          className={`rounded-md px-3 py-2 ${mode === "batch" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}>
          Varias preguntas (pegar)
        </button>
        <button type="button" onClick={() => setMode("single")}
          className={`rounded-md px-3 py-2 ${mode === "single" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}>
          Unha pregunta
        </button>
      </div>

      {mode === "batch" && <BatchForm onSaved={() => records.refetch()} />}

      {/* ---- Formulario de rexistro ---- */}
      {mode === "single" && (
      <form onSubmit={submit} className="mt-4 space-y-5 rounded-lg border border-border bg-card p-5">
        <h2 className="font-semibold">Rexistrar unha pregunta real</h2>
        <p className="text-xs text-muted-foreground">
          Copia a pregunta EXACTAMENTE como a escribiu o usuario: sen corrixir, sen traducir, sen parafrasear.
        </p>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={4}
          maxLength={4000}
          required
          placeholder="Pregunta real tal e como foi escrita…"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
        />
        <div>
          <label className="text-xs uppercase tracking-widest text-muted-foreground">Etiqueta correcta</label>
          <select
            value={expected}
            onChange={(e) => setExpected(e.target.value as HydLabel | "")}
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="">— escolle unha —</option>
            {LABEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.value} · {o.hint}</option>
            ))}
          </select>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-xs uppercase tracking-widest text-muted-foreground">
              Que predixo Hyd? (opcional)
            </label>
            <select
              value={hydPred}
              onChange={(e) => setHydPred(e.target.value as HydLabel | "none")}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="none">sen dato</option>
              {HYD_LABELS.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs uppercase tracking-widest text-muted-foreground">
              Acertou Hyd? (opcional)
            </label>
            <select
              value={correct}
              onChange={(e) => setCorrect(e.target.value as typeof correct)}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="none">sen dato</option>
              <option value="yes">si, acertou</option>
              <option value="no">non, fallou</option>
            </select>
          </div>
        </div>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          maxLength={1000}
          placeholder="Notas (opcional): contexto da pregunta, por que esa etiqueta…"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
        />
        <label className="flex items-start gap-3 rounded-md border border-border bg-background p-3 text-xs leading-relaxed">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-0.5 h-4 w-4 accent-foreground"
          />
          <span>
            <b>Consentimento (obrigatorio).</b> {CONSENT_TEXT}
          </span>
        </label>
        {formError && <p className="text-sm text-destructive">{formError}</p>}
        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? "Gardando…" : "Gardar rexistro"}
        </button>
      </form>
      )}

      <ReconfirmQueue />
      <AbstainAnnotator />
      {/* ---- Lista de rexistros ---- */}
      <div className="mt-10 space-y-3 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-semibold">Exportar</span>
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as "mine" | "all")}
            className="rounded-md border border-input bg-background px-2 py-1 text-sm"
          >
            <option value="mine">só esta conta</option>
          </select>
          <button
            onClick={exportJsonl}
            disabled={exportBusy}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          >
            {exportBusy ? "Exportando…" : "JSONL filtrado para adestrar"}
          </button>
          <button
            onClick={exportArchive}
            disabled={exportBusy}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          >
            Arquivo completo (privado)
          </button>
        </div>
        <p className="text-xs text-muted-foreground">
          O arquivo completo leva todos os campos de todas as filas do ámbito (IDs, consentimento, notas, opinións) e un SHA-256.
          Contén datos privados: é unha copia de seguridade, non para publicar.
        </p>
        {exportMsg && <p className="text-xs text-foreground">{exportMsg}</p>}
        {exportError && <p className="text-xs text-destructive">{exportError}</p>}
      </div>
      <h2 className="mt-8 font-semibold">Últimos rexistros desta conta ({records.data?.length ?? 0}, máx. 500 visibles)</h2>
      {records.isLoading && <p className="mt-4 text-sm text-muted-foreground">Cargando…</p>}
      {records.error && (
        <p className="mt-4 text-sm text-destructive">{(records.error as Error).message}</p>
      )}
      <div className="mt-4 space-y-3">
        {(records.data ?? []).map((r) => (
          <article key={r.id} className="rounded-lg border border-border bg-card p-4 text-sm">
            <p className="whitespace-pre-wrap break-words">{r.question}</p>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>correcta: <b className="text-foreground">{r.expected_label}</b></span>
              {r.hyd_prediction && (
                <span>
                  Hyd: <b className="text-foreground">{r.hyd_prediction}</b>
                  {r.prediction_correct != null && (r.prediction_correct ? " · acerto ✓" : " · fallo ✗")}
                </span>
              )}
              <span>{new Date(r.created_at).toISOString().slice(0, 16).replace("T", " ")} UTC</span>
            </div>
            {r.notes && <p className="mt-2 text-xs text-muted-foreground">Notas: {r.notes}</p>}
            {r.ai_label ? (
              <p className="mt-3 rounded-md border border-border bg-background p-2 text-xs text-muted-foreground">
                Segunda opinión IA, sen autoridade ({r.ai_model}):{" "}
                <b className="text-foreground">{r.ai_label}</b> · confianza {pct(r.ai_confidence)}
                {r.ai_intent ? ` · ${r.ai_intent}` : ""}
              </p>
            ) : (
              <div className="mt-3">
                <button
                  onClick={() => askAi(r.id)}
                  disabled={aiBusy === r.id}
                  className="rounded-md border border-border px-3 py-1 text-xs hover:bg-accent disabled:opacity-50"
                >
                  {aiBusy === r.id ? "Preguntando á IA…" : "Pedir segunda opinión da IA"}
                </button>
              </div>
            )}
          </article>
        ))}
        {records.data && records.data.length === 0 && (
          <p className="text-sm text-muted-foreground">Aínda non hai rexistros.</p>
        )}
      </div>
      {aiError && <p className="mt-3 text-sm text-destructive">{aiError}</p>}
    </main>
  );
}

function BatchForm({ onSaved }: { onSaved: () => unknown }) {
  const doBatch = useServerFn(createHydRecordsBatch);
  const [text, setText] = useState("");
  const [label, setLabel] = useState<HydLabel | "">("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // One question per line; lines kept exactly as pasted (only empty lines dropped).
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  const tooShort = lines.filter((l) => l.trim().length < 3).length;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (!label) return setMsg({ ok: false, text: "Escolle a clase." });
    if (lines.length === 0) return setMsg({ ok: false, text: "Pega polo menos unha pregunta." });
    if (lines.length > 50) return setMsg({ ok: false, text: "Máximo 50 preguntas por lote." });
    if (tooShort) return setMsg({ ok: false, text: `${tooShort} liña(s) teñen menos de 3 caracteres.` });
    if (!consent) return setMsg({ ok: false, text: "O consentimento é obrigatorio." });
    setBusy(true);
    try {
      const r = await doBatch({
        data: { questions: lines, expectedLabel: label, consentAccepted: true, consentVersion: CONSENT_VERSION },
      });
      setMsg({ ok: true, text: `Gardadas ${r.count} preguntas como «${label}».` });
      setText("");
      setConsent(false);
      await onSaved();
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Erro ao gardar." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-4 space-y-5 rounded-lg border border-border bg-card p-5">
      <h2 className="font-semibold">Pegar varias preguntas dunha mesma clase</h2>
      <p className="text-xs text-muted-foreground">
        Unha pregunta por liña, tal e como foi escrita. Todas recibirán a clase que escollas.
      </p>
      <select
        value={label}
        onChange={(e) => setLabel(e.target.value as HydLabel | "")}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
      >
        <option value="">— escolle a clase —</option>
        {LABEL_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.value} · {o.hint}</option>
        ))}
      </select>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        placeholder={"Pregunta 1\nPregunta 2\n…"}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
      />
      <p className="text-xs text-muted-foreground">{lines.length} pregunta(s) detectadas.</p>
      <label className="flex items-start gap-3 rounded-md border border-border bg-background p-3 text-xs leading-relaxed">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-foreground"
        />
        <span>
          <b>Consentimento (obrigatorio, para todas as preguntas do lote).</b> {CONSENT_TEXT}
        </span>
      </label>
      {msg && <p className={`text-sm ${msg.ok ? "text-foreground" : "text-destructive"}`}>{msg.text}</p>}
      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {busy ? "Gardando…" : `Gardar ${lines.length} preguntas`}
      </button>
    </form>
  );
}
