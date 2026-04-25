-- Creating the teams table
CREATE TABLE IF NOT EXISTS teams (
    team_id    VARCHAR(64)  PRIMARY KEY,
    team_name  VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

-- Creating the API keys table
CREATE TABLE IF NOT EXISTS api_keys (
    api_key    VARCHAR(128) PRIMARY KEY,
    team_id    VARCHAR(64)  REFERENCES teams(team_id),
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

-- Creating the request logs table
CREATE TABLE IF NOT EXISTS request_logs (
    id                BIGSERIAL    PRIMARY KEY,
    api_key           VARCHAR(128),
    team_id           VARCHAR(64),
    model_name        VARCHAR(64),
    prompt_tokens     INT,
    completion_tokens INT,
    total_tokens      INT GENERATED ALWAYS AS (prompt_tokens + completion_tokens) STORED,
    cost_usd          NUMERIC(12, 6),
    latency_ms        INT,
    status_code       INT,
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);

-- Creating the rate limit violations table
CREATE TABLE IF NOT EXISTS rate_limit_violations (
    id         BIGSERIAL    PRIMARY KEY,
    api_key    VARCHAR(128),
    team_id    VARCHAR(64),
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

-- Creating indexes for common dashboard query patterns
CREATE INDEX IF NOT EXISTS idx_logs_team_id    ON request_logs(team_id);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_api_key    ON request_logs(api_key);
CREATE INDEX IF NOT EXISTS idx_violations_team ON rate_limit_violations(team_id);
