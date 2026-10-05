// Server functions for the Hyd evaluator workflow.
// Records of REAL user questions, consented and signed by the evaluator
// account. The question is always stored verbatim — never rewritten.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";
import {
  HYD_LABELS,
  CONSENT_TEXT,
  recordInput,
  batchInput,
  exportScope,
  buildArchive,
  type HydLabel,
} from "./hyd-contract";
export { HYD_LABELS, CONSENT_TEXT, CONSENT_VERSION } from "./hyd-contract";
export type { HydLabel } from "./hyd-contract";

// Owner-only: exports read with the caller's own session, so the existing
// owner RLS policies decide what is visible. No admin / cross-account scope.
async function readAll(scope: "mine" | "all", userId: string, userClient: unknown, cutoff: string) {
  if (scope !== "mine") throw new Error("Só se pode exportar a propia conta.");
  const client = userClient as typeof import("@/integrations/supabase/client").supabase;
  const rows: Record<string, unknown>[] = [];
  let after: string | null = null;
  for (;;) {
    let q = client.from("hyd_records").select("*").lte("created_at", cutoff).eq("user_id", userId)
      .order("id", { ascending: true }).limit(1000);
    if (after) q = q.gt("id", after);
    const { data, error } = await q;
    if (error) throw new Error(`Exportación incompleta, non se descargou nada: ${error.message}`);
    rows.push(...(data ?? []));
    if (!data || data.length < 1000) break;
    after = data[data.length - 1]!.id;
  }
  return rows;
}

export const getHydCapabilities = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async () => ({ corpusAdmin: false }));

// Full private archive: every stored field of every row in the authorised scope.
export const exportHydArchive = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((d) => z.object({ scope: exportScope }).parse(d))
  .handler(async ({ data, context }) => {
    const cutoff = new Date().toISOString();
    const rows = await readAll(data.scope, context.userId, context.supabase, cutoff);
    const payload = buildArchive(rows, data.scope, cutoff);
    const text = JSON.stringify(payload);
    const { createHash } = await import("node:crypto");
    return { text, count: rows.length, sha256: createHash("sha256").update(text).digest("hex") };
  });

// ---------- Create a record ----------

export const createHydRecord = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((d) => recordInput.parse(d))
  .handler(async ({ data, context }) => {
    const { error } = await context.supabase.from("hyd_records").insert({
      user_id: context.userId,
      question: data.question,
      expected_label: data.expectedLabel,
      hyd_prediction: data.hydPrediction ?? null,
      prediction_correct: data.predictionCorrect ?? null,
      consent: data.consentAccepted,
      consent_text: CONSENT_TEXT,
      notes: data.notes ? data.notes : null,
    });
    if (error) throw new Error(`Non se puido gardar o rexistro: ${error.message}`);
    return { ok: true as const };
  });

// ---------- Batch create (one consent for the batch, optional label per row) ----------

export const createHydRecordsBatch = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((d) => batchInput.parse(d))
  .handler(async ({ data, context }) => {
    const rows = data.questions.map((q, i) => ({
      user_id: context.userId,
      question: q,
      expected_label: data.labels?.[i] ?? data.expectedLabel,
      hyd_prediction: null,
      prediction_correct: null,
      consent: data.consentAccepted,
      consent_text: CONSENT_TEXT,
      notes: data.notes ? data.notes : null,
    }));
    const { error } = await context.supabase.from("hyd_records").insert(rows);
    if (error) throw new Error(`Non se puideron gardar os rexistros: ${error.message}`);
    return { ok: true as const, count: rows.length };
  });

// ---------- List my records ----------

export type HydRecord = {
  id: string;
  question: string;
  expected_label: string;
  hyd_prediction: string | null;
  prediction_correct: boolean | null;
  ai_label: string | null;
  ai_intent: string | null;
  ai_confidence: number | null;
  ai_model: string | null;
  consent: boolean;
  consent_text: string;
  notes: string | null;
  created_at: string;
};

export const listHydRecords = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { data, error } = await context.supabase
      .from("hyd_records")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(500);
    if (error) throw new Error(`Non se puideron ler os rexistros: ${error.message}`);
    return (data ?? []) as unknown as HydRecord[];
  });

// ---------- AI second opinion (only AFTER the evaluator labeled) ----------

export const getAiSecondOpinion = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((d) => z.object({ recordId: z.string().uuid() }).parse(d))
  .handler(async ({ data, context }) => {
    const { data: rec, error } = await context.supabase
      .from("hyd_records")
      .select("*")
      .eq("id", data.recordId)
      .single();
    if (error || !rec) throw new Error("Rexistro non atopado.");
    if ((rec as { user_id: string }).user_id !== context.userId)
      throw new Error("Non autorizado sobre este rexistro.");

    const existing = rec as unknown as HydRecord;
    // Never overwrite an existing second opinion.
    if (existing.ai_label) return existing;

    const apiKey = process.env["LOVABLE_API_KEY"];
    if (!apiKey) throw new Error("A IA non está dispoñible agora mesmo.");

    const system =
      "Eres un clasificador de intención para un enrutador de consultas (Hyd). " +
      "Dada una pregunta de usuario, responde SOLO un objeto JSON con esta forma exacta: " +
      '{"intent": "<descripción breve de la intención en una frase>", "label": "<una etiqueta>", "confidence": <número entre 0 y 1>}. ' +
      "Las etiquetas válidas son exactamente: high_risk_review (peticiones sensibles que requieren revisión humana), " +
      "reasoning (razonamiento paso a paso, matemáticas, lógica), coding (programación), " +
      "abstain (la pregunta debe recibir una respuesta de abstención), privacy (privacidad y datos personales), " +
      "security (seguridad y ciberseguridad), vision (imágenes y visión), research (investigación profunda), " +
      "chat (conversación general), tool_use (uso de herramientas o funciones). " +
      "No expliques nada más. No incluyas texto fuera del JSON.";

    const res = await fetch("https://ai.gateway.lovable.dev/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: "google/gemini-2.5-flash",
        temperature: 0,
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: system },
          { role: "user", content: existing.question },
        ],
      }),
    });
    if (!res.ok) throw new Error(`A IA devolveu un erro (HTTP ${res.status}).`);

    const payload = (await res.json()) as {
      model?: string;
      choices?: { message?: { content?: string } }[];
    };
    const content = payload.choices?.[0]?.message?.content ?? "";
    let parsed: { intent?: string; label?: string; confidence?: number };
    try {
      parsed = JSON.parse(content);
    } catch {
      throw new Error("A IA non devolveu unha resposta válida.");
    }
    if (!parsed.label || !HYD_LABELS.includes(parsed.label as HydLabel))
      throw new Error("A IA suxeriu unha etiqueta non válida.");

    const confidence = Math.max(0, Math.min(1, Number(parsed.confidence) || 0));
    // Conditional write: only if no opinion exists yet (never overwrites a concurrent one).
    const { data: updated, error: updErr } = await context.supabase
      .from("hyd_records")
      .update({
        ai_label: parsed.label,
        ai_intent: (parsed.intent ?? "").slice(0, 300),
        ai_confidence: confidence,
        ai_model: payload.model ?? "google/gemini-2.5-flash",
      })
      .eq("id", data.recordId)
      .is("ai_label", null)
      .select()
      .maybeSingle();
    if (updErr) throw new Error(`Non se puido gardar a segunda opinión: ${updErr.message}`);
    if (updated) return updated as unknown as HydRecord;
    const { data: winner, error: wErr } = await context.supabase
      .from("hyd_records").select("*").eq("id", data.recordId).single();
    if (wErr || !winner) throw new Error("A opinión cambiou noutra petición; recarga a páxina.");
    return winner as unknown as HydRecord;
  });

// ---------- Filtered training JSONL (separate from the full archive) ----------

export const exportHydRecords = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((d) => z.object({ scope: exportScope }).parse(d))
  .handler(async ({ data, context }) => {
    const cutoff = new Date().toISOString();
    const sorted = await readAll(data.scope, context.userId, context.supabase, cutoff);
    sorted.sort((a, b) =>
      String(a["created_at"]).localeCompare(String(b["created_at"])) || String(a["id"]).localeCompare(String(b["id"])),
    );
    const rows = sorted;

    // Drop exact copies (same question ignoring case/spacing + same label);
    // the earliest record is kept, text untouched.
    const seen = new Set<string>();
    const all = rows.filter((r) => {
      const q = String((r as { question: string }).question).trim().replace(/\s+/g, " ").toLowerCase();
      const k = q + "\u0000" + (r as { expected_label: string }).expected_label;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });

    // Template detection: questions that share a skeleton with >=3 others
    // (same first 4 + last 2 words, same first 6, or same last 5 words)
    // look generated from a mould. They are kept intact but exported apart.
    const toks = all.map((r) => ((r as { question: string }).question.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []));
    const groups = new Map<string, number[]>();
    toks.forEach((t, i) => {
      if (t.length < 6) return;
      for (const k of [
        "p|" + t.slice(0, 4).join(" ") + "|" + t.slice(-2).join(" "),
        "h|" + t.slice(0, 6).join(" "),
        "s|" + t.slice(-5).join(" "),
      ]) {
        const g = groups.get(k) ?? [];
        g.push(i);
        groups.set(k, g);
      }
    });
    const suspect = new Set<number>();
    for (const g of groups.values()) if (g.length >= 4) g.forEach((i) => suspect.add(i));

    const lines: string[] = [];
    const suspectLines: string[] = [];
    all.forEach((r, i) => {
      const rec = r as unknown as HydRecord & { user_id: string };
      const isSuspect = suspect.has(i);
      const line = JSON.stringify({
        text: rec.question,
        expected: rec.expected_label,
        meta: {
          record_id: rec.id,
          source: "hyd-evaluator-app",
          // Historical rows have no declared provenance or rights: unknown, never inferred.
          real: null,
          source_kind: "unknown",
          rights: { declared: null, verified: false },
          synthetic: null,
          suspect_template: isSuspect,
          consent: rec.consent === true,
          consent_text: rec.consent_text,
          account: rec.user_id,
          independent_review: false,
          hyd_prediction: rec.hyd_prediction,
          prediction_correct: rec.prediction_correct,
          ai_second_opinion: {
            label: rec.ai_label,
            intent: rec.ai_intent,
            confidence: rec.ai_confidence,
            model: rec.ai_model,
            authority: false,
          },
          created_at: rec.created_at,
        },
      });
      (isSuspect ? suspectLines : lines).push(line);
    });
    return {
      lines,
      count: lines.length,
      suspectLines,
      suspectCount: suspectLines.length,
      total: rows.length,
      duplicates: rows.length - all.length,
      scope: data.scope,
    };
  });
