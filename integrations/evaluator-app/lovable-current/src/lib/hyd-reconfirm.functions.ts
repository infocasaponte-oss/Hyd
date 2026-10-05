// Human reconfirmation queue for abstain marks changed by an AI assistant (HYD-023).
// Owner-only via RLS. Never touches hyd_records or hyd_abstain_annotations.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";

export type ReconfirmItem = {
  id: string;
  question: string;
  ai_kind: string;
  status: string;
  confirmed_kind: string | null;
};

export const listMyReconfirm = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { data, error } = await context.supabase
      .from("hyd_abstain_reconfirm_queue")
      .select("id,ai_kind,status,confirmed_kind,record_id,hyd_records(question)")
      .order("created_at")
      .limit(1000);
    if (error) throw new Error(`Non se puido ler a cola: ${error.message}`);
    return (data ?? []).map((r): ReconfirmItem => ({
      id: r.id,
      ai_kind: r.ai_kind,
      status: r.status,
      confirmed_kind: r.confirmed_kind,
      question: (r.hyd_records as { question: string } | null)?.question ?? "",
    }));
  });

export const confirmMark = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((d) =>
    z.object({ id: z.string().uuid(), kind: z.enum(["dangerous", "missing_context", "unsure"]) }).parse(d),
  )
  .handler(async ({ data, context }) => {
    const { error, data: rows } = await context.supabase
      .from("hyd_abstain_reconfirm_queue")
      .update({
        status: "reviewed",
        confirmed_kind: data.kind,
        confirmed_by: context.userId,
        confirmed_at: new Date().toISOString(),
      })
      .eq("id", data.id)
      .select("id");
    if (error) throw new Error(`Non se puido gardar: ${error.message}`);
    if (!rows?.length) throw new Error("Esta marca non é túa ou non existe.");
    return { ok: true };
  });
