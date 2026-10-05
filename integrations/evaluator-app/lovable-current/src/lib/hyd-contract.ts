// Pure, browser-safe contract for the Hyd evaluator workflow (tested in hyd-contract.test.ts).
import { z } from "zod";

export const HYD_LABELS = [
  "high_risk_review",
  "reasoning",
  "coding",
  "abstain",
  "privacy",
  "security",
  "vision",
  "research",
  "chat",
  "tool_use",
] as const;
export type HydLabel = (typeof HYD_LABELS)[number];

// Exact consent text stored verbatim on every record. CONSENT_VERSION identifies this text;
// the server rejects any request that does not send both the acceptance and this version.
export const CONSENT_TEXT =
  "Consinto que esta pregunta, tal e como a escribin, se garde neste sistema e se use para adestrar e avaliar o enrutador Hyd. O rexistro queda asinado coa miña conta de evaluador e podo pedir a súa eliminación en calquera momento.";
export const CONSENT_VERSION = "hyd-consent/1";

// The question is stored byte-for-byte: no trim, no normalisation. Length is checked
// on the trimmed text only to reject empty lines.
export const questionSchema = z
  .string()
  .max(4000)
  .refine((t) => t.trim().length >= 3, "A pregunta é demasiado curta (mínimo 3 caracteres).");

export const consentFields = {
  consentAccepted: z.literal(true, { message: "Falta o consentimento explícito." }),
  consentVersion: z.literal(CONSENT_VERSION, { message: "Versión de consentimento non válida." }),
};

export const recordInput = z.object({
  question: questionSchema,
  expectedLabel: z.enum(HYD_LABELS),
  hydPrediction: z.enum(HYD_LABELS).nullable().optional(),
  predictionCorrect: z.boolean().nullable().optional(),
  notes: z.string().max(1000).optional(),
  ...consentFields,
});

export const batchInput = z
  .object({
    questions: z.array(questionSchema).min(1).max(50),
    expectedLabel: z.enum(HYD_LABELS),
    labels: z.array(z.enum(HYD_LABELS)).max(50).optional(),
    notes: z.string().max(1000).optional(),
    ...consentFields,
  })
  .refine((b) => !b.labels || b.labels.length === b.questions.length, "Cada pregunta precisa a súa etiqueta.");

export const exportScope = z.enum(["mine", "all"]);
export type ExportScope = z.infer<typeof exportScope>;

export function adminIds(value: string | undefined) {
  return (value ?? "").split(",").map((s) => s.trim()).filter(Boolean);
}

/** Full, unfiltered archive of every stored field. Private backup, never a training corpus. */
export function buildArchive(records: Record<string, unknown>[], scope: ExportScope, cutoff: string) {
  return {
    format: "hyd-records-archive/1",
    scope,
    cutoff,
    snapshot_consistent: false,
    contains_private_account_data: true,
    count: records.length,
    consent_version_current: CONSENT_VERSION,
    records,
    limitations: [
      "Paginated reads are not a transactional snapshot.",
      "Deleted rows and auth accounts are not included.",
      "Provenance, declared rights and correction fields do not exist yet for these rows: unknown, not inferred.",
    ],
  };
}
