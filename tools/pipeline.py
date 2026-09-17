"""Application pipeline: what happened after the job was found.

discover_jobs finds roles and find_hiring_people finds who to talk to, but
neither remembers what you actually did. This closes that loop — one row per
application, and a follow-up rule per stage so nothing goes quiet unnoticed.
"""
import time

from tools.storage import (
    delete_application,
    get_applications,
    upsert_application,
)

# Ordered by funnel depth. Anything not in here is rejected at the tool boundary.
STATUSES = (
    "interested",
    "applied",
    "screening",
    "interviewing",
    "offer",
    "rejected",
    "ghosted",
)

# Stages that are still live — only these get chased.
OPEN_STATUSES = ("interested", "applied", "screening", "interviewing")

# Days of silence before a stage is considered stale and worth a nudge.
STALE_AFTER = {
    "interested": 3,     # decide or drop it
    "applied": 7,        # standard follow-up window
    "screening": 5,
    "interviewing": 5,
}

NUDGE = {
    "interested": "Still open? Apply or mark it rejected so it stops taking up room.",
    "applied": "No word in {days}d. Message the hiring contact directly.",
    "screening": "Screening has gone quiet for {days}d. Ask where it stands.",
    "interviewing": "{days}d since the last interview touch. Chase the decision.",
}


def _days_since(ts: int) -> int:
    return max(0, int((time.time() - ts) // 86_400))


def track(
    url: str,
    status: str,
    company: str = "",
    title: str = "",
    notes: str = "",
    contact_reached: bool | None = None,
) -> dict:
    """Record or move one application. Status must be a member of STATUSES."""
    status = status.strip().lower()
    if status not in STATUSES:
        return {
            "error": f"unknown status {status!r}",
            "valid_statuses": list(STATUSES),
        }
    if not url:
        return {"error": "url is required — it is the primary key"}

    result = upsert_application(
        url=url,
        company=company.strip(),
        title=title.strip(),
        status=status,
        notes=notes.strip(),
        contact_reached=contact_reached,
    )
    moved = (
        not result["created"]
        and result.get("previous_status")
        and result["previous_status"] != status
    )
    result["message"] = (
        f"tracked as {status}"
        if result["created"]
        else f"moved {result['previous_status']} to {status}" if moved
        else f"updated, still {status}"
    )
    return result


def drop(url: str) -> dict:
    """Remove an application from the pipeline entirely."""
    return {"removed": delete_application(url)}


def _decorate(row: dict) -> dict:
    idle = _days_since(row["updated_at"])
    limit = STALE_AFTER.get(row["status"])
    return {
        "company": row["company"],
        "title": row["title"],
        "url": row["url"],
        "status": row["status"],
        "notes": row["notes"],
        "contact_reached": bool(row["contact_reached"]),
        "days_since_update": idle,
        "days_in_pipeline": _days_since(row["created_at"]),
        "stale": limit is not None and idle >= limit,
    }


def view(status: str = "", include_closed: bool = False) -> dict:
    """Full pipeline state: counts, follow-ups due, and the rows themselves.

    status          — restrict to one stage, e.g. "interviewing"
    include_closed  — keep rejected/ghosted rows in the listing
    """
    rows = [_decorate(r) for r in get_applications(status.strip().lower())]

    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    follow_ups = []
    for r in rows:
        if r["stale"] and r["status"] in OPEN_STATUSES:
            follow_ups.append({
                **r,
                "action": NUDGE[r["status"]].format(days=r["days_since_update"]),
            })
    follow_ups.sort(key=lambda r: -r["days_since_update"])

    listed = rows if include_closed else [
        r for r in rows if r["status"] in OPEN_STATUSES
    ]
    listed.sort(key=lambda r: (STATUSES.index(r["status"]), -r["days_since_update"]))

    applied = sum(counts[s] for s in ("applied", "screening", "interviewing", "offer"))
    reached = sum(1 for r in rows if r["contact_reached"])

    return {
        "totals": {
            "tracked": len(rows),
            "open": sum(counts[s] for s in OPEN_STATUSES),
            "applied_or_beyond": applied,
            "contacts_reached": reached,
        },
        "by_status": counts,
        "response_rate": round(
            (counts["screening"] + counts["interviewing"] + counts["offer"])
            / applied, 3
        ) if applied else 0.0,
        "follow_ups_due": follow_ups,
        "applications": listed,
    }
