from __future__ import annotations

from forum.ledger import Ledger, LedgerEntry


def ingest_project_status(
    ledger: Ledger,
    campaign_id: str,
    project_id: str,
    status: str,
    *,
    source: str,
    reason: str = "",
    reporter: str = "operator",
) -> LedgerEntry:
    """Record an external project's status WITHOUT executing anything.

    Appends a project_status entry carrying ``source`` (e.g. "external:telos").
    This is the telos/gather seam: forum witnesses what an outside system reports;
    it does not dispatch the project's work. await-free.
    """
    return ledger.append(
        actor=reporter,
        kind="project_status",
        payload={
            "campaign_id": campaign_id,
            "project_id": project_id,
            "status": status,
            "reason": reason,
            "source": source,
        },
    )


def ingest_feature_status(
    ledger: Ledger,
    campaign_id: str,
    project_id: str,
    feature_id: str,
    status: str,
    *,
    source: str,
    reason: str = "",
    reporter: str = "operator",
) -> LedgerEntry:
    """Record an external feature's status WITHOUT executing it.

    Appends a feature_status entry carrying ``source`` but NO witnessed_seq. The
    reducer honors an external done as done but labels it distinctly (external,
    not forum-witnessed) and never treats it as a violation or a forum-verified
    result. await-free.
    """
    return ledger.append(
        actor=reporter,
        kind="feature_status",
        payload={
            "campaign_id": campaign_id,
            "project_id": project_id,
            "feature_id": feature_id,
            "status": status,
            "reason": reason,
            "source": source,
        },
    )
