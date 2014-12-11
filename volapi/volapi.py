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
# pylint: disable=bad-continuation

import json
import os
import random
import re
import string
import time
from collections import deque

import requests
import websocket

from threading import Barrier, Condition, Thread

from .multipart import Data

__version__ = "0.8"

BASE_URL = "https://volafile.io"
BASE_ROOM_URL = BASE_URL + "/r/"
BASE_REST_URL = BASE_URL + "/rest/"
BASE_WS_URL = "wss://volafile.io/api/"


def random_id(length):
    """Generates a random ID of n length"""
    def char():
        """Generate single random char"""
        return random.choice(string.ascii_letters + string.digits)
    return ''.join(char() for _ in range(length))


def to_json(obj):
    """Create a compact JSON string from an object"""
    return json.dumps(obj, separators=(',', ':'))


def verify_username(username):
    """Raises an exception if the given username is not valid."""
    if len(username) > 12 or len(username) < 3:
        raise ValueError("Username must be between 3 and 12 characters.")
    if any(c not in string.ascii_letters + string.digits for c in username):
        raise ValueError("Usernames can only contain alphanumeric characters.")


class Connection(requests.Session):

    """Bundles a requests/websocket pair"""

    def __init__(self):
        super().__init__()

        agent = "Volafile-API/{}".format(__version__)

        self.headers.update({"User-Agent": agent})

        ws_url = ("{}?rn={}&EIO=3&transport=websocket&t={}".
                  format(BASE_WS_URL, random_id(6),
                         int(time.time() * 1000)))
        self.websock = websocket.create_connection(
            ws_url, header=["User-Agent: {}".format(agent)])

        self.max_id = 0
        self._send_count = 0

    @property
    def connected(self):
        """Is connected"""
        return self.websock.connected

    def recv_message(self, *args, **kw):
        """Receive a message"""
        return self.websock.recv(*args, **kw)

    def send_message(self, *args, **kw):
        """Send a message"""
        return self.websock.send(*args, **kw)

    def make_call(self, fun, args):
        """Makes a regular API call"""
        obj = {"fn": fun, "args": args}
        obj = [self.max_id, [[0, ["call", obj]], self._send_count]]
        self.send_message("4" + to_json(obj))
        self._send_count += 1

    def close(self):
        """Closes connection pair"""
        self.websock.close()
        super().close()


class RoomConnection(Connection):

    """Handles networking for a room."""

    def __init__(self):
        super().__init__()

        self.condition = Condition()

        self._file_queue = deque()
        self._message_queue = deque()

        self._ping_interval = 20  # default

    def subscribe(self, room_name, username):
        """Make subscribe API call"""
        checksum, checksum2 = self._get_checksums(room_name)
        obj = [-1, [[0, ["subscribe", {"room": room_name,
                                       "checksum": checksum,
                                       "checksum2": checksum2,
                                       "nick": username
                                       }]],
                    0]]
        self.send_message("4" + to_json(obj))

    def _get_checksums(self, room_name):
        """Gets the main checksums"""
        try:
            text = self.get(BASE_ROOM_URL + room_name).text
            cs2 = re.search(r'checksum2\s*:\s*"(\w+?)"', text).group(1)
            text = self.get(
                "https://static.volafile.io/static/js/main.js?c=" + cs2).text
            cs1 = re.search(r'config\.checksum\s*=\s*"(\w+?)"', text).group(1)

            return cs1, cs2
        except Exception as ex:
            raise IOError("Failed to get checksums") from ex

    def enqueue_file(self, file_id):
        """Enqueues a file id so listeners can see the file."""
        self._file_queue.appendleft(file_id)

    def enqueue_message(self, msg):
        """Enqueues a ChatMessage so listeners can see it."""
        self._message_queue.appendleft(msg)

    def listen(self, room, onmessage=None, onfile=None, onusercount=None):
        """Listen for incoming events for the given room.
        You need to at least provide one of the possible listener functions.
        You can detach a listener by returning False (exactly, not just a
        false-y value).
        The function will not return unless all listeners are detached again or
        the WebSocket connection is closed.
        """
        if not onmessage and not onfile and not onusercount:
            raise ValueError("At least one of onmessage, onfile, onusercount "
                             "must be specified")
        last_user = 0
        with self.condition:
            while self.connected and (onmessage or onfile or onusercount):
                while ((not self._message_queue or not onmessage) and
                       (not self._file_queue or not onfile) and
                       (room.user_count == last_user or not onusercount) and
                       self.connected):
                    self.condition.wait()

                if onusercount and room.user != last_user:
                    if onusercount(room.user_count) is False:
                        # detach
                        onusercount = None

                while onfile and self._file_queue:
                    if onfile(room.get_file(self._file_queue.pop())) is False:
                        # detach
                        onfile = None

                while onmessage and self._message_queue:
                    if onmessage(self._message_queue.pop()) is False:
                        # detach
                        onmessage = None

    def listen_forever(self, room):
        """Listens for new data about the room from the websocket
        and updates given room state accordingly."""

        barrier = Barrier(2)

        def listen():
            """Thread: Listen to incoming data"""
            barrier.wait()
            try:
                while self.connected:
                    new_data = self.recv_message()
                    if not new_data:
                        continue
                    if new_data[0] == '0':
                        json_data = json.loads(new_data[1:])
                        self._ping_interval = float(
                            json_data['pingInterval']) / 1000
                    if new_data[0] == '1':
                        self.close()
                        break
                    elif new_data[0] == '4':
                        json_data = json.loads(new_data[1:])
                        if isinstance(json_data, list) and len(json_data) > 1:
                            self.max_id = int(json_data[1][-1])
                            room.add_data(json_data)
                            with self.condition:
                                self.condition.notify_all()

            finally:
                try:
                    self.close()
                # pylint: disable=bare-except
                except:
                    pass
                # Notify that the listener is down now
                with self.condition:
                    self.condition.notify_all()

        def ping():
            """Thread: ping the server in intervals"""
            while self.connected:
                try:
                    self.send_message('2')
                    msg = "4" + to_json([self.max_id])
                    self.send_message(msg)
                # pylint: disable=bare-except
                except:
                    break
                time.sleep(self._ping_interval)

        Thread(target=listen, daemon=True).start()
        Thread(target=ping, daemon=True).start()
        barrier.wait()


class Room:

    """ Use this to interact with a room as a user
    Example:
        with Room("BEEPi", "ptc") as r:
            r.post_chat("Hello, world!")
            r.upload_file("onii-chan.ogg")
    """

    def __init__(self, name=None, user=None):
        """name is the room name, if none then makes a new room
        user is your user name, if none then generates one for you"""

        self.conn = RoomConnection()

        self.name = name
        if not self.name:
            name = self.conn.get(BASE_URL + "/new").url
            try:
                self.name = re.search(r'r/(.+?)$', name).group(1)
            except Exception as ex:
                raise IOError("Failed to create room") from ex

        self.user = User(user or random_id(5), self.conn)

        self.conn.subscribe(self.name, self.user.name)

        self._user_count = 0
        self._files = {}
        self._chat_log = []

        self.conn.listen_forever(self)

    def __repr__(self):
        return ("<Room({},{},connected={})>".
                format(self.name, self.user.name, self.connected))

    def __enter__(self):
        return self

    def __exit__(self, extype, value, traceback):
        self.close()

    @property
    def connected(self):
        """Room is connected"""
        return self.conn.connected

    def get_file(self, file_id):
        """Get the File object for the given file_id."""
        if file_id not in self._files:
            raise ValueError("No file with id {}".format(file_id))
        return self._files[file_id]

    def listen(self, onmessage=None, onfile=None, onusercount=None):
        """Listen for incoming events.
        You need to at least provide one of the possible listener functions.
        You can detach a listener by returning False (exactly, not just a
        false-y value).
        The function will not return unless all listeners are detached again or
        the WebSocket connection is closed.
        """
        self.conn.listen(self, onmessage, onfile, onusercount)

    def add_data(self, data):
        """Add data to given room's state"""
        for item in data[1:]:
            data_type = item[0][1][0]
            try:
                data = item[0][1][1]
            except ValueError:
                data = dict()
            if data_type == "user_count":
                self._user_count = data
            elif data_type == "files":
                files = data['files']
                for file in files:
                    self.conn.enqueue_file(file[0])
                    self._files[file[0]] = File(file[0],
                                                file[1],
                                                file[2],
                                                file[3],
                                                file[6]['user'])
            elif data_type == "delete_file":
                del self._files[item[0][1][1]]
            elif data_type == "chat":
                nick = data['nick']
                files = []
                rooms = []
                msg = ""
                for part in data["message"]:
                    if part['type'] == 'text':
                        msg += part['value']
                    elif part['type'] == 'file':
                        files += File(part['id'], part['name']),
                        msg += "@" + part['id']
                    elif part['type'] == 'room':
                        rooms += part["id"],
                        msg += "#" + part['id']
                    elif part['type'] == 'url':
                        msg += part['text']

                options = data['options']
                admin = 'admin' in options
                user = 'user' in options or admin
                donator = 'donator' in options

                chat_message = ChatMessage(nick, msg, files, rooms,
                                           logged_in=user,
                                           donator=donator,
                                           admin=admin)
                self.conn.enqueue_message(chat_message)
                self._chat_log.append(chat_message)

    @property
    def chat_log(self):
        """Returns list of ChatMessage objects for this room.
        Note: This will only reflect the messages at the time
        this method was called."""
        return self._chat_log[:]

    @property
    def user_count(self):
        """Returns number of users in this room"""
        return self._user_count

    @property
    def files(self):
        """Returns list of File objects for this room.
        Note: This will only reflect the files at the time
        this method was called."""
        return list(self._files.values())

    def get_user_stats(self, name):
        """Return data about the given user. Returns None if user
        does not exist."""

        req = self.conn.get(BASE_URL + "/user/" + name)
        if req.status_code != 200 or not name:
            return None

        return json.loads(self.conn.get(BASE_REST_URL + "getUserInfo",
                                        params={"name": name}).text)

    def post_chat(self, msg, me=False):
        """Posts a msg to this room's chat. Set me=True if you want to /me"""
        if not me:
            self.conn.make_call("chat", [self.user.name, msg])
        else:
            self.conn.make_call("command", [self.name, "me", msg])

    def upload_file(self, filename, upload_as=None, blocksize=None,
                    callback=None):
        """
        Uploads a file with given filename to this room.
        You may specify upload_as to change the name it is uploaded as.
        You can also specify a blocksize and a callback if you wish."""
        file = filename if hasattr(filename, "read") else open(filename, 'rb')
        filename = upload_as or os.path.split(filename)[1]

        files = Data({'file': {"name": filename, "value": file}},
                     blocksize=blocksize,
                     callback=callback)

        headers = {'Origin': 'https://volafile.io'}
        headers.update(files.headers)

        key, server = self._generate_upload_key()
        params = {'room': self.name,
                  'key': key,
                  'filename': filename}

        return self.conn.post("https://{}/upload".format(server),
                              params=params,
                              data=files,
                              headers=headers)

    def close(self):
        """Close connection to this room"""
        if self.connected:
            self.conn.close()

    def clear(self):
        """Clears the cached information, if any"""
        self._chat_log.clear()
        self._files.clear()

    def _generate_upload_key(self):
        """Generates a new upload key"""
        info = json.loads(self.conn.get(BASE_REST_URL + "getUploadKey",
                                        params={"name": self.user.name,
                                                "room": self.name}).text)
        return info['key'], info['server']


class ChatMessage:

    """Basically a struct for a chat message. self.msg holds the
    text of the message, files is a list of Files that were
    linked in the message, and rooms are a list of room
    linked in the message. There are also flags for whether the
    user of the message was logged in, a donor, or an admin."""
    # pylint: disable=too-few-public-methods

    def __init__(self, nick, msg, files, rooms, **kw):
        self.nick = nick
        self.msg = msg
        self.files = files
        self.rooms = rooms
        for key in ("logged_in", "donor", "admin"):
            setattr(self, key, kw.get(key, False))

    def __repr__(self):
        return "<Msg({},{})>".format(self.nick, self.msg)


class File:

    """Basically a struct for a file's info on volafile, with an additional
    method to retrieve the file's URL."""
    # pylint: disable=too-few-public-methods
    # pylint: disable=too-many-arguments

    def __init__(
            self,
            file_id,
            name,
            file_type=None,
            size=None,
            uploader=None):
        self.file_id = file_id
        self.name = name
        self.file_type = file_type
        self.size = size
        self.uploader = uploader

    @property
    def url(self):
        """Gets the download url of the file"""
        return "{}/get/{}/{}".format(BASE_URL, self.file_id, self.name)

    def __repr__(self):
        return ("<File({},{},{},{})>".
                format(self.file_id, self.size, self.uploader, self.name))


class User:

    """Used by Room. Currently not very useful by itself"""

    def __init__(self, name, conn):
        verify_username(name)
        self.name = name
        self.conn = conn
        self.logged_in = False

    def login(self, password):
        """Attempts to log in as the current user with given password"""
        if self.logged_in:
            raise RuntimeError("User already logged in!")

        params = {"name": self.name,
                  "password": password}
        json_resp = json.loads(self.conn.get(BASE_REST_URL + "login",
                                             params=params).text)
        if 'error' in json_resp:
            raise ValueError("Login unsuccessful: {}".
                             format(json_resp["error"]))
        self.conn.make_call("useSession", [json_resp["session"]])
        self.conn.cookies.update({"session": json_resp["session"]})
        self.logged_in = True

    def logout(self):
        """Logs your user out"""
        if not self.logged_in:
            raise RuntimeError("User is not logged in")
        self.conn.make_call("logout", [])
        self.logged_in = False

    def change_nick(self, new_nick):
        """Change the name of your user
        Note: Must be logged out to change nick"""
        if self.logged_in:
            raise RuntimeError("User must be logged out")
        verify_username(new_nick)

        self.conn.make_call("command", [self.name, "nick", new_nick])
        self.name = new_nick

    def register(self, password):
        """Registers the current user with the given password."""
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")

        params = {"name": self.name, "password": password}
        json_resp = json.loads(self.conn.get(BASE_REST_URL + "register",
                                             params=params).text)

        if 'error' in json_resp:
            raise ValueError("User '{}' is already registered".
                             format(self.name))

        self.conn.make_call("useSession", [json_resp["session"]])
        self.conn.cookies.update({"session": json_resp["session"]})
        self.logged_in = True

    def change_password(self, old_pass, new_pass):
        """Changes the password for the currently logged in user."""
        if len(new_pass) < 8:
            raise ValueError("Password must be at least 8 characters.")

        params = {"name": self.name,
                  "password": new_pass,
                  "old_password": old_pass
                  }
        json_resp = json.loads(self.conn.get(BASE_REST_URL + "changePassword",
                                             params=params).text)

        if 'error' in json_resp:
            raise ValueError("Wrong password.")

    def __repr__(self):
        return "<User({}, {})>".format(self.name, self.logged_in)
