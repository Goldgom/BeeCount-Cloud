from __future__ import annotations

import asyncio

from src.websocket_manager import WSConnectionManager


class _Socket:
    def __init__(self, *, delay: float = 0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.messages: list[str] = []

    async def accept(self) -> None:
        return None

    async def send_text(self, message: str) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("closed")
        self.messages.append(message)


def test_broadcast_sends_to_all_connections_concurrently() -> None:
    async def run() -> None:
        manager = WSConnectionManager(send_timeout=1)
        fast = _Socket(delay=0.01)
        slow = _Socket(delay=0.01)
        await manager.connect("u1", fast)  # type: ignore[arg-type]
        await manager.connect("u1", slow)  # type: ignore[arg-type]

        await manager.broadcast_to_user("u1", {"type": "sync_change"})
        assert fast.messages == slow.messages
        assert tuple(manager.online_user_ids()) == ("u1",)

    asyncio.run(run())


def test_failed_connections_are_removed_without_affecting_healthy_ones() -> None:
    async def run() -> None:
        manager = WSConnectionManager(send_timeout=1)
        healthy = _Socket()
        failed = _Socket(fail=True)
        await manager.connect("u1", healthy)  # type: ignore[arg-type]
        await manager.connect("u1", failed)  # type: ignore[arg-type]

        await manager.broadcast_to_user("u1", {"ok": True})
        assert healthy.messages
        assert manager._connections["u1"] == {healthy}  # noqa: SLF001

    asyncio.run(run())
