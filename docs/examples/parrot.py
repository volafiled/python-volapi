#!/usr/bin/env python3

# Any copyright is dedicated to the Public Domain.
# http://creativecommons.org/publicdomain/zero/1.0/

import re

from volapi import Room


def listen(room):
    def onmessage(m):
        print(m)
        if m.admin or m.nick == r.user.name:
            return
        if "parrot" in m.msg.lower():
            r.post_chat("ayy lmao")
        elif m.msg.lower() in ("lol", "lel", "kek"):
            r.post_chat("*kok")
        else:
            r.post_chat(re.sub(r"\blain\b", "purpleadmin", m.msg, re.I))

    r = Room(room)
    r.user.change_nick("DumbParrot")
    r.listen(onmessage=onmessage)

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Provide a room ID", file=sys.stderr)
        sys.exit(1)

    while True:
        try:
            listen(sys.argv[1])
        except Exception as ex:
            print("Error listening", ex, file=sys.stderr)
        except KeyboardInterrupt:
            print("\nUser canceled this boat!!!1!", file=sys.stderr)
            sys.exit(0)
