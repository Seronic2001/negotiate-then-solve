"""A world's state survives a server restart (``web.world.use_state_dir``)."""

import pytest

from web import world as world_mod
from web.world import World

pytestmark = pytest.mark.slow  # builds worlds and solves


@pytest.fixture
def state_dir(tmp_path):
    world_mod.use_state_dir(tmp_path / "state")
    yield tmp_path
    world_mod.use_state_dir(None)


def build(tmp_path):
    return World(parser_mode="offline", seed_history=False, deadline=5, semester_dir=tmp_path / "semester")


def wait_for_snapshot(w):
    import time

    end = time.time() + 30
    while w.snapshot is None and time.time() < end:
        time.sleep(0.2)
    assert w.snapshot is not None


def test_a_restart_carries_on_where_it_stopped(state_dir):
    w = build(state_dir)
    wait_for_snapshot(w)
    r = w.intake.from_portal("F-105", "I'd prefer no classes before 10 am on Friday, if possible.")
    w.submit(r, wait=True)
    status = w.orch.cases[r.id].status
    versions = len(w.store.versions())
    assert w.save() and not w.save()  # written once; nothing new the second time

    again = build(state_dir)
    assert again.seeding is False and set(again.orch.cases) == {r.id}
    assert again.orch.cases[r.id].status == status and len(again.store.versions()) == versions
    assert any(e["kind"] == "resumed" for e in again.store.events())
    assert again.snapshot is not None  # the demo state came back too: restore works at once
    again.restore()
    assert r.id not in again.orch.cases


def test_a_saved_state_for_another_department_is_ignored(state_dir):
    w = build(state_dir)
    wait_for_snapshot(w)
    r = w.intake.from_portal("F-105", "I'd prefer no classes before 10 am on Friday, if possible.")
    w.submit(r, wait=True)
    w.save()
    w._fingerprint = "something else"
    w._saved_mark = None
    w.save()  # as if written for a different department
    again = build(state_dir)
    assert not again.orch.cases  # started afresh


def test_a_request_caught_mid_way_starts_again(state_dir):
    from core.schemas import RequestStatus

    w = build(state_dir)
    wait_for_snapshot(w)
    r = w.intake.from_portal("F-105", "I'd prefer no classes before 10 am on Friday, if possible.")
    w.submit(r, wait=True)
    case = w.orch.cases[r.id]
    case.request.status = RequestStatus.NEGOTIATING  # as if the server stopped while it negotiated
    w._saved_mark = None
    w.save()
    again = build(state_dir)
    for t in list(again.threads.values()):
        t.join(timeout=120)
    assert again.orch.cases[r.id].status in (RequestStatus.AWAITING_APPROVAL, RequestStatus.PUBLISHED)
    assert any(e["kind"] == "restarted" for e in again.store.events(r.id))
