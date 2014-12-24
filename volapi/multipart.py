#!/usr/bin/env python3

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

import collections
import json
import os
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

    stream = BytesIO()
    stream.write("--{}\r\n".format(boundary).encode(encoding))
    if not filename:
        stream.write('Content-Disposition: form-data; name="{}"\r\n'.
                     format(name).encode(encoding))
    else:
        stream.write('Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.
                     format(name, filename).encode(encoding))
        if mime:
            stream.write('Content-Type: {}\r\n'.format(mime).encode(encoding))
    stream.write(b"\r\n")

    if hasattr(value, "read"):
        stream.seek(0)
        return stream, value, BytesIO("\r\n".encode(encoding))

    # not a file-like object, encode headers and value in one go
    value = (value
             if isinstance(value, str) or isinstance(value, bytes)
             else json.dumps(value))
    if isinstance(value, bytes):
        stream.write(value)
    else:
        stream.write(value.encode(encoding))
    stream.write(b"\r\n")
    stream.seek(0)
    return stream,


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

    def __init__(self, values, blocksize=0, encoding="utf-8", callback=None):
        self.encoding = encoding or "utf-8"
        self.boundary = generate_boundary()
        self.streams = []
        self.callback = callback or None
        self.blocksize = blocksize
        if not self.blocksize or self.blocksize <= 0:
            self.blocksize = (1 << 17)

        for name, value in values.items():
            self.streams.extend(
                make_streams(name, value, self.boundary, encoding))
        self.streams.append(BytesIO("--{}--\r\n".
                                    format(self.boundary).encode(encoding)))

    def __len__(self):
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
        return {"Content-Type": ("multipart/form-data; boundary={}".
                                 format(self.boundary)),
                "Content-Length": str(self.__len__()),
                "Content-Encoding": self.encoding
               }

    def __iter__(self):
        with self:
            total = None
            if self.callback:
                total = self.__len__()
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
                                self.callback(pos, total)
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
                self.callback(pos, total)

    def __enter__(self):
        return self

    def __exit__(self, extype, value, traceback):
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
    import sys

    def my_callback(cur, tot):
        """multipart callback"""
        print(cur, tot, "{:.2%}".format(float(cur) / tot), file=sys.stderr)

    def main():
        """main()"""
        multipart = {"abc": "def",
                     "123": 345,
                     "flt": 1.0,
                     "json": {"hellow": ["world"]},
                     "special": {"name": "huhu русский язык 中文",
                                 "value": "value"},
                     "file1": open(__file__, "rb"),
                     "file2": {"name": "file.py",
                               "value": open(__file__, "rb"),
                               "mime": "application/x-python"}
                    }
        multipart = Data(multipart, callback=my_callback, blocksize=100)

        if len(sys.argv) > 1:
            print(requests.post(sys.argv[1],
                                headers=multipart.headers,
                                data=multipart).content)
            sys.exit(0)

        for key, val in multipart.headers.items():
            print("{}: {}".format(key, val), file=sys.stderr)
        for i in multipart:
            sys.stdout.buffer.write(i)
            sys.stdout.flush()
        sys.exit(0)

    main()
