from __future__ import annotations

import os
import time
from datetime import date, timedelta

import psycopg2
import streamlit as st

from queries import (
    get_cost_by_model,
    get_request_volume,
    get_team_usage,
    get_violations,
)


POSTGRES_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://gateway:gateway@localhost:5432/gatewaydb",
)


@st.cache_resource
def get_connection():
    return psycopg2.connect(POSTGRES_DSN)


st.set_page_config(page_title="LLM Gateway Dashboard", layout="wide")
st.title("LLM Gateway Dashboard")

with st.sidebar:
    end_date = st.date_input("End date", value=date.today())
    start_date = st.date_input("Start date", value=end_date - timedelta(days=7))
    interval = st.selectbox("Volume interval", ["hour", "day"], index=1)
    violation_limit = st.number_input("Violation rows", min_value=10, max_value=500, value=50)

conn = get_connection()

team_usage = get_team_usage(conn, start_date, end_date)
team_options = ["All"] + team_usage["team_id"].dropna().astype(str).tolist()
with st.sidebar:
    selected_team = st.selectbox("Team", team_options)
team_filter = None if selected_team == "All" else selected_team

cost_by_model = get_cost_by_model(conn, team_filter or None, start_date, end_date)
request_volume = get_request_volume(conn, interval, start_date, end_date)
violations = get_violations(conn, int(violation_limit))

usage_section, cost_section, volume_section, violations_section = st.tabs(
    ["Team Usage", "Cost Breakdown", "Request Volume", "Rate Limit Violations"]
)

with usage_section:
    st.dataframe(team_usage, use_container_width=True)
    if not team_usage.empty:
        st.bar_chart(team_usage.set_index("team_id")["total_tokens"])

with cost_section:
    st.dataframe(cost_by_model, use_container_width=True)
    if not cost_by_model.empty:
        chart_data = cost_by_model.pivot_table(
            index="model_name",
            columns="team_id",
            values="cost_usd",
            aggfunc="sum",
            fill_value=0,
        )
        st.bar_chart(chart_data)

with volume_section:
    st.dataframe(request_volume, use_container_width=True)
    if not request_volume.empty:
        st.line_chart(request_volume.set_index("period")["requests"])

with violations_section:
    st.dataframe(violations, use_container_width=True)

time.sleep(30)
st.rerun()
