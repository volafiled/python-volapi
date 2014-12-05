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

import json
import os
import random
import re
import string
import time

import requests
import websocket

from threading import Barrier, Condition, Thread

from .multipart import Data

__version__ = "0.6.1"

BASE_URL = "https://volafile.io"
BASE_ROOM_URL = BASE_URL + "/r/"
BASE_REST_URL = BASE_URL + "/rest/"
BASE_WS_URL = "wss://volafile.io/api/"


def to_json(o):
    return json.dumps(o, separators=(',', ':'))


class Room:
    """ Use this to interact with a room as a user
    Example:
        r = Room("BEEPi", "ptc")
        r.post_chat("Hello, world!")
        r.upload_file("onii-chan.ogg")
        r.close()
    """

    def __init__(self, name=None, user=None):
        """name is the room name, if none then makes a new room
        user is your user name, if none then generates one for you"""

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Volafile-API/{}".
                                    format(__version__)})

        self.name = name
        if not self.name:
            name = self.session.get(BASE_URL + "/new").url
            self.name = re.search(r'r/(.+?)$', name).group(1)
        self.user = User(user or self._random_ID(5), self.session)
        checksum, checksum2 = self._get_checksums()
        self.ws_url = BASE_WS_URL
        self.ws_url += "?rn=" + self._random_ID(6)
        self.ws_url += "&EIO=3&transport=websocket"
        self.ws_url += "&t=" + str(int(time.time()*1000))
        self.ws = websocket.create_connection(self.ws_url)
        self._subscribe(checksum, checksum2)
        self.send_count = 1
        self.user_count = 0
        self.files = []
        self.chat_log = []
        self.max_ID = 0
        self.condition = Condition()

        self._listen_forever()

    @property
    def connected(self):
        return self.ws.connected

    def _listen_forever(self):
        """Listens for new data about the room from the websocket
        and updates Room state accordingly."""

        barrier = Barrier(2)

        def listen():
            barrier.wait()
            last_time = time.time()
            try:
                while self.connected:
                    new_data = self.ws.recv()
                    if not new_data:
                        pass
                    elif new_data[0] == '1':
                        self.close()
                        break
                    elif new_data[0] == '4':
                        json_data = json.loads(new_data[1:])
                        if type(json_data) is list and len(json_data) > 1:
                            self.max_ID = int(json_data[1][-1])
                            self._add_data(json_data)
                            with self.condition:
                                self.condition.notify_all()
                    else:
                        pass  # not implemented

                    # send max msg ID seen every 10 seconds
                    if time.time() > last_time + 10:
                        msg = "4" + to_json([self.max_ID])
                        self.ws.send(msg)
                        last_time = time.time()
            finally:
                try:
                    self.close()
                except:
                    pass
                # Notify that the listener is down now
                with self.condition:
                    self.condition.notify_all()

        def ping():
            while self.connected:
                self.ws.send('2')
                time.sleep(20)

        Thread(target=listen, daemon=True).start()
        Thread(target=ping, daemon=True).start()
        barrier.wait()

    def _add_data(self, data):
        for item in data[1:]:
            data_type = item[0][1][0]
            if data_type == "user_count":
                self.user_count = item[0][1][1]
            elif data_type == "files":
                files = item[0][1][1]['files']
                for f in files:
                    self.files.append(File(f[0], f[1], f[2], f[6]['user']))
            elif data_type == "chat":
                nick = item[0][1][1]['nick']
                msg_parts = item[0][1][1]['message']
                files = []
                rooms = []
                msg = ""
                for part in msg_parts:
                    if part['type'] == 'text':
                        msg += part['value']
                    elif part['type'] == 'file':
                        files.append(File(part['id'],
                                          part['name'],
                                          None,
                                          None))
                        msg += "@" + part['id']
                    elif part['type'] == 'room':
                        rooms.append(part['id'])
                        msg += "#" + part['id']
                    elif part['type'] == 'url':
                        msg += part['text']
                options = item[0][1][1]['options']
                admin = 'admin' in options.keys()
                user = 'user' in options.keys() or admin
                donator = 'donator' in options.keys()
                cm = ChatMessage(nick, msg, files, rooms, user, donator, admin)
                self.chat_log.append(cm)

    def listen(self, onmessage=None, onfile=None, onusercount=None):
        """Listen for incoming events.
        You need to at least provide one of the possible listener functions.
        You can detach a listener by returning False (exactly, not just a
        false-y value).
        The function will not return unless all listeners are detached again or
        the WebSocket connection is closed.
        """
        if not onmessage and not onfile and not onusercount:
            raise ValueError("At least one of onmessage, onfile, onusercount "
                             "must be specified")
        last_user, last_msg, last_file = 0, 0, 0
        with self.condition:
            while self.connected and (onmessage or onfile or onusercount):
                while (len(self.chat_log) == last_msg and
                       len(self.files) == last_file and
                       self.user_count == last_user and
                       self.connected):
                    self.condition.wait()

                if onusercount and self.user_count != last_user:
                    if onusercount(self.user_count) is False:
                        # detach
                        onusercount = None
                last_user = self.user_count

                while onfile and last_file < len(self.files):
                    if onfile(self.files[last_file]) is False:
                        # detach
                        onfile = None
                    last_file += 1
                last_file = len(self.files)

                while onmessage and last_msg < len(self.chat_log):
                    if onmessage(self.chat_log[last_msg]) is False:
                        # detach
                        onmessage = None
                    last_msg += 1
                last_msg = len(self.chat_log)

    def get_chat_log(self):
        """Returns list of ChatMessage objects for this room.
        Note: This will only reflect the messages at the time
        this method was called."""
        return self.chat_log[:]

    def get_user_count(self):
        """Returns number of users in this room"""
        return self.user_count

    def get_files(self):
        """Returns list of File objects for this room.
        Note: This will only reflect the files at the time
        this method was called."""
        return self.files[:]

    def _make_call(self, fn, args):
        o = {"fn": fn, "args": args}
        o = [self.max_ID, [[0, ["call", o]], self.send_count]]
        self.ws.send("4" + to_json(o))
        self.send_count += 1

    def post_chat(self, msg):
        """Posts a msg to this room's chat"""
        self._make_call("chat", [self.user.name, msg])

    def upload_file(self, filename, upload_as=None, blocksize=None, cb=None):
        """
        Uploads a file with given filename to this room.
        You may specify upload_as to change the name it is uploaded as.
        You can also specify a blocksize and a callback if you wish."""
        f = filename if hasattr(filename, "read") else open(filename, 'rb')
        filename = upload_as or os.path.split(filename)[1]

        files = Data({'file': {"name": filename, "value": f}},
                     blocksize=blocksize,
                     cb=cb)

        headers = {'Origin': 'https://volafile.io'}
        headers.update(files.headers)

        key, server = self._generate_upload_key()
        params = {'room': self.name,
                  'key': key,
                  'filename': filename
                  }

        return self.session.post("https://{}/upload".format(server),
                                 params=params,
                                 data=files,
                                 headers=headers
                                 )

    def close(self):
        """Close connection to this room"""
        self.ws.close()
        self.session.close()

    def _subscribe(self, checksum, checksum2):
        o = [-1, [[0, ["subscribe", {"room": self.name,
                                     "checksum": checksum,
                                     "checksum2": checksum2,
                                     "nick": self.user.name
                                     }]],
                  0]]
        self.ws.send("4" + to_json(o))

    def user_change_nick(self, new_nick):
        """Change the name of your user
        Note: Must be logged out to change nick"""
        if self.user.logged_in:
            raise RuntimeError("User must be logged out")

        self._make_call("command", [self.user.name, "nick", new_nick])
        self.user.name = new_nick

    def user_login(self, password):
        """Attempts to log in as the current user with given password"""
        if self.user.logged_in:
            raise RuntimeError("User already logged in!")

        params = {"name": self.user.name,
                  "password": password
                  }
        json_resp = json.loads(self.session.get(BASE_REST_URL + "login",
                                                params=params).text)
        if 'error' in json_resp.keys():
            raise ValueError("Login unsuccessful: {}".
                             format(json_resp["error"]))
        self._make_call("useSession", [json_resp["session"]])
        self.session.cookies.update({"session": json_resp["session"]})
        self.user.login()

    def get_user_stats(self, name):
        """Return data about the given user. Returns None if user
        does not exist."""

        r = self.session.get(BASE_URL + "/user/" + name)
        if r.status_code != 200 or not name:
            return None

        return json.loads(self.session.get(BASE_REST_URL + "getUserInfo",
                                           params={"name": name}).text)

    def user_logout(self):
        """Logs your user out"""
        if not self.user.logged_in:
            raise RuntimeError("User is not logged in")
        self._make_call("logout", [])

    def _random_ID(self, n):
        def r():
            return random.choice(string.ascii_letters + string.digits)
        return ''.join(r() for _ in range(n))

    def _generate_upload_key(self):
        info = json.loads(self.session.get(BASE_REST_URL + "getUploadKey",
                                           params={"name": self.user.name,
                                                   "room": self.name
                                                   }).text)
        return info['key'], info['server']

    def _get_checksums(self):
        text = self.session.get(BASE_ROOM_URL + self.name).text
        cs2 = re.search(r'checksum2\s*:\s*"(\w+?)"', text).group(1)
        text = self.session.get(
            "https://static.volafile.io/static/js/main.js?c=" + cs2).text
        cs1 = re.search(r'config\.checksum\s*=\s*"(\w+?)"', text).group(1)

        return cs1, cs2


class ChatMessage:
    """Basically a struct for a chat message. self.msg holds the
    text of the message, files is a list of Files that were
    linked in the message, and rooms are a list of room
    linked in the message. There are also flags for whether the
    user of the message was logged in, a donor, or an admin."""

    def __init__(self, nick, msg, files, rooms, logged_in, donor, admin):
        self.nick = nick
        self.msg = msg
        self.files = files
        self.rooms = rooms
        self.logged_in = logged_in
        self.donor = donor
        self.admin = admin

    def __repr__(self):
        return "<Msg({},{})>".format(self.nick, self.msg)


class File:
    """Basically a struct for a file's info on volafile, with an additional
    method to retrieve the file's URL."""

    def __init__(self, file_ID, name, file_type, uploader):
        self.file_ID = file_ID
        self.name = name
        self.file_type = file_type
        self.uploader = uploader

    def get_URL(self):
        return "{}/get/{}/{}".format(BASE_URL, self.file_ID, self.name)

    def __repr__(self):
        return "<File({},{},{})>".format(self.file_ID, self.uploader,
                                         self.name)


class User:
    """Used by Room. Currently not very useful by itself"""

    def __init__(self, name, session):
        self.name = name
        self.session = session
        self.logged_in = False

    def login(self):
        self.logged_in = True

    def logout(self):
        self.logged_in = False

    def __repr__(self):
        return "<User({}, {})>".format(self.name, self.logged_in)
