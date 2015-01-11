#!/usr/bin/env python3

# Any copyright is dedicated to the Public Domain.
# http://creativecommons.org/publicdomain/zero/1.0/

import re

from volapi import Room


def listen(room):
    """Open a volafile room and start listening to it"""
    def onmessage(m):
        """Print the new message and respond to it."""
        print(m)
        if m.admin or m.nick == r.user.name:
            return
        if "parrot" in m.msg.lower():
            r.post_chat("ayy lmao")
        elif m.msg.lower() in ("lol", "lel", "kek"):
            r.post_chat("*kok")
        else:
            r.post_chat(re.sub(r"\blain\b", "purpleadmin", m.msg, re.I))

    with Room(room) as r:
        r.user.change_nick("DumbParrot")
        r.add_listener("chat", onmessage)
        r.listen()

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
