import asyncio

from app.services.generation_hub import GenerationHub


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.fail = False

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(message)


def test_subscribe_snapshot_survives_unsubscribe():
    hub = GenerationHub()
    ws = FakeSocket()

    async def scenario():
        hub.upsert_job("u1", "c1", status_text="[think] Думаю", thinking=True, user_text="вопрос")
        jobs = await hub.subscribe("u1", ws)
        assert jobs[0]["conversation_id"] == "c1"
        assert jobs[0]["status_text"] == "[think] Думаю"
        await hub.unsubscribe("u1", ws)
        assert hub.get_job("u1", "c1") is not None
        assert hub.snapshots("u1")[0]["status_text"] == "[think] Думаю"

    asyncio.run(scenario())


def test_broadcast_reaches_reconnect_and_skips_dead_socket():
    hub = GenerationHub()
    dead = FakeSocket()
    dead.fail = True
    live = FakeSocket()

    async def scenario():
        await hub.subscribe("u1", dead)
        hub.upsert_job("u1", "c1", thinking=True, status_text="Ищу")
        await hub.broadcast("u1", {"type": "status", "payload": {"text": "Ищу", "conversation_id": "c1"}})
        await hub.subscribe("u1", live)
        await hub.broadcast("u1", {"type": "status", "payload": {"text": "Читаю github.com", "conversation_id": "c1"}})
        assert live.sent[-1]["payload"]["text"] == "Читаю github.com"
        assert hub.get_job("u1", "c1").status_text == "Ищу"

    asyncio.run(scenario())


def test_disconnect_does_not_cancel_running_task():
    hub = GenerationHub()
    ws = FakeSocket()
    started = asyncio.Event()
    finished = asyncio.Event()

    async def job():
        started.set()
        await asyncio.sleep(0.05)
        finished.set()

    async def scenario():
        await hub.subscribe("u1", ws)
        hub.start_task("u1", "c1", job())
        await started.wait()
        await hub.unsubscribe("u1", ws)
        assert hub.is_running("u1", "c1")
        await asyncio.wait_for(finished.wait(), timeout=1)
        assert not hub.is_running("u1", "c1")

    asyncio.run(scenario())


def test_rekey_moves_job_to_real_conversation():
    hub = GenerationHub()
    hub.upsert_job("u1", "pending:1", thinking=True, user_text="hello")
    hub.rekey("u1", "pending:1", "real")
    assert hub.get_job("u1", "pending:1") is None
    assert hub.get_job("u1", "real").user_text == "hello"
    assert hub.snapshots("u1")[0]["conversation_id"] == "real"
