"""
Bot response queue: serializes bot replies per room so multiple personas do not talk over each other.
"""

import asyncio
from typing import Dict, Callable, Optional
from dataclasses import dataclass


@dataclass
class BotResponse:
    """One queued bot reply task."""
    room_id: str
    bot_name: str
    user_id: str
    user_text: str
    priority: int = 0  # 0=low, 1=medium, 2=high
    handler: Optional[Callable] = None

    def __lt__(self, other):
        return self.priority > other.priority  # higher priority first


class BotResponseQueue:
    """
    Per-room response queues:
    - One active processor per room
    - Optional priority ordering
    """

    def __init__(self, max_concurrent_per_room: int = 1):
        self.max_concurrent_per_room = max_concurrent_per_room
        self.room_limits: Dict[str, int] = {}
        self.queues: Dict[str, asyncio.PriorityQueue] = {}
        self.processing_count: Dict[str, int] = {}
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        self.cancelled_rooms: set = set()

    def set_room_concurrency(self, room_id: str, n: int) -> None:
        self.room_limits[room_id] = max(1, int(n))

    def _limit_for_room(self, room_id: str) -> int:
        return self.room_limits.get(room_id, self.max_concurrent_per_room)

    def _get_queue(self, room_id: str) -> asyncio.PriorityQueue:
        if room_id not in self.queues:
            self.queues[room_id] = asyncio.PriorityQueue()
            self.processing_count[room_id] = 0
        return self.queues[room_id]

    async def enqueue(self, response: BotResponse):
        queue = self._get_queue(response.room_id)
        await queue.put((-response.priority, response))
        print(f"📋 Bot response queued: {response.bot_name} in {response.room_id}")

    def cancel_room(self, room_id: str) -> None:
        """Drop pending bot work when a group chat ends."""
        self.cancelled_rooms.add(room_id)
        queue = self.queues.get(room_id)
        if queue:
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        task = self.processing_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()
        self.processing_count[room_id] = 0
        print(f"🛑 Bot queue cancelled for room {room_id}")

    def is_room_cancelled(self, room_id: str) -> bool:
        return room_id in self.cancelled_rooms

    async def _process_queue(self, room_id: str):
        queue = self._get_queue(room_id)
        try:
            while not queue.empty():
                if room_id in self.cancelled_rooms:
                    break
                if self.processing_count[room_id] >= self._limit_for_room(room_id):
                    await asyncio.sleep(0.5)
                    continue
                try:
                    _, response = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if room_id in self.cancelled_rooms:
                    break
                self.processing_count[room_id] += 1
                print(f"🤖 Processing bot response: {response.bot_name} in {response.room_id}")
                try:
                    if response.handler:
                        await response.handler(response)
                except Exception as e:
                    print(f"❌ Error processing bot response: {e}")
                finally:
                    self.processing_count[room_id] -= 1
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ Error in queue processor: {e}")
        finally:
            self.cancelled_rooms.discard(room_id)

    async def ensure_queue_processor(self, room_id: str):
        if room_id in self.cancelled_rooms:
            return
        if room_id not in self.processing_tasks or self.processing_tasks[room_id].done():
            self.processing_tasks[room_id] = asyncio.create_task(self._process_queue(room_id))


bot_response_queue = BotResponseQueue(max_concurrent_per_room=1)
