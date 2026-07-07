"""Pure-logic tests for end-of-cycle objective completion (FK-based).

Every task carries an explicit ``objective_id`` (the CEO tags each dispatched
initiative; sub-tasks inherit it), so completion is a direct roll-up: an active
objective is closed when a cycle delivered at least one done task tagged with it
and no failed one. The DB wrapper is a thin query around
:func:`delivered_objective_ids`; these tests pin the rule without a database.
"""

from __future__ import annotations

import uuid

from app.services.objectives import delivered_objective_ids, objectives_prompt_block


class _Obj:
    def __init__(self, title: str) -> None:
        self.id = uuid.uuid4()
        self.title = title


def test_delivered_when_tagged_work_all_succeeded() -> None:
    grow, soc2, pricing = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    delivered = delivered_objective_ids(
        objective_ids=[grow, soc2, pricing],
        done_objective_ids=[grow, grow],  # two done tasks tagged to grow
        failed_objective_ids=[],
    )
    assert grow in delivered
    assert soc2 not in delivered  # no tagged work
    assert pricing not in delivered


def test_failed_tagged_task_blocks_completion() -> None:
    soc2 = uuid.uuid4()
    # A done task is tagged to it, but so is a failed one — not fully delivered.
    delivered = delivered_objective_ids(
        objective_ids=[soc2],
        done_objective_ids=[soc2],
        failed_objective_ids=[soc2],
    )
    assert soc2 not in delivered


def test_untagged_tasks_are_ignored() -> None:
    grow = uuid.uuid4()
    # None objective_ids (untagged work) never complete anything.
    delivered = delivered_objective_ids(
        objective_ids=[grow],
        done_objective_ids=[None, None],
        failed_objective_ids=[None],
    )
    assert delivered == []


def test_only_active_objectives_are_considered() -> None:
    grow, stale = uuid.uuid4(), uuid.uuid4()
    # `stale` isn't in the active list, so even a done task tagged to it is a no-op.
    delivered = delivered_objective_ids(
        objective_ids=[grow],
        done_objective_ids=[grow, stale],
        failed_objective_ids=[],
    )
    assert delivered == [grow]


def test_no_done_work_completes_nothing() -> None:
    grow = uuid.uuid4()
    assert delivered_objective_ids([grow], [], []) == []


def test_objectives_prompt_block_numbers_from_one() -> None:
    block = objectives_prompt_block([_Obj("Grow signups"), _Obj("Pass SOC2")])
    assert "1. Grow signups" in block
    assert "2. Pass SOC2" in block
    # The CEO is told the number is what it passes as `objective`.
    assert "objective" in block.lower()


def test_objectives_prompt_block_empty_when_no_objectives() -> None:
    assert objectives_prompt_block([]) == ""
