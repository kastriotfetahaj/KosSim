CREATE TABLE IF NOT EXISTS teams (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    submit_token TEXT UNIQUE NOT NULL,
    nat_alias TEXT NOT NULL,
    is_nop BOOLEAN NOT NULL DEFAULT FALSE,
    country_code TEXT NOT NULL DEFAULT 'XK',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    display_name TEXT,
    internal_port INTEGER NOT NULL DEFAULT 8080,
    num_payloads INTEGER NOT NULL DEFAULT 1,
    flags_per_tick INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS team_services (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 8080,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(team_id, service_id)
);

CREATE TABLE IF NOT EXISTS flag_rounds (
    round_id BIGINT PRIMARY KEY,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    rotation_seconds INTEGER NOT NULL,
    tick INTEGER UNIQUE
);

CREATE TABLE IF NOT EXISTS flags (
    id BIGSERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    round_id BIGINT NOT NULL REFERENCES flag_rounds(round_id) ON DELETE CASCADE,
    flag TEXT NOT NULL UNIQUE,
    payload INTEGER NOT NULL DEFAULT 0,
    attack_info TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE(team_id, service_id, round_id, payload)
);

CREATE INDEX IF NOT EXISTS idx_flags_active ON flags(active);
CREATE INDEX IF NOT EXISTS idx_flags_team_service ON flags(team_id, service_id);

CREATE TABLE IF NOT EXISTS submissions (
    id BIGSERIAL PRIMARY KEY,
    submitter_team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    target_team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
    round_id BIGINT REFERENCES flag_rounds(round_id) ON DELETE SET NULL,
    tick_issued INTEGER,
    payload INTEGER,
    flag TEXT NOT NULL,
    result TEXT NOT NULL,
    points_awarded INTEGER NOT NULL DEFAULT 0,
    is_firstblood BOOLEAN NOT NULL DEFAULT FALSE,
    source_ip TEXT,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(submitter_team_id, flag)
);

CREATE INDEX IF NOT EXISTS idx_submissions_firstblood
    ON submissions(is_firstblood, submitted_at DESC) WHERE is_firstblood;

CREATE INDEX IF NOT EXISTS idx_submissions_submitter_round_result
    ON submissions(submitter_team_id, round_id, result);

CREATE TABLE IF NOT EXISTS scores (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
    attack_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    defense_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    uptime_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    hacked_penalty_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    challenge_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    sla_points NUMERIC(14, 4) NOT NULL DEFAULT 1,
    total NUMERIC(14, 4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_health (
    id BIGSERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    round_id BIGINT NOT NULL REFERENCES flag_rounds(round_id) ON DELETE CASCADE,
    tick INTEGER,
    is_up BOOLEAN NOT NULL,
    status TEXT NOT NULL DEFAULT 'OFFLINE',
    message TEXT,
    attack_info TEXT,
    flag_avail JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime_seconds NUMERIC(10, 3),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(team_id, service_id, round_id)
);

CREATE TABLE IF NOT EXISTS team_tick_points (
    id BIGSERIAL PRIMARY KEY,
    tick INTEGER NOT NULL,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    off_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    def_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    sla_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    sla_delta NUMERIC(14, 4) NOT NULL DEFAULT 0,
    flag_captured_count INTEGER NOT NULL DEFAULT 0,
    flag_stolen_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tick, team_id, service_id)
);

CREATE INDEX IF NOT EXISTS idx_team_tick_points_lookup
    ON team_tick_points(team_id, service_id, tick DESC);

CREATE TABLE IF NOT EXISTS score_snapshots (
    id BIGSERIAL PRIMARY KEY,
    round_id BIGINT NOT NULL,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    attack_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    defense_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    uptime_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    hacked_penalty_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    challenge_points NUMERIC(14, 4) NOT NULL DEFAULT 0,
    service_total NUMERIC(14, 4) NOT NULL DEFAULT 0,
    flags_captured INTEGER NOT NULL DEFAULT 0,
    attackers_count INTEGER NOT NULL DEFAULT 0,
    victims_count INTEGER NOT NULL DEFAULT 0,
    sla_up_count INTEGER NOT NULL DEFAULT 0,
    sla_total_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(round_id, team_id, service_id)
);

CREATE INDEX IF NOT EXISTS idx_score_snapshots_team_service ON score_snapshots(team_id, service_id, round_id);

CREATE TABLE IF NOT EXISTS log_messages (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    component TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 5,
    title TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_log_messages_created ON log_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_log_messages_level ON log_messages(level DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS checker_jobs (
    id BIGSERIAL PRIMARY KEY,
    tick INTEGER NOT NULL,
    round_id BIGINT NOT NULL REFERENCES flag_rounds(round_id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    celery_task_id TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    deadline_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    last_error TEXT,
    result_status TEXT,
    runtime_seconds NUMERIC(10, 3),
    UNIQUE(tick, team_id, service_id)
);

CREATE INDEX IF NOT EXISTS idx_checker_jobs_tick_status ON checker_jobs(tick, status);
CREATE INDEX IF NOT EXISTS idx_checker_jobs_deadline ON checker_jobs(deadline_at);

CREATE TABLE IF NOT EXISTS checker_attempts (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES checker_jobs(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    celery_task_id TEXT,
    worker_name TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    runtime_seconds NUMERIC(10, 3),
    error TEXT,
    UNIQUE(job_id, attempt_no)
);

CREATE INDEX IF NOT EXISTS idx_checker_attempts_job ON checker_attempts(job_id, started_at DESC);

CREATE TABLE IF NOT EXISTS checker_step_logs (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES checker_jobs(id) ON DELETE CASCADE,
    attempt_id BIGINT REFERENCES checker_attempts(id) ON DELETE SET NULL,
    method TEXT NOT NULL,
    related_tick INTEGER,
    payload INTEGER,
    status TEXT NOT NULL,
    message TEXT,
    runtime_seconds NUMERIC(10, 3),
    trace TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_checker_step_logs_job ON checker_step_logs(job_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_checker_step_logs_failures ON checker_step_logs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS checker_worker_heartbeats (
    worker_name TEXT PRIMARY KEY,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active_jobs INTEGER NOT NULL DEFAULT 0,
    version TEXT NOT NULL DEFAULT 'kossim'
);

CREATE TABLE IF NOT EXISTS network_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS team_networks (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
    team_cidr TEXT NOT NULL,
    gateway_ip TEXT NOT NULL,
    vulnbox_ip TEXT NOT NULL,
    player_ip TEXT NOT NULL,
    player_private_key TEXT NOT NULL,
    player_public_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vulnboxes (
    id BIGSERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    backend TEXT NOT NULL DEFAULT 'docker',
    desired_status TEXT NOT NULL DEFAULT 'RUNNING',
    observed_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    host TEXT,
    ip_address TEXT,
    reset_generation INTEGER NOT NULL DEFAULT 0,
    restart_generation INTEGER NOT NULL DEFAULT 0,
    rebuild_generation INTEGER NOT NULL DEFAULT 0,
    last_report_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(team_id, backend)
);

CREATE INDEX IF NOT EXISTS idx_vulnboxes_status ON vulnboxes(desired_status, observed_status);

CREATE TABLE IF NOT EXISTS vulnbox_events (
    id BIGSERIAL PRIMARY KEY,
    vulnbox_id BIGINT REFERENCES vulnboxes(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vulnbox_events_created ON vulnbox_events(created_at DESC);

CREATE TABLE IF NOT EXISTS game_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    state TEXT NOT NULL DEFAULT 'STOPPED',
    desired_state TEXT NOT NULL DEFAULT 'STOPPED',
    current_tick INTEGER NOT NULL DEFAULT 0,
    tick_start BIGINT,
    tick_end BIGINT,
    start_at BIGINT,
    stop_after_tick INTEGER,
    scoreboard_freeze_tick INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
