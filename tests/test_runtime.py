import asyncio

from forum.executor import Assignment, Result
from forum.roster import load_default
from forum.runtime import TieredExecutor


class _Named:
    def __init__(self, model_id):
        self.model_id = model_id
        self.calls = []

    async def run(self, assignment):
        self.calls.append(assignment)
        return Result(assignment.task_id, assignment.agent, self.model_id)


def test_tiered_executor_selects_by_roster_model_tier():
    roster = load_default()
    default = _Named("default-local")
    cheap = _Named("cheap-local")
    capable = _Named("capable-local")
    frontier = _Named("frontier-local")
    ex = TieredExecutor(
        roster,
        default,
        tiers={"cheap": cheap, "capable": capable, "frontier": frontier},
    )

    backend = Assignment("T1", "backend", "build")
    docs = Assignment("T2", "technical-writing", "docs")
    foundry = Assignment("T3", "model-foundry", "eval")
    control = Assignment("control:coordinator", "coordinator", "plan")

    assert ex.select(backend) is capable
    assert ex.select(docs) is cheap
    assert ex.select(foundry) is frontier
    assert ex.select(control) is default
    assert ex.model_id_for(backend) == "capable-local"
    assert ex.model_id_for(control) == "default-local"


def test_tiered_executor_runs_selected_executor():
    roster = load_default()
    default = _Named("default-local")
    capable = _Named("capable-local")
    ex = TieredExecutor(roster, default, tiers={"capable": capable})

    result = asyncio.run(ex.run(Assignment("T1", "backend", "build api")))

    assert result.output == "capable-local"
    assert capable.calls[0].instruction == "build api"
    assert default.calls == []
