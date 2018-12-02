"""
The MIT License (MIT)
Copyright © 2015 RealDolos
Copyright © 2018 Szero
See LICENSE
"""
# pylint: disable=bad-continuation,broad-except

import logging
import sys
import asyncio

from collections import namedtuple
from collections import defaultdict
from functools import wraps
from threading import get_ident
from threading import Barrier
from threading import Condition
from threading import RLock
from threading import Thread, Event
from urllib.parse import urlsplit
from copy import copy

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
                logger.exception(
                    "failed to call async [%r] with [%r] [%r]", func, args, kw
                )

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
    The issue is that notify_all will temporarily release the
    lock to fire the listeners.

    If a listener would interact with volapi from there, this
    might mean a deadlock.
    Having the release on another thread will not block the
    event loop thread, therefore problem solved
    """

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

        if sys.platform != "win32":
            self.loop = asyncio.new_event_loop()
        else:
            self.loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(self.loop)
        barrier.wait()
        try:
            self.loop.run_forever()
        except Exception:
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

        factory = WebSocketClientFactory(ws_url, headers=headers, loop=self.loop)
        factory.useragent = agent
        factory.protocol = lambda: room
        conn = self.loop.create_connection(
            factory,
            host=urlparts.netloc,
            port=urlparts.port or 443,
            ssl=urlparts.scheme == "wss",
        )
        asyncio.ensure_future(conn, loop=self.loop)

    def __send_message(self, proto, payload):
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
    def send_sync_message(self, proto, payload):
        self.__send_message(proto, payload)

    @call_async
    def send_async_message(self, proto, payload):
        self.__send_message(proto, payload)

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


class Listeners(namedtuple("Listeners", ("callbacks", "queue", "enlock", "lock"))):
    """Collection of Listeners
    `callbacks` are function objects.
    `queue` holds data that will be sent to each function object
    in `callbacks` variable.
    Each issue of `process` method will run given callback
    against items in `queue` when their types match. After that
    `queue` is cleared and amount of `callbacks` is returned.
    Callbacks that return False will be removed."""

    def __new__(cls):
        return super().__new__(
            cls, defaultdict(list), defaultdict(list), RLock(), RLock()
        )

    def process(self):
        """Process queue for these listeners. Only the items with type that
        matches """

        with self.lock, self.enlock:
            queue = copy(self.queue)
            self.queue.clear()
            callbacks = copy(self.callbacks)

        with self.lock:
            rm_cb = False
            for ki, vi in queue.items():
                if ki in self.callbacks:
                    for item in vi:
                        for cb in self.callbacks[ki]:
                            if cb(item) is False:
                                callbacks[ki].remove(cb)
                                if not callbacks[ki]:
                                    del callbacks[ki]
                                rm_cb = True

        with self.lock:
            if rm_cb:
                self.callbacks.clear()
                for k, v in callbacks.items():
                    self.callbacks[k].extend(v)
            return len(self.callbacks)

    def add(self, callback_type, callback):
        """Add a new listener"""

        with self.lock:
            self.callbacks[callback_type].append(callback)

    def enqueue(self, item_type, item):
        """Queue a new data item, make item iterable"""

        with self.enlock:
            self.queue[item_type].append(item)

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
        return f"<Protocol({self.session},max_id={self.max_id},send_count={self.send_count})>"
