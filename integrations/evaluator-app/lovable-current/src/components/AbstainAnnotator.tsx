import { useQuery } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { listMyAbstain, setAbstainKind, type AbstainKind } from "@/lib/hyd-abstain.functions";

export function AbstainAnnotator() {
  const doList = useServerFn(listMyAbstain);
  const doSet = useServerFn(setAbstainKind);
  const q = useQuery({ queryKey: ["hyd-abstain"], queryFn: () => doList() });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [onlyPending, setOnlyPending] = useState(true);

  async function mark(id: string, kind: AbstainKind | null) {
    setBusy(id);
    setErr(null);
    try {
      await doSet({ data: { recordId: id, kind } });
      await q.refetch();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Erro ao gardar a marca.");
    } finally {
      setBusy(null);
    }
  }

  const items = q.data ?? [];
  const done = items.filter((i) => i.kind).length;
  const shown = (onlyPending ? items.filter((i) => !i.kind) : items).slice(0, 100);

  return (
    <section className="mt-10 rounded-lg border border-border bg-card p-5 text-sm">
      <h2 className="font-semibold">Tipo de abstain</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Marca cada abstain túa: <b>perigosa</b> (petición daniña ou ilegal) ou <b>falta de contexto</b> (non se pode
        contestar sen información que o asistente non ten). A pregunta non se cambia; a marca gárdase aparte.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
        <span>{done} de {items.length} marcadas</span>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={onlyPending} onChange={(e) => setOnlyPending(e.target.checked)} />
          só sen marcar
        </label>
      </div>
      {q.isLoading && <p className="mt-3 text-xs text-muted-foreground">Cargando…</p>}
      {q.error && <p className="mt-3 text-xs text-destructive">{(q.error as Error).message}</p>}
      {err && <p className="mt-3 text-xs text-destructive">{err}</p>}
      <div className="mt-3 space-y-2">
        {shown.map((i) => (
          <div key={i.id} className="rounded-md border border-border bg-background p-3">
            <p className="whitespace-pre-wrap break-words text-sm">{i.question}</p>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              {(["dangerous", "missing_context"] as const).map((k) => (
                <button key={k} type="button" disabled={busy === i.id} onClick={() => mark(i.id, i.kind === k ? null : k)}
                  className={`rounded-md border border-border px-3 py-1 disabled:opacity-50 ${i.kind === k ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}>
                  {k === "dangerous" ? "Perigosa" : "Falta de contexto"}
                </button>
              ))}
            </div>
          </div>
        ))}
        {q.data && shown.length === 0 && <p className="text-xs text-muted-foreground">Non hai abstain pendentes.</p>}
      </div>
    </section>
  );
}
