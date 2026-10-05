import { describe, expect, it } from "vitest";
import { batchInput, buildArchive, CONSENT_VERSION, recordInput, adminIds } from "./hyd-contract";

const ok = { expectedLabel: "chat", consentAccepted: true, consentVersion: CONSENT_VERSION } as const;

describe("hyd contract", () => {
  it("keeps the question byte-for-byte (no trim)", () => {
    const q = "  ola,   como estás?\t";
    expect(recordInput.parse({ ...ok, question: q }).question).toBe(q);
  });
  it("rejects missing consent", () => {
    expect(() => recordInput.parse({ expectedLabel: "chat", question: "pregunta real" })).toThrow();
  });
  it("rejects consent=false or wrong version", () => {
    expect(() => recordInput.parse({ ...ok, consentAccepted: false, question: "abc d" })).toThrow();
    expect(() => recordInput.parse({ ...ok, consentVersion: "x", question: "abc d" })).toThrow();
  });
  it("rejects blank questions", () => {
    expect(() => recordInput.parse({ ...ok, question: "   " })).toThrow();
  });
  it("batch per-row labels must match question count", () => {
    expect(() => batchInput.parse({ ...ok, questions: ["uno dos", "tres catro"], labels: ["chat"] })).toThrow();
    const b = batchInput.parse({ ...ok, questions: [" uno dos ", "tres catro"], labels: ["chat", "coding"] });
    expect(b.questions[0]).toBe(" uno dos ");
  });
  it("archive keeps every record and field untouched", () => {
    const rows = [{ id: "1", question: " x ", notes: "n", ai_label: "chat" }];
    const a = buildArchive(rows, "mine", "2026-10-04T00:00:00Z");
    expect(a.count).toBe(1);
    expect(a.records[0]).toEqual(rows[0]);
    expect(a.contains_private_account_data).toBe(true);
  });
  it("parses admin id list", () => {
    expect(adminIds(" a, b ,,")).toEqual(["a", "b"]);
    expect(adminIds(undefined)).toEqual([]);
  });
});
