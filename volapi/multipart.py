#!/usr/bin/env python3
"""
The MIT License (MIT)
Copyright © 2015 RealDolos
See LICENSE
"""

import collections
import json
import os
import sys
import uuid

from io import BytesIO
from urllib.parse import quote


def generate_boundary():
    """Generates a boundary string to be used for multipart/form-data"""

    return uuid.uuid4().hex


def escape_header(val):
    """Escapes a value so that it can be used in a mime header"""

    if val is None:
        return None
    try:
        return quote(val, encoding="ascii", safe="/ ")
    except ValueError:
        return "utf-8''" + quote(val, encoding="utf-8", safe="/ ")


def make_streams(name, value, boundary, encoding):
    """Generates one or more streams for each name, value pair"""

    filename = None
    mime = None

    # user passed in a special dict.
    if isinstance(value, collections.Mapping) and "name" in value and "value" in value:
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

    stream = BytesIO()
    stream.write("--{}\r\n".format(boundary).encode(encoding))
    if not filename:
        stream.write(
            'Content-Disposition: form-data; name="{}"\r\n'.format(name).encode(
                encoding
            )
        )
    else:
        stream.write(
            'Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.format(
                name, filename
            ).encode(encoding)
        )
        if mime:
            stream.write("Content-Type: {}\r\n".format(mime).encode(encoding))
    stream.write(b"\r\n")

    if hasattr(value, "read"):
        stream.seek(0)
        return stream, value, BytesIO("\r\n".encode(encoding))

    # not a file-like object, encode headers and value in one go
    value = value if isinstance(value, (str, bytes)) else json.dumps(value)
    if isinstance(value, bytes):
        stream.write(value)
    else:
        stream.write(value.encode(encoding))
    stream.write(b"\r\n")
    stream.seek(0)
    return (stream,)


class Data:
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

    def __init__(
        self, values, blocksize=0, encoding="utf-8", callback=None, logical_offset=0
    ):
        self.encoding = encoding or "utf-8"
        self.boundary = generate_boundary()
        self.streams = []
        self.callback = callback or None
        self.blocksize = blocksize
        self.logical_offset = logical_offset
        if not self.blocksize or self.blocksize <= 0:
            self.blocksize = 1 << 17

        for name, value in values.items():
            self.streams.extend(make_streams(name, value, self.boundary, encoding))
        self.streams.append(
            BytesIO("--{}--\r\n".format(self.boundary).encode(encoding))
        )

    @property
    def len(self):
        """Length of the data stream"""
        # The len property is needed for requests.
        # requests checks __len__, then len
        # Since we cannot implement __len__ because python 32-bit uses 32-bit
        # sizes, we implement this instead.
        def stream_len(stream):
            """Stream length"""
            cur = stream.tell()
            try:
                stream.seek(0, 2)
                return stream.tell() - cur
            finally:
                stream.seek(cur)

        return sum(stream_len(s) for s in self.streams)

    @property
    def headers(self):
        """All headers needed to make a request"""
        return {
            "Content-Type": ("multipart/form-data; boundary={}".format(self.boundary)),
            "Content-Length": str(self.len),
            "Content-Encoding": self.encoding,
        }

    def __iter__(self):
        with self:
            total = None
            if self.callback:
                total = self.len
            pos = 0
            remainder = self.blocksize
            buf = BytesIO()
            stream = self.streams.pop(0)
            while stream:
                with stream:
                    while remainder:
                        cur = stream.read(remainder)
                        if not cur:
                            break
                        buf.write(cur)
                        remainder -= len(cur)
                        if not remainder:
                            val = buf.getvalue()
                            yield val
                            if self.callback:
                                pos += len(val)
                                self.callback(
                                    self.logical_offset + pos,
                                    self.logical_offset + total,
                                )
                            remainder = self.blocksize
                            buf = BytesIO()
                try:
                    stream = self.streams.pop(0)
                except IndexError:
                    break

            last = buf.getvalue()
            if not last:
                return

            pos += len(last)
            yield last
            if self.callback:
                self.callback(self.logical_offset + pos, self.logical_offset + total)

    def __enter__(self):
        return self

    def __exit__(self, _extype, _value, _traceback):
        self.close()

    def close(self):
        """Close multipart instance and all associated streams"""
        try:
            for stream in self.streams:
                with stream:
                    pass
        finally:
            del self.streams[:]


if __name__ == "__main__":
    import requests

    def my_callback(cur, tot):
        """multipart callback"""
        print(cur, tot, "{:.2%}".format(float(cur) / tot), file=sys.stderr)

    def main():
        """main()"""
        multipart = {
            "abc": "def",
            "123": 345,
            "flt": 1.0,
            "json": {"hellow": ["world"]},
            "special": {"name": "huhu русский язык 中文", "value": "value"},
            "file1": open(__file__, "rb"),
            "file2": {
                "name": "file.py",
                "value": open(__file__, "rb"),
                "mime": "application/x-python",
            },
        }
        multipart = Data(multipart, callback=my_callback, blocksize=100)

        if len(sys.argv) > 1:
            print(
                requests.post(
                    sys.argv[1], headers=multipart.headers, data=multipart
                ).content
            )
            sys.exit(0)

        for key, val in multipart.headers.items():
            print("{}: {}".format(key, val), file=sys.stderr)
        for i in multipart:
            sys.stdout.buffer.write(i)
            sys.stdout.flush()
        sys.exit(0)

    main()
