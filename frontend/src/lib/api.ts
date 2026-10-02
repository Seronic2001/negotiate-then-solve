import type {
  CaseDetail,
  CaseSummary,
  ClubDecision,
  ClubRequest,
  EventRow,
  Experiment,
  GraphData,
  InboxItem,
  InstanceView,
  Ledger,
  Observability,
  Overview,
  ParsedInput,
  Persona,
  PolicyDocument,
  PolicyDocuments,
  ReplyView,
  Rule,
  SemPreference,
  SemStatus,
  SemTimetable,
  SemesterOverview,
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
  documents: () => call<PolicyDocuments>("/handbook/documents"),
  uploadDocument: (name: string, data: string) => post<PolicyDocument & { rules: Rule[] }>("/handbook/documents", { name, data }),
  removeDocument: (name: string) => call<{ removed: string }>(`/handbook/documents/${encodeURIComponent(name)}`, { method: "DELETE" }),
  search: (q: string, mode?: string) =>
    call<{ query: string; tokens: string[]; mode: string; results: Rule[] }>(
      `/handbook/search?q=${encodeURIComponent(q)}${mode ? `&mode=${mode}` : ""}`,
    ),
  semester: () => call<SemesterOverview>("/semester"),
  semesterPublic: () => call<SemesterOverview>("/semester/public"),
  loadOfferings: (body: { sample: true } | { name: string; data: string }) =>
    post<{ courses: number; cohorts: number; pools: number; warnings: string[] }>("/semester/offerings", body),
  setSizes: (sizes: Record<string, number>) => post<{ ok: boolean }>("/semester/sizes", { sizes }),
  addPreference: (text: string, preview = false) => post<ParsedInput>("/semester/preferences", { text, preview }),
  myPreferences: () => call<SemPreference[]>("/semester/preferences"),
  removePreference: (id: string) => call<{ removed: string }>(`/semester/preferences/${id}`, { method: "DELETE" }),
  build: (note = "") => post<SemStatus>("/semester/build", { note }),
  semesterStatus: () => call<SemStatus>("/semester/status"),
  semesterTimetable: (version?: number) => call<SemTimetable>(`/semester/timetable${version ? `?version=${version}` : ""}`),
  proposeChange: (text: string, preview = false) => post<ParsedInput>("/semester/changes", { text, preview }),
  publishSemester: (version: number) => post<{ published: number }>(`/semester/versions/${version}/publish`),
  club: (request: ClubRequest, submit: boolean) => post<ClubDecision>("/clubs", { request, submit }),
  clubs: () => call<ClubDecision[]>("/clubs"),
  decideClub: (id: string, approve: boolean) => post<ClubDecision>(`/clubs/${id}/decide`, { approve }),
  transparency: () => call<Transparency>("/transparency"),
  observability: () => call<Observability>("/observability"),
  experiments: () => call<Experiment[]>("/experiments"),
  reset: () => post<{ ok: boolean }>("/demo/reset"),
};
