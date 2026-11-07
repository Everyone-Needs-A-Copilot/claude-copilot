"""A completed failed check cannot spend another dispatch in its generation."""
import copy

import pytest

from tc.db.exceptions import ConflictError
from tc.services import cycles
from tests.cycle_stage_fixtures import make_world


@pytest.mark.parametrize("prior", ["failed", "stale"])
def test_terminal_result_requires_generation_transition_before_new_claim(tmp_path, prior):
    world = make_world(tmp_path, count=1)
    world.freeze()
    world.start("q1")
    world.result("q1", "C1", "failed" if prior == "failed" else "passed",
                 defect="fixture-isolation")
    world.stop("q1")
    if prior == "stale":
        (world.root / "src/item1.py").write_text("VALUE = 2\n")
    before = copy.deepcopy(world.status())

    with pytest.raises(ConflictError):
        cycles.claim_stream(cycle=world.cycle, stream="q1", agent="new-worker",
                            cwd=world.root, db_path=world.db)

    after = world.status()
    assert after["streams"]["q1"]["claim"] == before["streams"]["q1"]["claim"]
    assert after["checkResults"] == before["checkResults"]
    assert "q1" not in after["ready"]
    assert any("generation" in str(row) for row in after["queued"])

    # The supported transition retains history and permits the corrected scope.
    if prior == "failed":
        world.collect()
    world.advance("candidate-integrated")
    fresh = world.start("q1")
    assert fresh["token"] != before["streams"]["q1"]["claim"]["token"]
    assert world.status()["generation"] == before["generation"] + 1


def test_retained_pass_does_not_block_missing_case_after_transition(tmp_path):
    def configure(plan, root, db):
        extra = copy.deepcopy(plan["checks"][0])
        extra["id"] = "C2"
        plan["checks"].append(extra)

    world = make_world(tmp_path, count=1, configure=configure)
    world.freeze()
    world.start("q1")
    world.result("q1", "C1")
    world.stop("q1")
    retained = copy.deepcopy(world.status()["checkResults"]["C1"])
    world.advance("candidate-integrated")
    world.start("q1")
    world.result("q1", "C2")
    world.stop("q1")
    assert world.status()["checkResults"]["C1"] == retained
    world.collect()
    world.accept()
