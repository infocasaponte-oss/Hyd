// Live, aggregate-only corpus stats for the public panel (no questions, no authors).
import { createServerFn } from "@tanstack/react-start";

const LABELS = [
  "high_risk_review", "reasoning", "coding", "abstain", "privacy",
  "security", "vision", "research", "chat", "tool_use",
] as const;

// Accounts whose questions built E2's train/calibration/test splits (both belong
// to the same person). Used only to EXCLUDE them from the independent count —
// this grants no access to anyone.
const TRAINING_ACCOUNTS = new Set([
  "f0a64f92-4432-4482-ac0d-ec5ee5aa9598",
  "87c9c2d4-6034-411c-a17c-0735e05a44ae",
]);

export const getCorpusStats = createServerFn({ method: "GET" }).handler(async () => {
  const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
  const rows: { question: string; expected_label: string; created_at: string; user_id: string }[] = [];
  for (let from = 0; ; from += 1000) {
    const { data, error } = await supabaseAdmin
      .from("hyd_records")
      .select("question, expected_label, created_at, user_id")
      .order("id", { ascending: true })
      .range(from, from + 999);
    if (error) throw new Error(error.message);
    rows.push(...(data ?? []));
    if (!data || data.length < 1000) break;
  }

  // Same rules as the JSONL export: drop exact copies, then flag mould-like questions.
  const seen = new Set<string>();
  const distinct = rows.filter((r) => {
    const k = r.question.trim().replace(/\s+/g, " ").toLowerCase() + "\u0000" + r.expected_label;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  const groups = new Map<string, number[]>();
  distinct.forEach((r, i) => {
    const t = r.question.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? [];
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

  const labelsByText = new Map<string, Set<string>>();
  for (const r of distinct) {
    const k = r.question.trim().replace(/\s+/g, " ").toLowerCase();
    (labelsByText.get(k) ?? labelsByText.set(k, new Set()).get(k)!).add(r.expected_label);
  }
  const conflicts = [...labelsByText.values()].filter((s) => s.size > 1).length;

  const perClass = Object.fromEntries(LABELS.map((l) => [l, 0])) as Record<string, number>;
  distinct.forEach((r, i) => {
    if (!suspect.has(i)) perClass[r.expected_label] = (perClass[r.expected_label] ?? 0) + 1;
  });
  const lastAt = rows.reduce((m, r) => (r.created_at > m ? r.created_at : m), "");

  // Independent pool: accounts that did NOT contribute to E2's training data,
  // minus any question whose text already appears in the training accounts.
  const norm = (q: string) => q.trim().replace(/\s+/g, " ").toLowerCase();
  const trainTexts = new Set(rows.filter((r) => TRAINING_ACCOUNTS.has(r.user_id)).map((r) => norm(r.question)));
  const extSeen = new Set<string>();
  const ext = rows.filter((r) => {
    if (TRAINING_ACCOUNTS.has(r.user_id)) return false;
    const k = norm(r.question);
    if (trainTexts.has(k) || extSeen.has(k)) return false;
    extSeen.add(k);
    return true;
  });
  const extPerClass = Object.fromEntries(LABELS.map((l) => [l, 0])) as Record<string, number>;
  for (const r of ext) extPerClass[r.expected_label] = (extPerClass[r.expected_label] ?? 0) + 1;

  return {
    total: rows.length,
    distinct: distinct.length,
    suspect: suspect.size,
    valid: distinct.length - suspect.size,
    conflicts,
    perClass,
    lastAt,
    external: {
      accounts: new Set(ext.map((r) => r.user_id)).size,
      questions: ext.length,
      perClass: extPerClass,
    },
    generatedAt: new Date().toISOString(),
  };
});
