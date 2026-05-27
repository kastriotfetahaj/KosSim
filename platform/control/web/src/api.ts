// Typed client for FastAPI control plane.

export class HttpError extends Error {
  constructor(public status: number, public body: string) {
    super(`HTTP ${status}`);
  }
}

async function request<T>(
  method: string,
  url: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new HttpError(res.status, text);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};

// ---------- Public scoreboard types ----------

export type Service = {
  id: number;
  name: string;
  slug?: string | null;
  display_name?: string | null;
};

export type ServiceCell = {
  service_name: string;
  service_slug?: string | null;
  service_display_name?: string | null;
  service_total: number;
  service_delta: number;
  attack_points: number;
  attack_delta: number;
  defense_points: number;
  defense_delta: number;
  uptime_points: number;
  uptime_delta: number;
  challenge_points: number;
  challenge_delta: number;
  flags_captured: number;
  flags_delta: number;
  attackers_count: number;
  attackers_delta: number;
  victims_count: number;
  victims_delta: number;
  sla_pct: number;
  sla_delta: number;
  checker_status: string;
  is_up: boolean;
  put_status: "OK" | "FAIL" | "IDLE";
  get_status: "OK" | "FAIL" | "IDLE";
  havoc_status: "OK" | "FAIL" | "IDLE";
};

export type ScoreboardRow = {
  rank: number;
  team_id: number;
  team_name: string;
  nat_alias: string | null;
  country_code: string;
  total: number;
  total_delta: number;
  service_cells: Record<string, ServiceCell>;
  totals: {
    attack_points: number;
    defense_points: number;
    uptime_points: number;
    service_total: number;
    flags_captured: number;
    attackers_count: number;
    victims_count: number;
  };
};

export type ScoreboardResponse = {
  generated_at: string;
  rotation_seconds: number;
  round_id: number;
  game_state: string;
  desired_state: string;
  start_at: number | null;
  stop_after_tick: number | null;
  next_tick_at_epoch: number;
  seconds_to_next_tick: number;
  frozen: boolean;
  freeze_tick: number | null;
  display_tick: number | null;
  services: Service[];
  rows: ScoreboardRow[];
  service_tops: Record<string, ServiceTop | null>;
  tick_activity: TickActivity | null;
};

export type ServiceTop = {
  team_name: string;
  country_code: string;
  attackers_count: number;
  victims_count: number;
  service_total: number;
  first_blood?: ServiceFirstBlood | null;
};

export type ServiceFirstBlood = {
  id: number;
  timestamp: number | null;
  service_id: number;
  service_name: string | null;
  service_slug?: string | null;
  service_display_name: string | null;
  attacker_team: string;
  attacker_country: string | null;
  victim_team: string | null;
  victim_country: string | null;
  tick_issued: number | null;
  payload: number | null;
};

export type TickActivityEvent = {
  id: number;
  timestamp: number | null;
  attacker_team: string;
  attacker_country: string | null;
  victim_team: string | null;
  victim_country: string | null;
  service_id: number | null;
  service_name: string | null;
  service_slug?: string | null;
  service_display_name: string | null;
  tick_issued: number | null;
  payload: number | null;
  is_firstblood: boolean;
};

export type TickActivity = {
  tick: number | null;
  capture_count: number;
  first_blood_count: number;
  attackers_count: number;
  victims_count: number;
  captures: TickActivityEvent[];
  first_bloods: TickActivityEvent[];
};

export function fetchScoreboard(opts: {
  includeNop?: boolean;
  public?: boolean;
}): Promise<ScoreboardResponse> {
  const params = new URLSearchParams();
  if (opts.includeNop) params.set("include_nop", "true");
  if (opts.public) params.set("public", "true");
  return api.get<ScoreboardResponse>(`/api/v1/scoreboard?${params}`);
}

// ---------- Team tick history (drill-down) ----------

export type TickServiceBreakdown = {
  attack_points: number;
  attack_delta: number;
  defense_points: number;
  defense_delta: number;
  uptime_points: number;
  uptime_delta: number;
  flags_captured: number;
  flags_captured_delta: number;
};

export type TickEntry = {
  tick: number;
  services: Record<string, TickServiceBreakdown>;
  totals: TickServiceBreakdown & { score: number; score_delta: number };
};

export type TeamHistoryResponse = {
  team: {
    id: number;
    name: string;
    country_code: string;
    nat_alias: string | null;
    is_nop: boolean;
  };
  services: Service[];
  ticks: TickEntry[];
};

export function fetchTeamHistory(
  teamId: number,
  limit = 60,
): Promise<TeamHistoryResponse> {
  return api.get<TeamHistoryResponse>(
    `/api/v1/team/${teamId}/history?limit=${limit}`,
  );
}

// ---------- Admin types ----------

export type TimerSnapshot = {
  state: string;
  desired_state: string;
  current_tick: number;
  rotation_seconds: number;
  seconds_to_next_tick: number;
  tick_end?: number | null;
  start_at?: number | null;
  stop_after_tick?: number | null;
  scoreboard_freeze_tick?: number | null;
};

export type Dashboard = {
  summary: {
    timer: TimerSnapshot;
    accepted_submissions: number;
    total_submissions: number;
    bad_checkers: number;
  };
  submissions_chart: ChartData;
  checkers_chart: ChartData;
};

export type ChartData = {
  labels: string[];
  datasets: Array<{
    label?: string;
    data: number[];
    backgroundColor?: string | string[];
  }>;
};

export type CheckerRow = {
  tick: number;
  team: string;
  service: string;
  status: string;
  message: string;
  runtime_seconds: number | null;
  checked_at: string | null;
  job_id: number | null;
  job_status: string | null;
  attempts: number;
};

export type CheckersResponse = {
  filters: { ticks: number[]; teams: string[]; services: string[] };
  rows: CheckerRow[];
};

export type CheckerJobLogs = {
  rows: Array<{
    method: string;
    related_tick: number | null;
    payload: number | null;
    status: string;
    message: string;
    runtime_seconds: number | null;
    trace: string | null;
    created_at: string | null;
  }>;
};

export type FlagRow = {
  flag: string;
  team: string;
  service: string;
  tick: number;
  payload: number;
  created_at: string | null;
};

export type FlagsRecent = { pattern: string; rows: FlagRow[] };

export type DecodeReport =
  | { valid: false; error: string }
  | {
      valid: true;
      tick: number;
      team: string;
      service: string;
      payload: number;
      verdict: string;
      submitted_before: boolean;
      is_firstblood: boolean;
    };

export type SubmissionRow = {
  submitted_at: string | null;
  submitter: string;
  target: string | null;
  service: string | null;
  result: string;
  tick_issued: number | null;
  is_firstblood: boolean;
  points_awarded: number;
  flag_short: string;
};

export type SubmissionsResponse = { rows: SubmissionRow[]; chart: ChartData };

export type ServiceTargetRow = {
  id: number;
  team: string;
  service: string;
  enabled: boolean;
  host: string;
  port: number | null;
};

export type TeamRow = {
  id: number;
  name: string;
  submit_token: string;
  nat_alias: string;
  is_nop: boolean;
  country_code: string;
  created_at: string | null;
};

export type TeamsResponse = { rows: TeamRow[] };

export type TeamCreateInput = {
  name: string;
  nat_alias?: string;
  country_code?: string;
  is_nop?: boolean;
  submit_token?: string;
};

export type TeamUpdateInput = Partial<TeamCreateInput>;

export type LogRow = {
  created_at: string | null;
  component: string;
  level: number;
  level_label: string;
  title: string;
  text: string;
};

export type LogsResponse = {
  rows: LogRow[];
  components: string[];
  levels: Array<{ value: number; label: string }>;
};

export type AnalyticsServiceActivity = {
  id: number;
  name: string;
  slug: string;
  attackers: number[];
  victims: number[];
  captures: number[];
};

export type FirstBloodEvent = {
  id: number;
  timestamp: string | null;
  tick: number | null;
  payload: number | null;
  attacker: string;
  attacker_country: string | null;
  victim: string | null;
  victim_country: string | null;
  service: string | null;
  service_slug: string | null;
};

export type HeatmapTeam = { id: number; name: string; total: number };
export type HeatmapCell = { attacker_id: number; victim_id: number; captures: number };

export type AnalyticsResponse = {
  latest_tick: number;
  tick_range: { start: number; end: number; labels: string[] };
  top_teams: Array<{ id: number; name: string; country_code: string; total: number }>;
  score_history: ChartData;
  service_activity: { labels: string[]; services: AnalyticsServiceActivity[] };
  sla_trends: ChartData;
  first_bloods: FirstBloodEvent[];
  heatmap: {
    attackers: HeatmapTeam[];
    victims: HeatmapTeam[];
    cells: HeatmapCell[];
    max: number;
  };
};

export type ChallengeCatalogItem = {
  path: string;
  name: string;
  slot: string;
  categories: string[];
  flagstores: number;
  difficulty: string;
  runtime: string;
  vulnerabilities: number;
  rabbit_holes: number;
  summary: string;
  patch_notes: string | null;
};

export type ChallengeCatalogResponse = {
  can_reveal_patches: boolean;
  patches_revealed: boolean;
  challenges: ChallengeCatalogItem[];
};

export type NetworkResponse = {
  settings: Record<string, string | null | undefined>;
  teams: Array<{
    team_id: number;
    team: string;
    team_cidr: string;
    gateway_ip: string;
    vulnbox_ip: string;
    player_ip: string;
    player_public_key: string;
  }>;
  acl_policy: string[];
};

export type VulnboxRow = {
  id: number;
  team_id: number;
  team: string;
  backend: string;
  desired_status: string;
  observed_status: string;
  host: string | null;
  ip_address: string | null;
  reset_generation: number;
  restart_generation: number;
  rebuild_generation: number;
  last_report_at: string | null;
  updated_at: string | null;
};

export type VulnboxEvent = {
  created_at: string | null;
  team: string | null;
  action: string;
  status: string;
  message: string;
};

export type VulnboxesResponse = { rows: VulnboxRow[]; events: VulnboxEvent[] };

export type ObservabilityResponse = {
  latest_tick: number;
  tick_range: { start: number; end: number };
  queue_depths: Record<string, number | null>;
  checker_status: Record<string, number>;
  runtime_histogram: Record<string, number>;
  sla_rows: Array<{ service: string; tick: number; sla: number }>;
  submission_rates: Array<{ tick: number; result: string; n: number }>;
  first_bloods: Array<{
    id: number;
    submitted_at: string | null;
    tick: number | null;
    attacker: string;
    victim: string | null;
    service: string | null;
  }>;
  failed_checks: Array<{
    id: number;
    tick: number;
    team: string;
    service: string;
    status: string;
    method: string | null;
    message: string;
    trace: string | null;
    created_at: string | null;
  }>;
  workers: Array<{ worker_name: string; last_seen: string | null; active_jobs: number }>;
  alerts: Array<{ severity: string; title: string; detail: string }>;
  operational_health: {
    readiness: "ok" | "warning" | "danger" | string;
    database: string;
    redis: string;
    queue_total: number | null;
    worker_count: number;
    active_worker_count: number;
    overdue_jobs: number;
    stale_vulnboxes: number;
    crashed_jobs: number;
  };
};

// ---------- Admin endpoints ----------

export const admin = {
  me: () =>
    api.get<{ authenticated: boolean; username?: string }>("/admin/api/me"),
  login: (username: string, password: string) =>
    api.post<{ ok: true; username: string }>("/admin/api/login", {
      username,
      password,
    }),
  logout: () => api.post<{ ok: true }>("/admin/api/logout"),

  dashboard: () => api.get<Dashboard>("/admin/api/dashboard"),
  analytics: (params: { ticks?: number; top?: number }) =>
    api.get<AnalyticsResponse>(`/admin/api/analytics?${qs(params)}`),
  observability: (params: { ticks?: number }) =>
    api.get<ObservabilityResponse>(`/admin/api/observability?${qs(params)}`),
  challenges: (params: { include_patches?: boolean }) =>
    api.get<ChallengeCatalogResponse>(`/admin/api/challenges?${qs(params)}`),
  network: () => api.get<NetworkResponse>("/admin/api/network"),
  networkSync: () => api.post<{ ok: true; teams: number; settings: number }>("/admin/api/network/sync"),
  networkExportUrl: () => "/admin/api/network/export",
  submissionsExportUrl: () => "/admin/api/export/submissions.csv",
  checkerFailuresExportUrl: () => "/admin/api/export/checker-failures.csv",
  scoreboardExportUrl: () => "/admin/api/export/scoreboard.json",
  logsExportUrl: () => "/admin/api/export/logs.csv",
  vulnboxes: () => api.get<VulnboxesResponse>("/admin/api/vulnboxes"),
  vulnboxesSync: () => api.post<{ ok: true; count: number }>("/admin/api/vulnboxes/sync"),
  vulnboxAction: (id: number, action: string) =>
    api.post<{ ok: true; task_id: string }>(`/admin/api/vulnboxes/${id}/action`, { action }),
  checkers: (params: Record<string, string | number | undefined>) =>
    api.get<CheckersResponse>(`/admin/api/checkers?${qs(params)}`),
  checkerLogs: (jobId: number) => api.get<CheckerJobLogs>(`/admin/api/checkers/${jobId}/logs`),
  flagsRecent: (q?: string) =>
    api.get<FlagsRecent>(`/admin/api/flags/recent?${qs({ q })}`),
  decodeFlag: (flag: string) =>
    api.post<DecodeReport>("/admin/api/flags/decode", { flag }),
  submissions: (params: Record<string, string | number | undefined>) =>
    api.get<SubmissionsResponse>(`/admin/api/submissions?${qs(params)}`),

  game: () => api.get<TimerSnapshot>("/admin/api/game"),
  gameStart: () => api.post<TimerSnapshot>("/admin/api/game/start"),
  gamePause: () => api.post<TimerSnapshot>("/admin/api/game/pause"),
  gameStop: () => api.post<TimerSnapshot>("/admin/api/game/stop"),
  gameSchedule: (body: {
    start_at?: number | null;
    stop_after_tick?: number | null;
    scoreboard_freeze_tick?: number | null;
  }) => api.post<TimerSnapshot>("/admin/api/game/schedule", body),

  services: (params: { q?: string; only?: "on" | "off" }) =>
    api.get<{ rows: ServiceTargetRow[] }>(`/admin/api/services?${qs(params)}`),
  servicesToggle: (ts_id: number, enabled: boolean) =>
    api.post<{ ok: true }>("/admin/api/services/toggle", { ts_id, enabled }),

  logs: (params: Record<string, string | number | undefined>) =>
    api.get<LogsResponse>(`/admin/api/logs?${qs(params)}`),

  teams: () => api.get<TeamsResponse>("/admin/api/teams"),
  teamCreate: (body: TeamCreateInput) =>
    api.post<TeamRow>("/admin/api/teams", body),
  teamUpdate: (id: number, body: TeamUpdateInput) =>
    api.patch<TeamRow>(`/admin/api/teams/${id}`, body),
  teamDelete: (id: number) =>
    api.del<{ ok: true; deleted_id: number }>(`/admin/api/teams/${id}`),
  teamRotateToken: (id: number) =>
    api.post<TeamRow>(`/admin/api/teams/${id}/rotate-token`),

  // Patches
  patchesList: () =>
    api.get<{ rows: PatchRow[]; services: { id: number; name: string }[] }>(
      "/admin/api/patches",
    ),
  patchesUpload: async (
    serviceName: string,
    file: File,
    notes: string,
  ): Promise<PatchRow> => {
    const fd = new FormData();
    fd.append("service_name", serviceName);
    fd.append("notes", notes);
    fd.append("file", file);
    const res = await fetch("/admin/api/patches", {
      method: "POST",
      credentials: "same-origin",
      body: fd,
    });
    if (!res.ok) throw new HttpError(res.status, await res.text());
    return res.json();
  },
  patchesUpdate: (id: number, notes: string) =>
    api.patch<PatchRow>(`/admin/api/patches/${id}`, { notes }),
  patchesDelete: (id: number) =>
    api.del<{ ok: true; deleted_id: number }>(`/admin/api/patches/${id}`),

  // Wiki
  wikiList: () => api.get<{ rows: WikiPage[] }>("/admin/api/wiki"),
  wikiGet: (slug: string) => api.get<WikiPage>(`/admin/api/wiki/${slug}`),
  wikiUpsert: (body: WikiUpsertInput) => api.post<WikiPage>("/admin/api/wiki", body),
  wikiDelete: (slug: string) =>
    api.del<{ ok: true; deleted_slug: string }>(`/admin/api/wiki/${slug}`),
};

// ---------- Patches ----------

export type PatchRow = {
  id: number;
  service_id: number | null;
  service_name: string;
  filename: string;
  content_type: string;
  notes: string;
  sha256: string;
  size_bytes: number;
  created_at: string | null;
};

export function patchDownloadUrl(id: number): string {
  return `/api/v1/patches/${id}/download`;
}

export function fetchPublicPatches(service?: string): Promise<{ rows: PatchRow[] }> {
  const sp = new URLSearchParams();
  if (service) sp.set("service", service);
  const q = sp.toString();
  return api.get<{ rows: PatchRow[] }>(`/api/v1/patches${q ? "?" + q : ""}`);
}

// ---------- Wiki ----------

export type WikiPage = {
  id: number;
  slug: string;
  title: string;
  body_md?: string;
  is_published: boolean;
  sort_order: number;
  created_at: string | null;
  updated_at: string | null;
};

export type WikiUpsertInput = {
  slug: string;
  title: string;
  body_md?: string;
  is_published?: boolean;
  sort_order?: number;
};

export function fetchPublicWikiIndex(): Promise<{ rows: WikiPage[] }> {
  return api.get<{ rows: WikiPage[] }>("/api/v1/wiki");
}

export function fetchPublicWikiPage(slug: string): Promise<WikiPage> {
  return api.get<WikiPage>(`/api/v1/wiki/${encodeURIComponent(slug)}`);
}

function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  return sp.toString();
}
