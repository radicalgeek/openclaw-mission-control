"""One-shot admin script to purge cron jobs registered against a specific agent
on the OpenClaw gateway.

Use case: an agent's LLM has registered a self-heartbeat (or similar) cron job
that fires periodically and fails (e.g. wrong sessionTarget, missing model).
The cron persists across worker restarts, so you can't fix it by restarting
the agent's session — you have to delete it via the gateway control plane.

Usage:
  python scripts/purge_agent_crons.py \
      --gateway-url ws://host:18789 \
      --gateway-token "$GATEWAY_TOKEN" \
      --session-prefix "agent:lead-d971ec5a-f657-43b3-be6d-e7574626c684" \
      [--dry-run]

The script lists ALL cron jobs (including disabled), filters to those whose
sessionKey starts with the given prefix, prints a summary, and (unless
``--dry-run``) issues ``cron.remove`` for each.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.openclaw.gateway_rpc import (  # noqa: E402
    GatewayConfig,
    OpenClawGatewayError,
    openclaw_call,
)

GatewayClientConfig = GatewayConfig


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", required=True, help="ws://host:port")
    parser.add_argument("--gateway-token", required=True, help="Gateway auth token")
    parser.add_argument(
        "--session-prefix",
        required=True,
        help='e.g. "agent:lead-<board_id>" or "agent:mc-<agent_id>"',
    )
    parser.add_argument(
        "--allow-insecure-tls",
        action="store_true",
        help="Skip TLS verification (use for self-signed or http→ws ingress)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matches but do not delete",
    )
    return parser.parse_args()


def _format_job(job: dict[str, Any]) -> str:
    job_id = job.get("id") or job.get("jobId") or "?"
    name = job.get("name", "?")
    session = job.get("sessionKey") or job.get("session_key") or "?"
    enabled = job.get("enabled", "?")
    schedule = job.get("schedule") or {}
    schedule_kind = schedule.get("kind", "?")
    return f"  - id={job_id} name={name!r} session={session} enabled={enabled} schedule={schedule_kind}"


async def _run(args: argparse.Namespace) -> int:
    config = GatewayClientConfig(
        url=args.gateway_url,
        token=args.gateway_token,
        allow_insecure_tls=args.allow_insecure_tls,
        disable_device_pairing=True,
    )

    # Page through cron.list (no fixed page size — the openclaw default returns
    # everything for typical deployments; if pagination becomes necessary the
    # response includes `total` and `nextOffset`).
    matches: list[dict[str, Any]] = []
    offset = 0
    while True:
        try:
            page = await openclaw_call(
                "cron.list",
                {"includeDisabled": True, "limit": 200, "offset": offset},
                config=config,
            )
        except OpenClawGatewayError as exc:
            print(f"cron.list failed at offset={offset}: {exc}", file=sys.stderr)
            return 2

        if not isinstance(page, dict):
            print(f"cron.list returned non-dict payload: {page!r}", file=sys.stderr)
            return 2

        items = page.get("items") or page.get("jobs") or []
        if not isinstance(items, list):
            print(f"cron.list returned no items list: {page!r}", file=sys.stderr)
            return 2

        for job in items:
            if not isinstance(job, dict):
                continue
            session_key = (
                job.get("sessionKey") or job.get("session_key") or job.get("agentId") or ""
            )
            if isinstance(session_key, str) and session_key.startswith(args.session_prefix):
                matches.append(job)

        next_offset = page.get("nextOffset")
        total = page.get("total")
        if next_offset is None or not items:
            break
        if isinstance(total, int) and offset + len(items) >= total:
            break
        offset = int(next_offset)

    if not matches:
        print(f"No cron jobs found matching session prefix {args.session_prefix!r}.")
        return 0

    print(f"Found {len(matches)} cron job(s) matching {args.session_prefix!r}:")
    for job in matches:
        print(_format_job(job))

    if args.dry_run:
        print("\n--dry-run: no deletions performed.")
        return 0

    failed = 0
    for job in matches:
        job_id = job.get("id") or job.get("jobId")
        if not job_id:
            print(f"  skip (no id): {job!r}")
            continue
        try:
            await openclaw_call("cron.remove", {"id": job_id}, config=config)
            print(f"  removed id={job_id}")
        except OpenClawGatewayError as exc:
            print(f"  FAILED to remove id={job_id}: {exc}", file=sys.stderr)
            failed += 1

    if failed:
        return 1
    return 0


def main() -> None:
    args = _parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
