"""
Cache Manager: in-memory message cache with batched DB writes.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict


class CacheManager:
    """
    In-memory cache:
    - Message buffer per room
    - Batch flush to DB (threshold or timer)
    """

    def __init__(self, batch_size: int = 50, flush_interval: float = 30.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.message_cache: Dict[str, List[Dict]] = defaultdict(list)
        self.on_flush_callback = None
        self.flush_task = None

    def set_persist_callback(self, callback):
        """Register async callback invoked on flush."""
        self.on_flush_callback = callback

    async def start(self):
        """Start periodic flush loop."""
        self.flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self):
        """Stop periodic flush loop."""
        if self.flush_task:
            self.flush_task.cancel()

    def cache_message(self, room_id: str, sender: str, text: str) -> bool:
        """Cache one message. Returns True if batch_size threshold was reached."""
        message = {
            "room_id": room_id,
            "sender": sender,
            "text": text,
            "timestamp": datetime.now().isoformat(),
        }
        self.message_cache[room_id].append(message)
        total_messages = sum(len(msgs) for msgs in self.message_cache.values())
        return total_messages >= self.batch_size

    def get_cached_messages(self, room_id: str) -> List[Dict]:
        """Return cached messages for a room."""
        return self.message_cache.get(room_id, [])

    async def flush_messages(self, room_id: Optional[str] = None) -> int:
        """Persist cached messages via callback."""
        if self.on_flush_callback is None:
            return 0

        flushed_count = 0

        if room_id:
            if room_id in self.message_cache:
                messages = self.message_cache[room_id]
                if messages:
                    await self.on_flush_callback("messages", messages)
                    flushed_count = len(messages)
                    self.message_cache[room_id] = []
        else:
            for rid, messages in list(self.message_cache.items()):
                if messages:
                    await self.on_flush_callback("messages", messages)
                    flushed_count += len(messages)
                    self.message_cache[rid] = []

        if flushed_count > 0:
            print(f"✅ Flushed {flushed_count} messages to DB")

        return flushed_count

    def invalidate_summary(self, room_id: str):
        """No-op kept for callers that invalidate after context updates."""
        pass

    async def _periodic_flush(self):
        """Flush all rooms on an interval."""
        try:
            while True:
                await asyncio.sleep(self.flush_interval)
                total_messages = sum(len(msgs) for msgs in self.message_cache.values())
                if total_messages > 0:
                    await self.flush_messages()
        except asyncio.CancelledError:
            await self.flush_messages()


cache_manager = CacheManager(batch_size=50, flush_interval=30.0)
