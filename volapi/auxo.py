"""
The MIT License (MIT)
Copyright © 2015 RealDolos
See LICENSE
"""
# pylint: disable=bad-continuation,broad-except

import logging
import asyncio

from collections import namedtuple
from functools import wraps
from threading import get_ident
from threading import Barrier
from threading import Condition
from threading import RLock
from threading import Thread, Event
from urllib.parse import urlsplit

from autobahn.asyncio.websocket import WebSocketClientFactory
from autobahn.asyncio.websocket import WebSocketClientProtocol
from requests import Request
from requests.cookies import get_cookie_header


logger = logging.getLogger(__name__)

def call_async(func):
    """Decorates a function to be called async on the loop thread"""

    @wraps(func)
    def wrapper(self, *args, **kw):
        """Wraps instance method to be called on loop thread"""
        def call():
            """Calls function on loop thread"""
            try:
                func(self, *args, **kw)
            except Exception:
                logger.exception("failed to call async [%r] with [%r] [%r]", func, args, kw)

        self.loop.call_soon_threadsafe(call)
    return wrapper


def call_sync(func):
    """Decorates a function to be called sync on the loop thread"""

    @wraps(func)
    def wrapper(self, *args, **kw):
        """Wraps instance method to be called on loop thread"""

        # Just return when already on the event thread
        if self.thread.ident == get_ident():
            return func(self, *args, **kw)

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
        try:
            self.loop.run_forever()
        except Exception:
            import sys
            sys.exit(1)

    @call_async
    def create_connection(self, room, ws_url, agent, cookies):
        """Creates a new connection"""

        urlparts = urlsplit(ws_url)
        req = Request("GET", ws_url)
        cookies = get_cookie_header(cookies, req)
        if cookies:
            headers = dict(Cookie=cookies)
        else:
            headers = None

        factory = WebSocketClientFactory(
                ws_url,
                headers=headers,
                loop=self.loop
                )
        factory.useragent = agent
        factory.protocol = lambda: room
        conn = self.loop.create_connection(factory,
                host=urlparts.netloc,
                port=urlparts.port or 443,
                ssl=urlparts.scheme == "wss",
                )
        asyncio.ensure_future(conn, loop=self.loop)

    @call_async
    def send_message(self, proto, payload):
        # pylint: disable=no-self-use
        """Sends a message"""

        try:
            if not isinstance(payload, bytes):
                payload = payload.encode("utf-8")
            if not proto.connected:
                raise IOError("not connected")
            proto.sendMessage(payload)
            logger.debug("sent: %r", payload)
        except Exception as ex:
            logger.exception("Failed to send message")
            proto.reraise(ex)

    @call_sync
    def close(self, proto):
        # pylint: disable=no-self-use
        """Closes a connection"""

        try:
            proto.sendClose()
        except Exception as ex:
            logger.exception("Failed to send close")
            proto.reraise(ex)


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
        self.session = None

    def onConnect(self, _response):
        self.connected = True

    async def onOpen(self):
        await self.conn.on_open()

    def onMessage(self, payload, _isBinary):
        if not payload:
            logger.warning("empty frame!")
            return

        try:
            if isinstance(payload, bytes):
                new_data = payload.decode("utf-8")
            self.conn.on_message(new_data)
        except Exception:
            logger.exception("something went horribly wrong")

    async def onClose(self, _wasClean, _code, _reason):
        await self.conn.on_close()
        self.connected = False

    def reraise(self, ex):
        if hasattr(self, "conn"):
            self.conn.reraise(ex)
        else:
            logger.error("Cannot reraise")

    def __repr__(self):
        return "<Protocol({},max_id={},send_count={})>".format(
                self.session, self.max_id, self.send_count)
