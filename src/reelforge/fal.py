"""Thin transport for fal.ai's queue API. No model knowledge lives here."""

import time

import httpx

QUEUE = "https://queue.fal.run"


class FalError(RuntimeError):
    pass


class FalClient:
    """Submit → poll → fetch result on queue.fal.run."""

    dry = False

    def __init__(self, key: str, poll_s: float = 3.0):
        self._headers = {"Authorization": f"Key {key}"}
        self.poll_s = poll_s

    def run(self, model_id: str, payload: dict, timeout_s: float = 1800) -> dict:
        with httpx.Client(headers=self._headers, timeout=60) as http:
            r = http.post(f"{QUEUE}/{model_id}", json=payload)
            if r.status_code >= 400:
                raise FalError(f"submit {model_id}: HTTP {r.status_code}: {r.text[:500]}")
            sub = r.json()
            status_url, response_url = sub["status_url"], sub["response_url"]
            deadline = time.monotonic() + timeout_s
            while True:
                s = http.get(status_url).json()
                st = s.get("status")
                if st == "COMPLETED":
                    return http.get(response_url).json()
                if st in ("FAILED", "CANCELLED", "ERROR"):
                    raise FalError(f"{model_id} {st}: {s}")
                if time.monotonic() > deadline:
                    raise FalError(f"{model_id} timed out after {timeout_s}s ({status_url})")
                time.sleep(self.poll_s)

    def download(self, url: str, dest) -> None:
        with httpx.Client(timeout=300) as http, open(dest, "wb") as f:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes():
                    f.write(chunk)


class DryRunClient:
    """Marker client: generation services synthesize local placeholders instead."""

    dry = True


def get_balance(key: str) -> float | None:
    """Account balance in USD via the dashboard's billing endpoint.

    Undocumented but stable; return None rather than raise if it changes.
    """
    try:
        r = httpx.get("https://rest.alpha.fal.ai/billing/user_balance",
                      headers={"Authorization": f"Key {key}"}, timeout=10)
        r.raise_for_status()
        return float(r.text.strip())
    except Exception:
        return None
