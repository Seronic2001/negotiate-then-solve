import type {
  CaseDetail,
  CaseSummary,
  EventRow,
  Experiment,
  GraphData,
  InboxItem,
  InstanceView,
  Ledger,
  Observability,
  Overview,
  Persona,
  ReplyView,
  Rule,
  Timetable,
  Transparency,
  VersionRow,
} from "./types";

const USER_KEY = "nts.user";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function currentUserId(): string | null {
  try {
    return localStorage.getItem(USER_KEY);
  } catch {
    return null;
  }
}

export function setCurrentUserId(id: string | null): void {
  try {
    if (id) localStorage.setItem(USER_KEY, id);
    else localStorage.removeItem(USER_KEY);
  } catch {
    /* storage unavailable: the session lasts until reload */
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const user = currentUserId();
  const headers = new Headers(init.headers);
  if (user) headers.set("X-User", user);
  if (init.body) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  personas: () => call<Persona[]>("/personas"),
  login: (person: string) => post<Persona>("/login", { person }),
  me: () => call<Persona>("/me"),
  overview: () => call<Overview>("/overview"),
  instance: () => call<InstanceView>("/instance"),
  submit: (text: string) => post<{ id: string }>("/requests", { text }),
  cases: (scope: "mine" | "all") => call<CaseSummary[]>(`/cases?scope=${scope}`),
  case: (id: string) => call<CaseDetail>(`/cases/${id}`),
  events: (after = 0, caseId?: string) =>
    call<EventRow[]>(`/events?after=${after}${caseId ? `&case=${caseId}` : ""}&limit=300`),
  inbox: () => call<InboxItem[]>("/inbox"),
  reply: (id: string, reply: Omit<ReplyView, "decision"> & { decision: "accept" | "reject" | "counter" }) =>
    post<InboxItem>(`/inbox/${id}/reply`, reply),
  simulate: (id: string) => post<InboxItem>(`/inbox/${id}/simulate`),
  autopilot: () => call<Record<string, boolean>>("/autopilot"),
  setAutopilot: (person: string, on: boolean) => post<Record<string, boolean>>("/autopilot", { person, on }),
  approvals: () => call<CaseDetail[]>("/approvals"),
  approve: (id: string) => post<{ version: number; notified: Record<string, string> }>(`/approvals/${id}/approve`),
  reject: (id: string, reason: string) => post<{ status: string }>(`/approvals/${id}/reject`, { reason }),
  versions: () => call<VersionRow[]>("/versions"),
  timetable: (opts: { version?: number; week?: number | null } = {}) => {
    const q = new URLSearchParams();
    if (opts.version) q.set("version", String(opts.version));
    if (opts.week) q.set("week", String(opts.week));
    return call<Timetable>(`/timetable?${q}`);
  },
  rollback: (version: number) => post<{ version: number }>(`/versions/${version}/rollback`),
  ledger: () => call<Ledger>("/ledger"),
  graph: () => call<GraphData>("/graph"),
  handbook: () => call<Rule[]>("/handbook"),
  search: (q: string) => call<{ query: string; tokens: string[]; results: Rule[] }>(`/handbook/search?q=${encodeURIComponent(q)}`),
  transparency: () => call<Transparency>("/transparency"),
  observability: () => call<Observability>("/observability"),
  experiments: () => call<Experiment[]>("/experiments"),
  reset: () => post<{ ok: boolean }>("/demo/reset"),
};
