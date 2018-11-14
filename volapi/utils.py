"""
The MIT License (MIT)
Copyright © 2015 RealDolos
See LICENSE
"""

import json
import random
import string

from contextlib import contextmanager
from html.parser import HTMLParser
from collections import OrderedDict
from threading import Barrier, BrokenBarrierError


class MLStripper(HTMLParser):
    """Used for stripping HTML from text."""

    def __init__(self):
        super().__init__()
        self.fed = []

    def handle_data(self, data):
        self.fed.append(data)

    def get_data(self):
        """Gets the non-HTML data from text that was fed in"""

        return "".join(self.fed)


def html_to_text(html):
    """Strips HTML tags from given text and returns it."""

    stripper = MLStripper()
    stripper.feed(html)
    return stripper.get_data()


def random_id(length):
    """Generates a random ID of given length"""

    def char():
        """Generate single random char"""

        return random.choice(string.ascii_letters + string.digits)

    return "".join(char() for _ in range(length))


def to_json(obj):
    """Create a compact JSON string from an object"""

    return json.dumps(obj, separators=(",", ":"))


@contextmanager
def delayed_close(closable):
    """Delay close until this contextmanager dies"""

    close = getattr(closable, "close", None)
    if close:
        # we do not want the library to close file in case we need to
        # resume, hence make close a no-op
        # pylint: disable=unused-argument
        def replacement_close(*args, **kw):
            """ No op """
            pass

        # pylint: enable=unused-argument
        setattr(closable, "close", replacement_close)
    try:
        yield closable
    finally:
        if close:
            setattr(closable, "close", close)
            closable.close()


CALLBACKS = OrderedDict({0: None})


class SmartEvent:

    """Helper Event class that deals with lain's callbacks"""

    def __init__(self):
        self._last_id = list(CALLBACKS.keys())[-1]
        self._data_to_return = None
        self._cb_to_phase_out = None
        CALLBACKS[self._last_id] = Barrier(2, timeout=3)
        CALLBACKS[self._last_id + 1] = None

    @property
    def callback_id(self):
        return str(self._last_id)

    def wait(self):
        if CALLBACKS[self._last_id] is not None:
            try:
                CALLBACKS[self._last_id].wait()
            except BrokenBarrierError as ex:
                raise ValueError(
                    "The API call you made isn't callback-compatible!"
                ) from ex
        del CALLBACKS[self._cb_to_phase_out]
        return self._data_to_return

    def set(self, callback_id, data):
        callback_id = int(callback_id)
        self._cb_to_phase_out = callback_id
        self._data_to_return = data
        try:
            CALLBACKS[callback_id].wait()
        except BrokenBarrierError:
            CALLBACKS[callback_id] = None
