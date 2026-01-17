import os
import time
from typing import Any, Dict, List, Optional

import requests


class SupabaseClient:
    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_ROLE"]
        self.session = requests.Session()
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _rest(
        self,
        table: str,
        params: Optional[Dict[str, str]] = None,
        json_body=None,
        method="post",
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        url = f"{self.url}/rest/v1/{table}"
        headers = dict(self.headers)
        if extra_headers:
            headers.update(extra_headers)
        resp = self.session.request(method, url, headers=headers, params=params, json=json_body, timeout=60)
        resp.raise_for_status()
        if resp.text:
            return resp.json()
        return None

    def log_run(self, job_type: str) -> str:
        start = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {"job_type": job_type, "started_at": start, "status": "running"}
        res = self._rest("runs", json_body=data)
        return res[0]["id"]

    def finish_run(
        self, run_id: str, status: str, processed: int = 0, error: Optional[str] = None, notes: Optional[str] = None
    ):
        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self._rest(
            "runs",
            params={"id": f"eq.{run_id}"},
            json_body={
                "finished_at": finished_at,
                "status": status,
                "processed_count": processed,
                "error": error,
                "notes": notes,
            },
            method="patch",
        )

    def upsert_matches(self, matches: List[Dict[str, Any]]) -> None:
        if not matches:
            return
        self._rest(
            "matches",
            params={"on_conflict": "league,kickoff_utc,home_team,away_team"},
            json_body=matches,
            method="post",
            extra_headers={"Prefer": "resolution=merge-duplicates"},
        )

    def fetch_matches(self, params: Dict[str, str]) -> List[Dict[str, Any]]:
        return self._rest("matches", params=params, method="get") or []

    def insert_prediction(self, payload: Dict[str, Any]) -> None:
        self._rest("predictions", json_body=payload, method="post")

    def insert_result(self, payload: Dict[str, Any]) -> None:
        self._rest("results", json_body=payload, method="post")

    def fetch_predictions(self, match_id: str) -> List[Dict[str, Any]]:
        return self._rest("predictions", params={"match_id": f"eq.{match_id}"}, method="get") or []

    def upsert_baseline(self, baseline: Dict[str, Any]) -> None:
        self._rest(
            "baselines",
            params={"on_conflict": "match_id"},
            json_body=baseline,
            method="post",
            extra_headers={"Prefer": "resolution=merge-duplicates"},
        )

    def update_match_status(self, match_id: str, status: str):
        self._rest("matches", params={"id": f"eq.{match_id}"}, json_body={"status": status}, method="patch")

    def fetch_results(self, params: Dict[str, str]) -> List[Dict[str, Any]]:
        return self._rest("results", params=params, method="get") or []
