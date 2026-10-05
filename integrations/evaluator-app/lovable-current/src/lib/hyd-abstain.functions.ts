// Human annotation of abstain type (dangerous vs missing_context). Separate table;
// the original record (question, label) is never modified. Owner-only via RLS.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";

export type AbstainKind = "dangerous" | "missing_context";
export type AbstainItem = { id: string; question: string; created_at: string; kind: AbstainKind | null };

export const listMyAbstain = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { supabase, userId } = context;
    const rows: { id: string; question: string; created_at: string }[] = [];
    let after: string | null = null;
    for (;;) {
      let q = supabase.from("hyd_records").select("id,question,created_at")
        .eq("user_id", userId).eq("expected_label", "abstain").order("id").limit(1000);
      if (after) q = q.gt("id", after);
      const { data, error } = await q;
      if (error) throw new Error(`Non se puideron ler as abstain: ${error.message}`);
      rows.push(...(data ?? []));
      if (!data || data.length < 1000) break;
      after = data[data.length - 1]!.id;
    }
    const kinds = new Map<string, AbstainKind>();
    after = null;
    for (;;) {
      let q = supabase.from("hyd_abstain_annotations").select("id,record_id,kind").order("id").limit(1000);
      if (after) q = q.gt("id", after);
      const { data, error } = await q;
      if (error) throw new Error(`Non se puideron ler as marcas: ${error.message}`);
      for (const a of data ?? []) kinds.set(a.record_id, a.kind as AbstainKind);
      if (!data || data.length < 1000) break;
      after = data[data.length - 1]!.id;
    }
    rows.sort((a, b) => a.created_at.localeCompare(b.created_at));
    return rows.map((r): AbstainItem => ({ ...r, kind: kinds.get(r.id) ?? null }));
  });

export const setAbstainKind = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((d) =>
    z.object({ recordId: z.string().uuid(), kind: z.enum(["dangerous", "missing_context"]).nullable() }).parse(d),
  )
  .handler(async ({ data, context }) => {
    const { supabase, userId } = context;
    if (data.kind === null) {
      const { error } = await supabase.from("hyd_abstain_annotations").delete().eq("record_id", data.recordId);
      if (error) throw new Error(`Non se puido quitar a marca: ${error.message}`);
      return { ok: true };
    }
    const { error } = await supabase.from("hyd_abstain_annotations").upsert(
      { record_id: data.recordId, user_id: userId, kind: data.kind, updated_at: new Date().toISOString() },
      { onConflict: "record_id" },
    );
    if (error) throw new Error(`Non se puido gardar a marca: ${error.message}`);
    return { ok: true };
  });
