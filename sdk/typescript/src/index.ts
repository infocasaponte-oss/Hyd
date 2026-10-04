// Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
// HYDRA TypeScript SDK (native protocol). Works in Node >= 18 and browsers (fetch + WebSocket).

export type Mode = "fast" | "balanced" | "deep" | "max" | "private";

export interface HydraResult {
  schema_version: string;
  task_id: string;
  status: string;
  answer: string | null;
  decision: string;
  confidence: number;
  verified: boolean;
  models_used: string[];
  tools_used: string[];
  artifacts: Record<string, unknown>[];
  claims: Record<string, unknown>[];
  latency_ms: number;
  learning: Record<string, unknown>;
}

export interface HydraEventEnvelope {
  type: "event";
  event_id: string;
  event_type: string;
  aggregate_id: string;
  sequence: number;
  producer: string;
  payload: Record<string, unknown>;
  payload_hash: string;
}

export class HydraClient {
  constructor(private baseUrl = "http://127.0.0.1:8080", private apiKey?: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  private headers(): Record<string, string> {
    return { "Content-Type": "application/json", ...(this.apiKey ? { "X-API-Key": this.apiKey } : {}) };
  }

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const r = await fetch(this.baseUrl + path, { method, headers: this.headers(), body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return (await r.json()) as T;
  }

  task(goal: string, opts: { mode?: Mode; localOnly?: boolean } = {}): Promise<HydraResult> {
    return this.req("POST", "/v1/tasks", { goal, mode: opts.mode ?? "balanced", constraints: { local_only: !!opts.localOnly } });
  }

  goal(goal: string, workspace?: string, mode: Mode = "balanced"): Promise<Record<string, unknown>> {
    return this.req("POST", "/hydra/v1/goals", { goal, workspace, mode });
  }

  world(query?: string): Promise<Record<string, unknown>> {
    return query ? this.req("POST", "/hydra/v1/world/query", { query }) : this.req("GET", "/hydra/v1/world");
  }

  corpusSearch(text: string, limit = 20): Promise<Record<string, unknown>[]> {
    return this.req("POST", "/hydra/v1/corpus/query", { text, limit });
  }

  resolve(capability: string, constraints: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.req("POST", "/hydra/v1/models/resolve", { capability, constraints });
  }

  translate(text: string, target_language: string, glossary: Record<string, string> = {}): Promise<Record<string, unknown>> {
    return this.req("POST", "/v1/translate", { text, target_language, glossary });
  }

  /** Streams structured events (task.created, route.selected, model.completed, ...) then the result. */
  streamTask(goal: string, onEvent: (e: HydraEventEnvelope) => void, mode: Mode = "balanced"): Promise<HydraResult> {
    const url = this.baseUrl.replace(/^http/, "ws") + "/v1/ws/tasks";
    // Browsers cannot set WebSocket headers and query strings end up in logs: the key travels as a
    // subprotocol, base64url-encoded so any key is a valid RFC 7230 token ("hydra.token.b64.<key>").
    const protocols = this.apiKey ? ["hydra.v1", `hydra.token.b64.${base64url(this.apiKey)}`] : ["hydra.v1"];
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url, protocols);
      ws.onopen = () => ws.send(JSON.stringify({ goal, mode }));
      ws.onmessage = (m) => {
        const d = JSON.parse(String(m.data));
        if (d.type === "event") onEvent(d);
        else if (d.type === "result") { ws.close(); resolve(d as HydraResult); }
        else if (d.type === "error") { ws.close(); reject(new Error(d.error)); }
      };
      ws.onerror = () => reject(new Error("websocket error"));
    });
  }
}

function base64url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
