#!/usr/bin/env python3

# Any copyright is dedicated to the Public Domain.
# http://creativecommons.org/publicdomain/zero/1.0/

import collections
import json
import os
import uuid

from io import BytesIO
from urllib.parse import quote


def generate_boundary():
    """Generates a boundary string to be used for multipart/form-data"""
    return uuid.uuid4().hex


def escape_header(v):
    """Escapes a value so that it can be used in a mime header"""
    if v is None:
        return None
    try:
        return quote(v, encoding="ascii", safe="/ ")
    except:
        return "utf-8''" + quote(v, encoding="utf-8", safe="/ ")


def make_streams(name, value, boundary, encoding):
    """Generates one or more streams for each name, value pair"""
    filename = None
    mime = None

    # user passed in a special dict.
    if (isinstance(value, collections.Mapping) and
            "name" in value and "value" in value):
        filename = value["name"]
        try:
            mime = value["mime"]
        except KeyError:
            pass
        value = value["value"]

    if not filename:
        filename = getattr(value, "name", None)
        if filename:
            filename = os.path.split(filename)[1]

    mime = mime or "application/octet-stream"

    name, filename, mime = [escape_header(v) for v in (name, filename, mime)]

    s = BytesIO()
    s.write("--{}\r\n".format(boundary).encode(encoding))
    if not filename:
        s.write('Content-Disposition: form-data; name="{}"\r\n'.
                format(name).encode(encoding))
    else:
        s.write('Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.
                format(name, filename).encode(encoding))
        if mime:
            s.write('Content-Type: {}\r\n'.format(mime).encode(encoding))
    s.write(b"\r\n")

    if hasattr(value, "read"):
        s.seek(0)
        return s, value, BytesIO("\r\n".encode(encoding))

    # not a file-like object, encode headers and value in one go
    value = (value
             if isinstance(value, str) or isinstance(value, bytes)
             else json.dumps(value))
    if isinstance(value, bytes):
        s.write(value)
    else:
        s.write(value.encode(encoding))
    s.write(b"\r\n")
    s.seek(0)
    return s,


class Data(object):
    """multipart/form-data generator

    The generator will own any file-like objects you pass in. You don't
    need to close such objects yourself.

    Supported value types:
     - POD types
     - file-like-objects
     - json-serializable objects (will be serialized as json

    You may specify file names and value types by passing special dicts
    that contain name, value and optionally mime keys. values will be
    treated like normal objects.

    Data objects must be iterated over (streamed). Each iteration result
    will contain at most blocksize bytes. This enables Data objects to
    encode multipart/form-data requests without having to read all data
    into memory at once
    """

    def __init__(self, values, blocksize=0, encoding="utf-8", cb=None):
        self.encoding = encoding or "utf-8"
        self.boundary = generate_boundary()
        self.streams = []
        self.cb = cb or None
        self.blocksize = blocksize
        if not self.blocksize or self.blocksize <= 0:
            self.blocksize = (1 << 17)

        for name, value in values.items():
            self.streams.extend(
                make_streams(name, value, self.boundary, encoding))
        self.streams.append(BytesIO("--{}--\r\n".
                                    format(self.boundary).encode(encoding)))

    def __len__(self):
        def stream_len(s):
            cur = s.tell()
            try:
                s.seek(0, 2)
                return s.tell() - cur
            finally:
                s.seek(cur)

        return sum(stream_len(s) for s in self.streams)

    @property
    def headers(self):
        """All headers needed to make a request"""
        return {"Content-Type": ("multipart/form-data; boundary={}".
                                 format(self.boundary)),
                "Content-Length": str(len(self)),
                "Content-Encoding": self.encoding
                }

    def __iter__(self):
        with self:
            total = None
            if self.cb:
                total = len(self)
            pos = 0
            remainder = self.blocksize
            b = BytesIO()
            s = self.streams.pop(0)
            while s:
                with s:
                    while remainder:
                        cur = s.read(remainder)
                        if not cur:
                            break
                        b.write(cur)
                        remainder -= len(cur)
                        if not remainder:
                            v = b.getvalue()
                            yield v
                            if self.cb:
                                pos += len(v)
                                self.cb(pos, total)
                            remainder = self.blocksize
                            b = BytesIO()
                try:
                    s = self.streams.pop(0)
                except IndexError:
                    break

            last = b.getvalue()
            if not last:
                return

            l = len(last)
            yield last
            if self.cb:
                self.cb(pos + l, total)

    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        try:
            for s in self.streams:
                with s:
                    pass
        finally:
            del self.streams[:]


if __name__ == "__main__":
    import requests
    from sys import argv, exit, stderr, stdout

    def cb(cur, tot):
        print(cur, tot, "{:.2%}".format(float(cur) / tot), file=stderr)

    data = {"abc": "def",
            "123": 345,
            "flt": 1.0,
            "json": {"hellow": ["world"]},
            "special": {"name": "huhu русский язык 中文", "value": "value"},
            "file1": open(__file__, "rb"),
            "file2": {"name": "file.py",
                      "value": open(__file__, "rb"),
                      "mime": "application/x-python"}
            }
    data = Data(data, cb=cb, blocksize=100)

    if len(argv) > 1:
        print(requests.post(argv[1], headers=data.headers, data=data).content)
        exit(0)

    for k, v in data.headers.items():
        print("{}: {}".format(k, v), file=stderr)
    for i in data:
        stdout.buffer.write(i)
        stdout.flush()
    exit(0)
