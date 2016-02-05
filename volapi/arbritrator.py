'''
This file is part of Volapi.

Volapi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Volapi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Volapi.  If not, see <http://www.gnu.org/licenses/>.
'''
# pylint: disable=bad-continuation,broad-except,star-args

import asyncio

from collections import namedtuple
from functools import wraps
from threading import Barrier
from threading import Condition
from threading import RLock
from threading import Thread, Event
from urllib.parse import urlsplit

from autobahn.asyncio.websocket import WebSocketClientFactory
from autobahn.asyncio.websocket import WebSocketClientProtocol

from .utils import to_json


def call_async(func):
    """Decorates a function to be called async on the loop thread"""

    @wraps(func)
    def wrapper(self, *args, **kw):
        """Wraps instance method to be called on loop thread"""
        def call():
            """Calls function on loop thread"""
            func(self, *args, **kw)

        self.loop.call_soon_threadsafe(call)
    return wrapper


def call_sync(func):
    """Decorates a function to be called sync on the loop thread"""

    @wraps(func)
    def wrapper(self, *args, **kw):
        """Wraps instance method to be called on loop thread"""
        barrier = Barrier(2)
        result = None
        ex = None

        def call():
            """Calls function on loop thread"""
            nonlocal result, ex
            try:
                result = func(self, *args, **kw)
            except Exception as exc:
                ex = exc
            finally:
                barrier.wait()

        self.loop.call_soon_threadsafe(call)
        barrier.wait()
        if ex:
            raise ex or Exception("Unknown error")
        return result
    return wrapper

class Awakener:
    """
    Callable helper thread to awaken non-event loop threads.
    The issue is that notify_all wil temporarily release the
    lock to fire the listeners.

    If a listener would interact with volapi from there, this
    might mean a deadlock.
    Having the release on another thread will not block the
    event loop thread, therefore problemb solved
    """
    # pylint: disable=too-few-public-methods
    def __init__(self, condition):
        self.condition = condition
        self.count = 0
        self.lock = RLock()
        self.event = Event()
        self.thread = Thread(daemon=True, target=self.target)
        self.thread.start()

    def __call__(self):
        with self.lock:
            self.count += 1
        self.event.set()

    def target(self):
        """Thread routine"""
        while self.event.wait():
            self.event.clear()
            while True:
                with self.lock:
                    if not self.count:
                        break
                    self.count -= 1
                with self.condition:
                    self.condition.notify_all()


class ListenerArbitrator:
    """Manages the asyncio loop and thread"""

    def __init__(self):
        self.loop = None
        self.condition = Condition()
        barrier = Barrier(2)
        self.awaken = Awakener(self.condition)
        self.thread = Thread(daemon=True, target=lambda: self._loop(barrier))
        self.thread.start()
        barrier.wait()

    def _loop(self, barrier):
        """Actual thread"""

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        barrier.wait()
        self.loop.run_forever()

    @call_sync
    def create_connection(self, room, ws_url, agent):
        """Creates a new connection"""

        factory = WebSocketClientFactory(ws_url, loop=self.loop)
        factory.useragent = agent
        factory.protocol = lambda: room
        ws_url = urlsplit(ws_url)
        conn = self.loop.create_connection(factory,
                                           host=ws_url.netloc,
                                           port=ws_url.port or 443,
                                           ssl=ws_url.scheme == "wss"
                                           )
        asyncio.async(conn, loop=self.loop)

    @call_async
    def send_message(self, conn, payload):
        """Sends a message"""
        # pylint: disable=no-self-use

        if not isinstance(payload, bytes):
            payload = payload.encode("utf-8")
        if conn.connected:
            conn.sendMessage(payload)

    @call_sync
    def close(self, conn):
        # pylint: disable=no-self-use
        """Closes a connection"""

        conn.sendClose()


ARBITRATOR = ListenerArbitrator()


class Listeners(namedtuple("Listeners", ("callbacks", "queue", "lock"))):
    """Collection of Listeners"""

    def __new__(cls):
        return super().__new__(cls, list(), list(), RLock())

    def process(self):
        """Process queue for these listeners"""
        with self.lock:
            items = list(self.queue)
            self.queue.clear()
            callbacks = list(self.callbacks)

        for item in items:
            callbacks = [c for c in callbacks
                         if c(item) is not False]

        with self.lock:
            self.callbacks.clear()
            self.callbacks.extend(callbacks)
            return len(self.callbacks)

    def add(self, callback):
        """Add a new listener"""

        with self.lock:
            self.callbacks.append(callback)

    def enqueue(self, item):
        """Queue a new data item"""

        with self.lock:
            self.queue.append(item)

    def __len__(self):
        """Return number of listeners in collection"""

        with self.lock:
            return len(self.callbacks)


class Protocol(WebSocketClientProtocol):
    """Implements the websocket protocol"""

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.connected = False
        self.max_id = 0
        self.send_count = 1

    def onConnect(self, response):
        self.connected = True

    def onOpen(self):
        while True:
            yield from asyncio.sleep(self.conn.ping_interval)
            self.conn.send_message("2")
            self.conn.send_message("4" + to_json([self.max_id]))

    def onMessage(self, new_data, binarybinary):
        # pylint: disable=unused-argument
        if not new_data:
            return

        if isinstance(new_data, bytes):
            new_data = new_data.decode("utf-8")
        self.conn.on_message(new_data)

    def onClose(self, clean, code, reason):
        # pylint: disable=unused-argument
        self.connected = False

