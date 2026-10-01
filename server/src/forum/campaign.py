from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forum.ledger import Ledger, LedgerEntry


class CampaignCycleError(ValueError):
    """Raised when a campaign's feature dependency graph contains a cycle.

    A ValueError subclass so a caller can catch the generic validation failure or
    the specific cycle. Detected by Kahn layering in ``Campaign.validate``.
    """


@dataclass(frozen=True, slots=True)
class Feature:
    """One unit of best-effort work in a campaign, executed by a forum agent.

    ``depends_on`` names sibling feature ids (across the whole campaign, not just
    the owning project) that must be witnessed-done before this feature runs.
    ``done_when`` are acceptance criteria carried onto the dispatched Task.
    """

    feature_id: str
    title: str
    agent: str
    instruction: str
    priority: int = 0
    depends_on: tuple[str, ...] = ()
    done_when: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Project:
    """A group of features under one owner.

    ``owner`` is ``"forum"`` (forum executes its features) or ``"external:<name>"``
    (an outside system such as telos owns it; forum only records ingested status,
    never dispatches its features).
    """

    project_id: str
    owner: str
    priority: int
    features: tuple[Feature, ...]


@dataclass(frozen=True, slots=True)
class Campaign:
    """A witnessed multi-project best-effort plan, one altitude above a plan.

    The campaign is declared once (a ``campaign_declared`` ledger entry); its live
    status is never stored, only reduced from the ledger (see campaign_status).
    """

    campaign_id: str
    title: str
    projects: tuple[Project, ...]

    def all_features(self) -> tuple[Feature, ...]:
        return tuple(f for p in self.projects for f in p.features)

    def feature_project(self, feature_id: str) -> Project:
        for project in self.projects:
            for feature in project.features:
                if feature.feature_id == feature_id:
                    return project
        raise KeyError(feature_id)

    def owner_of(self, feature_id: str) -> str:
        return self.feature_project(feature_id).owner

    def validate(self) -> None:
        """Raise on duplicate ids, a dep on an unknown feature, or a dependency cycle.

        Pure and await-free; declare_campaign calls this BEFORE any append so a bad
        campaign never touches the ledger.
        """
        features = self.all_features()
        ids: set[str] = set()
        for feature in features:
            if feature.feature_id in ids:
                raise ValueError(f"duplicate feature id: {feature.feature_id!r}")
            ids.add(feature.feature_id)
        for feature in features:
            for dep in feature.depends_on:
                if dep not in ids:
                    raise ValueError(
                        f"feature {feature.feature_id!r} depends on unknown feature {dep!r}"
                    )
        # Kahn layering: repeatedly remove features whose deps are all resolved.
        remaining = {f.feature_id: set(f.depends_on) for f in features}
        done: set[str] = set()
        while remaining:
            ready = sorted(fid for fid, deps in remaining.items() if deps <= done)
            if not ready:
                raise CampaignCycleError(
                    f"dependency cycle among features: {sorted(remaining)}"
                )
            done.update(ready)
            for fid in ready:
                del remaining[fid]


def _feature_payload(feature: Feature) -> dict[str, Any]:
    return {
        "feature_id": feature.feature_id,
        "title": feature.title,
        "agent": feature.agent,
        "instruction": feature.instruction,
        "priority": feature.priority,
        "depends_on": list(feature.depends_on),
        "done_when": list(feature.done_when),
    }


def _project_payload(project: Project) -> dict[str, Any]:
    return {
        "project_id": project.project_id,
        "owner": project.owner,
        "priority": project.priority,
        "features": [_feature_payload(f) for f in project.features],
    }


def campaign_payload(campaign: Campaign) -> dict[str, Any]:
    """Serialize a campaign to the campaign_declared payload dict (round-trips)."""
    return {
        "campaign_id": campaign.campaign_id,
        "title": campaign.title,
        "projects": [_project_payload(p) for p in campaign.projects],
    }


def _feature_from_payload(body: dict[str, Any]) -> Feature:
    return Feature(
        feature_id=str(body["feature_id"]),
        title=str(body.get("title", "")),
        agent=str(body.get("agent", "")),
        instruction=str(body.get("instruction", "")),
        priority=int(body.get("priority", 0)),
        depends_on=tuple(str(d) for d in body.get("depends_on", ())),
        done_when=tuple(str(d) for d in body.get("done_when", ())),
    )


def _project_from_payload(body: dict[str, Any]) -> Project:
    return Project(
        project_id=str(body["project_id"]),
        owner=str(body.get("owner", "forum")),
        priority=int(body.get("priority", 0)),
        features=tuple(_feature_from_payload(f) for f in body.get("features", ())),
    )


def campaign_from_payload(body: dict[str, Any]) -> Campaign:
    """Rebuild a Campaign from a campaign_declared payload dict."""
    return Campaign(
        campaign_id=str(body["campaign_id"]),
        title=str(body.get("title", "")),
        projects=tuple(_project_from_payload(p) for p in body.get("projects", ())),
    )


def declare_campaign(
    ledger: Ledger, campaign: Campaign, *, causal_parent: int | None = None
) -> LedgerEntry:
    """Validate then witness a campaign as ONE campaign_declared entry.

    await-free. validate() runs first, so a campaign with a duplicate id, an
    unknown dep, or a cycle raises and NOTHING is appended.
    """
    campaign.validate()
    return ledger.append(
        actor="campaign",
        kind="campaign_declared",
        payload=campaign_payload(campaign),
        causal_parent=causal_parent,
    )
