import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { listMyReconfirm, confirmMark } from "@/lib/hyd-reconfirm.functions";
import { Button } from "@/components/ui/button";

const LABEL: Record<string, string> = {
  dangerous: "Perigosa",
  missing_context: "Falta de contexto",
  unsure: "Non estou seguro/a",
};

export function ReconfirmQueue() {
  const list = useServerFn(listMyReconfirm);
  const confirm = useServerFn(confirmMark);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["reconfirm"], queryFn: () => list() });
  const m = useMutation({
    mutationFn: (v: { id: string; kind: "dangerous" | "missing_context" | "unsure" }) => confirm({ data: v }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reconfirm"] }),
  });
  const items = q.data ?? [];
  if (q.isLoading) return null;
  if (q.error) return <p className="mt-6 text-sm text-destructive">{(q.error as Error).message}</p>;
  if (!items.length) return null;
  const pending = items.filter((i) => i.status === "pending").length;

  return (
    <section className="mt-8 rounded-lg border border-border p-5 text-sm">
      <h2 className="font-semibold">Reconfirmar marcas cambiadas pola IA</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Un asistente de IA cambiou o tipo destas abstain túas. Non sabemos o que puxeras ti orixinalmente.
        Di que tipo é para ti. Ata que confirmes, só se usan como diagnóstico, sen validez humana.
        Pendentes: {pending} de {items.length}.
      </p>
      {m.error && <p className="mt-2 text-xs text-destructive">{(m.error as Error).message}</p>}
      <ul className="mt-4 space-y-3">
        {items.map((i) => (
          <li key={i.id} className="rounded-md border border-border p-3">
            <p className="whitespace-pre-wrap">{i.question}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              IA puxo: {LABEL[i.ai_kind]}
              {i.status === "reviewed" && <> · Ti confirmaches: <b>{LABEL[i.confirmed_kind ?? ""]}</b></>}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {(["dangerous", "missing_context", "unsure"] as const).map((k) => (
                <Button
                  key={k}
                  size="sm"
                  variant={i.confirmed_kind === k ? "default" : "outline"}
                  disabled={m.isPending}
                  onClick={() => m.mutate({ id: i.id, kind: k })}
                >
                  {LABEL[k]}
                </Button>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
