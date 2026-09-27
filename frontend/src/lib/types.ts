// Shapes returned by the Python API (src/nts/web.py).

export type Role = "coordinator" | "dean" | "hod" | "faculty" | "guest_faculty" | "lab_incharge" | "exam_cell" | "student";

export interface Persona {
  id: string;
  name: string;
  role: Role;
  email?: string;
  /** Views this person may open, decided by the server (``VIEWS`` in nts/web.py). */
  views?: View[];
}

export type View = "home" | "requests" | "timetable" | "handbook" | "how" | "new" | "inbox" | "approvals" | "documents" | "semester" | "prefs" | "clubs" | "fairness" | "graph" | "health" | "experiments";

export type Status =
  | "received"
  | "classified"
  | "refused"
  | "policy_checked"
  | "denied"
  | "clarification_requested"
  | "compiled"
  | "solved"
  | "negotiating"
  | "fairness_audited"
  | "awaiting_approval"
  | "published"
  | "escalated"
  | "answered"
  | "forwarded";

export interface EventRow {
  n: number;
  case: string | null;
  at: string;
  kind: string;
  [key: string]: unknown;
}

export interface CaseSummary {
  id: string;
  sender: string;
  sender_name: string;
  role: Role;
  channel: string;
  text: string;
  received_at: string;
  status: Status;
  route: string;
  type: string | null;
  rounds: number;
  running: boolean;
}

export interface ConstraintView {
  id: string;
  type: string;
  hard: boolean;
  tier: number;
  tier_name: string;
  owner: string | null;
  owner_name: string;
  text: string;
  when: { days: string[] | null; slots: number[] | null; weeks: number[] | null };
  justification: string;
  source: { request: string | null; rule: string | null };
}

export interface PlacementView {
  day: string;
  slot: number;
  room: string;
  text: string;
  time: string;
}

export interface OfferView {
  key: string;
  drop: string[];
  cost: number;
  moved: number;
  verified: boolean;
  placements: (PlacementView & { session: string; session_name: string })[];
}

export interface Claim {
  text: string;
  facts: string[];
  supported: boolean;
}

export interface MessageView {
  round: number;
  to: string;
  to_name: string;
  mus: string[];
  offers: OfferView[];
  text: string;
  explanation_mode: string;
  faithfulness: number;
  leaks: string[];
  rejected_claims: number;
  facts: { id: string; text: string }[];
  claims: Claim[];
}

export interface ReplyView {
  decision: "accept" | "reject" | "counter" | "no_reply" | null;
  choice?: string;
  counter_days?: string[];
  counter_slots?: number[];
  text?: string;
}

export interface InboxItem {
  id: string;
  case: string | null;
  to: string;
  to_name: string;
  created: string;
  deadline: string;
  message: MessageView;
  reply: ReplyView | null;
  answered_by: string | null;
}

export interface DiffRow {
  session: string;
  session_name: string;
  faculty: string | null;
  faculty_name: string | null;
  groups: string[];
  before: PlacementView | null;
  after: PlacementView | null;
}

export interface CaseDetail extends CaseSummary {
  routing: {
    request_type: string;
    type_p: number;
    action: string;
    action_p: number;
    tau: number;
    fast_path: boolean;
    latency_ms: number;
  } | Record<string, never>;
  timings: Record<string, number>;
  parse: null | {
    action: string;
    refusal: string | null;
    errors: string[];
    output: Record<string, unknown> | null;
    constraints: ConstraintView[];
  };
  policy: null | {
    verdict: "allowed" | "needs_approval" | "forbidden";
    cited: { id: string; cite: string }[];
    obligations: string[];
    retrieved: string[];
    hallucinated: string[];
    explanation: string;
    alternative: string | null;
    answer: string | null;
    uncited_escalation: boolean;
    mode: string;
  };
  outcome: null | {
    status: "feasible" | "agreed" | "escalated";
    step: number;
    rounds: number;
    relaxed: string[];
    mus_log: ConstraintView[][];
    messages: MessageView[];
    replies: ReplyView[];
    concessions: { stakeholder: string; name: string; constraint_id: string; credit: number }[];
    notices: Record<string, string[]>;
    escalation: null | { to: string; to_name: string; reason: string; text: string };
    solver: null | { status: string; wall_time: number; moved: number | null; soft_violations: Record<string, number> };
  };
  proposal: null | { version: number; week: number | null; diff: DiffRow[] };
  fairness: { gini_before?: number; gini_after?: number; conceded?: string[]; preferences_lost?: string[] };
  reply: string;
  notices: Record<string, string>;
  inbox: InboxItem[];
  events: EventRow[];
}

export interface Overview {
  department: string;
  semester: string;
  seeding: boolean;
  counts: Partial<Record<Status, number>>;
  total: number;
  pending_approvals: number;
  my_inbox: number;
  published_version: number | null;
  gini: number;
  negotiations: { agreed: number; escalated: number; feasible: number; mean_rounds: number | null };
  recent: EventRow[];
  models: { parser: string; policy: string };
  sessions: number;
  faculty: number;
  rooms: number;
  groups: number;
}

export interface TimetableEntry {
  session: string;
  course: string;
  title: string;
  kind: "lecture" | "tutorial" | "practical";
  faculty: string;
  faculty_name: string;
  groups: string[];
  group_names: string[];
  duration: number;
  day: string;
  slot: number;
  room: string;
  room_name: string;
}

export interface Timetable {
  version: number;
  week: number | null;
  approved_by: string | null;
  parent: number | null;
  entries: TimetableEntry[];
  changed: string[];
}

export interface VersionRow {
  version: number;
  parent: number | null;
  approved_by: string | null;
  approved_by_name: string | null;
  published: boolean;
  case: string | null;
  created_at: string;
  week: number | null;
}

export interface InstanceView {
  name: string;
  calendar: { days: string[]; slots_per_day: number; lunch_slot: number | null; weeks: number };
  slots: { slot: number; label: string }[];
  day_names: Record<string, string>;
  faculty: { id: string; name: string; role: Role; reports_to: string | null; email: string | null }[];
  groups: { id: string; name: string; size: number }[];
  rooms: { id: string; name: string; capacity: number; type: string; equipment: string[] }[];
  sessions: { id: string; course: string; kind: string; faculty: string; groups: string[]; duration: number; title: string }[];
  policy: { max_consecutive: number | null; lunch_break: boolean };
}

export interface Ledger {
  semester: string;
  gini: number;
  decay: number;
  entries: { stakeholder: string; name: string; constraint_id: string; semester: string; credit: number }[];
  stakeholders: { id: string; name: string; credit: number; concessions: number }[];
}

export interface GraphData {
  nodes: { id: string; kind: string; label: string; role?: string; type?: string; tier?: number; balance?: number }[];
  edges: { source: string; target: string; rel: string }[];
}

export interface Rule {
  id: string;
  number: string;
  title: string;
  text: string;
  source: string;
  pages: number[];
  method: string; // "markdown", "html", "text layer" or "ocr: <backend>"
  score?: number;
}

export interface PolicyDocument {
  name: string;
  kind: "pdf" | "html" | "image" | "markdown";
  pages: number;
  methods: Record<string, number>;
  ocr_confidence: number | null;
  rules: string[];
  seconds: number;
  error: string | null;
}

export interface PolicyDocuments {
  ocr: { backend: string; model: string };
  accepts: string[];
  documents: PolicyDocument[];
}

export interface Transparency {
  tiers: { tier: number; name: string; who: string; examples: string; relaxable_in_negotiation: boolean }[];
  weights: Record<string, number>;
  role_authority: Record<string, number>;
  justification: Record<string, number>;
  ladder: { step: number; name: string; text: string }[];
  negotiation: Record<string, number>;
  system_one: { trained_on?: number; val_action_accuracy?: number; tau?: number };
  models: { parser: string; policy: string };
  safety: string[];
}

export interface Observability {
  uptime_s: number;
  models: { parser: string; policy: string };
  llm: { model: string; used_today: number; rpd: number | null; rpm: number | null; cached_responses: number }[];
  stages: Record<string, { n: number; p50: number | null; p95: number | null; max: number | null }>;
  solver: { n: number; p50: number | null; p95: number | null };
  routing: { counts: Record<string, number>; tau: number; system_one_latency_ms_p50: number | null; fast_path_share: number | null };
  explanations: { messages: number; faithfulness: number | null; leaks: number; rejected_claims: number };
  events_by_kind: Record<string, number>;
  errors: EventRow[];
  safety: { refused: number; denied: number; unapproved_publishes: number; leaks: number };
  threads_running: number;
}

export interface NegotiationSummary {
  n: number;
  correct_outcome: number | null;
  validity_of_timetables: number | null;
  timetables_produced: number;
  agreement_rate: number | null;
  rounds_mean: number | null;
  rounds_ci: [number, number] | null;
  cost_ratio_to_oracle: number | null;
  within_10pct_of_oracle: number | null;
  escalation_precision: number | null;
  escalation_recall: number | null;
  concession_gini: number | null;
  first_proposal_acceptance: number | null;
  explanation_faithfulness: number | null;
  private_leaks: number;
  imposed_acceptable: number | null;
  status: Record<string, number>;
}

export type Experiment =
  | { id: string; title: string; at: string; kind: "negotiation"; configs: Record<string, NegotiationSummary>; paired?: unknown }
  | { id: string; title: string; at: string; kind: "parsing"; system_one: Record<string, number> | null; system_two: Record<string, unknown> }
  | { id: string; title: string; at: string; kind: "policy"; summary: Record<string, unknown> }
  | { id: string; title: string; at: string; kind: "safety"; summary: Record<string, unknown> };

// -- semester timetable ---------------------------------------------------------

export interface SemWindow {
  days: string[];
  start: string;
  end: string;
  reason: string;
}

export interface SemCalendar {
  days: string[];
  mirror: Record<string, string>;
  lecture_slots: [string, string][];
  tutorial_slots: [string, string][];
  lab_starts: string[];
  blocked: SemWindow[];
  club_hours: SemWindow[];
  weeks: number;
  evening_slot: number;
}

export interface SemRoom {
  id: string;
  capacity: number;
  type: string;
}

export interface SemCohort {
  id: string;
  name: string;
  size: number;
  courses: string[];
  electives: string[];
  /** Each elective slot and the pools its course can come from ([] for honours projects). */
  elective_pools?: { slot: string; pools: { id: string; name: string; courses: string[] }[] }[];
}

export interface SemNeed {
  kind: "lecture" | "tutorial" | "lab";
  label: string;
  rooms: number[];
  room_type: string;
  options: number;
  pair: boolean;
}

export interface SemCourse {
  code: string;
  name: string;
  L: number;
  T: number;
  P: number;
  C: number;
  faculty: string[];
  half: string;
  cap: number | null;
  cohorts: string[];
  pools: string[];
  scheduled: boolean;
  note: string;
  needs: SemNeed[];
}

export interface SemPreference {
  id: string;
  target: "faculty" | "course" | "cohort";
  who: string;
  mode: "avoid" | "prefer";
  days: string[] | null;
  start: string | null;
  end: string | null;
  hard: boolean;
  weight: number;
  text: string;
  source: string;
}

export interface SemReport {
  status: string;
  seconds: number;
  components: number;
  meetings: number;
  hard_violations: string[];
  preferences: { id: string; text: string; met: boolean; hard: boolean; sessions: number }[];
  pool_clashes: number;
  evening_sessions: number;
  moved: number;
  notes: string[];
  room_use?: Record<string, number>;
}

export interface SemVersionMeta {
  version: number;
  created: string;
  kind: "build" | "change";
  note: string;
  published: boolean;
  based_on: number | null;
  moved: number;
  report: SemReport;
}

export interface SemesterOverview {
  loaded: boolean;
  source: string | null;
  semester_start: string;
  calendar: SemCalendar;
  published: number | null;
  cohorts: SemCohort[];
  rooms: SemRoom[];
  courses?: SemCourse[];
  pools?: { id: string; name: string; courses: string[]; cap: number | null }[];
  warnings?: string[];
  preferences?: SemPreference[];
  closures?: { room: string; window: SemWindow; text: string }[];
  versions?: SemVersionMeta[];
  sample_available?: boolean;
}

export interface SemMeeting {
  component: string;
  course: string;
  name: string;
  kind: "lecture" | "tutorial" | "lab";
  label: string;
  day: string;
  start: string;
  end: string;
  slot: number | null;
  rooms: string[];
  faculty: string[];
  cohorts: string[];
  half: string;
}

export interface SemDiffRow {
  component: string;
  course: string;
  name: string;
  label: string;
  before: string;
  after: string;
}

export interface SemTimetable {
  version: number;
  published: boolean;
  kind: string;
  note: string;
  diff: SemDiffRow[];
  meetings: SemMeeting[];
  report: SemReport;
}

export interface SemStatus {
  running: boolean;
  kind?: string;
  note?: string;
  elapsed?: number;
  error?: string | null;
  version?: number | null;
}

export interface ParsedInput {
  ok: boolean;
  error?: string;
  summary?: string[];
  preferences?: SemPreference[];
  closures?: ({ room: string } & SemWindow)[];
  status?: SemStatus;
}

export interface ClubRequest {
  club: string;
  activity: string;
  date: string;
  start: string;
  end: string;
  attendees: number;
  cohorts: string[];
  room: string | null;
  requested_by?: string;
}

export interface ClubDecision {
  id: string;
  request: ClubRequest;
  status: "booked" | "needs_approval" | "rejected";
  room: string | null;
  day: string;
  week: number | null;
  checks: { name: string; ok: boolean; detail: string }[];
  alternatives: { date: string; day: string; start: string; end: string; room: string }[];
  rules: { id: string; title: string; source: string; text: string }[];
  decided_at: string;
}
