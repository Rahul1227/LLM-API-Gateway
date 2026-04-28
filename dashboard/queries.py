from __future__ import annotations

from datetime import date

import pandas as pd


def get_team_usage(conn, start_date: date, end_date: date) -> pd.DataFrame:
    query = """
        SELECT
            team_id,
            COUNT(*) AS requests,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM request_logs
        WHERE created_at::date BETWEEN %s AND %s
        GROUP BY team_id
        ORDER BY cost_usd DESC
    """
    return pd.read_sql_query(query, conn, params=(start_date, end_date))


def get_cost_by_model(conn, team_id: str | None, start_date: date, end_date: date) -> pd.DataFrame:
    query = """
        SELECT
            team_id,
            model_name,
            COUNT(*) AS request_count,
            COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
            ROUND(COALESCE(AVG(cost_usd), 0), 6) AS avg_cost_per_request,
            COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS total_tokens,
            ROUND(COALESCE(SUM(cost_usd) / NULLIF(SUM(prompt_tokens + completion_tokens), 0), 0), 8) AS cost_per_token
        FROM request_logs
        WHERE created_at::date BETWEEN %s AND %s
          AND (%s IS NULL OR team_id = %s)
        GROUP BY team_id, model_name
        ORDER BY total_cost_usd DESC
    """
    return pd.read_sql_query(query, conn, params=(start_date, end_date, team_id, team_id))


def get_request_volume(conn, interval: str, start_date: date, end_date: date) -> pd.DataFrame:
    if interval not in {"hour", "day"}:
        interval = "day"
    query = """
        SELECT
            date_trunc(%s, created_at) AS period,
            COUNT(*) AS requests
        FROM request_logs
        WHERE created_at::date BETWEEN %s AND %s
        GROUP BY period
        ORDER BY period
    """
    return pd.read_sql_query(query, conn, params=(interval, start_date, end_date))


def get_violations(conn, limit: int) -> pd.DataFrame:
    query = """
        SELECT
            team_id,
            api_key,
            created_at
        FROM rate_limit_violations
        ORDER BY created_at DESC
        LIMIT %s
    """
    return pd.read_sql_query(query, conn, params=(limit,))
