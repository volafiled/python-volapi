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

import asyncio
import json
import os
import random
import re
import string
import time
import warnings

import requests

from collections import OrderedDict
from collections import defaultdict
from collections import namedtuple
from functools import wraps
from functools import partial
from threading import Barrier
from threading import Condition
from threading import RLock
from threading import Thread
from threading import Event
from threading import get_ident as get_thread_ident
from urllib.parse import urlsplit

from autobahn.asyncio.websocket import WebSocketClientFactory
from autobahn.asyncio.websocket import WebSocketClientProtocol

from .multipart import Data

__version__ = "0.14"

BASE_URL = "https://volafile.io"
BASE_ROOM_URL = BASE_URL + "/r/"
BASE_REST_URL = BASE_URL + "/rest/"
BASE_WS_URL = "wss://volafile.io/api/"
EVENT_TYPES = (
    "chat",
    "file",
    "user_count",
    "config",
    "user",
    "owner",
    "update_assets",
    "subscribed",
    "hooks",
    "time",
    "login",
    "chat_success")


def call_async(func):
    """Decorates a function to be called async on the loop thread"""

    @wraps(func)
    def wrapper(self, *args, **kw):
        """Wraps instance method to be called on loop thread"""
        def call():
            """Calls function on loop thread"""
            # pylint: disable=star-args
            func(self, *args, **kw)

        self.loop.call_soon_threadsafe(call)
    return wrapper


def call_sync(func):
    """Decorates a function to be called sync on the loop thread"""

    @wraps(func)
    def wrapper(self, *args, **kw):
        """Wraps instance method to be called on loop thread"""
        barrier = Barrier(2)
        result = None
        ex = None

        def call():
            """Calls function on loop thread"""
            # pylint: disable=star-args,broad-except
            nonlocal result, ex
            try:
                result = func(self, *args, **kw)
            except Exception as exc:
                ex = exc
            barrier.wait()

        self.loop.call_soon_threadsafe(call)
        barrier.wait()
        if ex:
            raise ex or Exception("Unknown error")
        return result
    return wrapper


class ListenerArbitrator:

    """Manages the asyncio loop and thread"""

    def __init__(self):
        self.loop = None
        self.condition = Condition()
        barrier = Barrier(2)
        self.thread = Thread(daemon=True, target=lambda: self._loop(barrier))
        self.thread.start()
        barrier.wait()

    def _loop(self, barrier):
        """Actual thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        barrier.wait()
        self.loop.run_forever()

    @call_sync
    def create_connection(self, room, ws_url, agent):
        """Creates a new connection"""
        factory = WebSocketClientFactory(ws_url)
        factory.useragent = agent
        factory.protocol = lambda: room
        ws_url = urlsplit(ws_url)
        conn = self.loop.create_connection(factory,
                                           host=ws_url.netloc,
                                           port=ws_url.port or 443,
                                           ssl=ws_url.scheme == "wss"
                                           )
        asyncio.async(conn, loop=self.loop)

    @call_async
    def send_message(self, conn, payload):
        # pylint: disable=no-self-use
        """Sends a message"""
        if not isinstance(payload, bytes):
            payload = payload.encode("utf-8")
        if conn.connected:
            conn.sendMessage(payload)

    @call_async
    def close(self, conn):
        # pylint: disable=no-self-use
        """Closes a connection"""
        conn.sendClose()


ARBITRATOR = ListenerArbitrator()


def parse_chat_message(data):
    """Parses the data for a json chat message and returns a
    ChatMessage object"""
    nick = data['nick']
    files = []
    rooms = []
    msg = ""
    for part in data["message"]:
        if part['type'] == 'text':
            msg += part['value']
        elif part['type'] == 'break':
            msg += "\n"
        elif part['type'] == 'file':
            files += File(part['id'], part['name']),
            msg += "@" + part['id']
        elif part['type'] == 'room':
            rooms += part["id"],
            msg += "#" + part['id']
        elif part['type'] == 'url':
            msg += part['text']
        else:
            warnings.warn(
                "unknown message type '{}'".format(
                    part['type']),
                Warning)

    options = data['options']
    admin = 'admin' in options
    user = 'user' in options or admin
    donator = 'donator' in options

    chat_message = ChatMessage(nick, msg, files, rooms,
                               logged_in=user,
                               donor=donator,
                               admin=admin)
    return chat_message


def random_id(length):
    """Generates a random ID of n length"""
    def char():
        """Generate single random char"""
        return random.choice(string.ascii_letters + string.digits)
    return ''.join(char() for _ in range(length))


def to_json(obj):
    """Create a compact JSON string from an object"""
    return json.dumps(obj, separators=(',', ':'))


class Listeners(namedtuple("Listeners", ("callbacks", "queue", "lock"))):

    """Collection of Listeners"""

    def __new__(cls):
        return super().__new__(cls, list(), list(), RLock())

    def process(self):
        """Process queue for these listeners"""
        with self.lock:
            for item in self.queue:
                callbacks = [c for c in self.callbacks
                             if c(item) is not False]
                self.callbacks.clear()
                self.callbacks.extend(callbacks)
            self.queue.clear()
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
        self.conn = conn
        self.connected = False
        self.max_id = 0
        self.send_count = 1

    def onConnect(self, response):
        self.connected = True

    def onOpen(self):
        while True:
            yield from asyncio.sleep(self.conn.ping_interval)
            self.conn.send_message("2")
            self.conn.send_message("4" + to_json([self.max_id]))

    def onMessage(self, new_data, binarybinary):
        # pylint: disable=unused-argument
        if not new_data:
            return

        if isinstance(new_data, bytes):
            new_data = new_data.decode("utf-8")
        self.conn.on_message(new_data)

    def onClose(self, clean, code, reason):
        # pylint: disable=unused-argument
        self.connected = False
        with ARBITRATOR.condition:
            ARBITRATOR.condition.notify_all()


class Connection(requests.Session):

    """Bundles a requests/websocket pair"""

    def __init__(self, room):
        super().__init__()

        self.room = room

        agent = "Volafile-API/{}".format(__version__)

        self.headers.update({"User-Agent": agent})

        self.lock = RLock()
        self.listeners = defaultdict(lambda: defaultdict(Listeners))
        self.must_process = False

        self._ping_interval = 20  # default

        ws_url = ("{}?rn={}&EIO=3&transport=websocket&t={}".
                  format(BASE_WS_URL, random_id(6),
                         int(time.time() * 1000)))
        self.proto = Protocol(self)
        ARBITRATOR.create_connection(self.proto, ws_url, agent)

    @property
    def ping_interval(self):
        """Gets the ping interval"""
        return self._ping_interval

    @property
    def connected(self):
        """Connection state"""
        return self.proto.connected

    def send_message(self, payload):
        """Send a message"""
        ARBITRATOR.send_message(self.proto, payload)

    def make_call(self, fun, args):
        """Makes a regular API call"""
        obj = {"fn": fun, "args": args}
        obj = [self.proto.max_id, [[0, ["call", obj]], self.proto.send_count]]
        self.send_message("4" + to_json(obj))
        self.proto.send_count += 1

    def close(self):
        """Closes connection pair"""
        ARBITRATOR.close(self.proto)
        super().close()

    def subscribe(self, room_name, username, secret_key):
        """Make subscribe API call"""
        checksum, checksum2 = self._get_checksums(room_name)
        subscribe_options = {"room": room_name,
                             "checksum": checksum,
                             "checksum2": checksum2,
                             "nick": username
                             }
        if secret_key:
            subscribe_options['secretToken'] = secret_key
        obj = [-1, [[0, ["subscribe", subscribe_options]],
                    0]]
        self.send_message("4" + to_json(obj))

    def on_message(self, new_data):
        """Processes incoming messages"""
        if new_data[0] == '0':
            json_data = json.loads(new_data[1:])
            self._ping_interval = float(
                json_data['pingInterval']) / 1000
            return

        if new_data[0] == '1':
            self.close()
            return

        if new_data[0] == '4':
            json_data = json.loads(new_data[1:])
            if isinstance(json_data, list) and len(json_data) > 1:
                self.proto.max_id = int(json_data[1][-1])
                self.room.add_data(json_data)
                with ARBITRATOR.condition:
                    ARBITRATOR.condition.notify_all()
            return

    def _get_checksums(self, room_name):
        """Gets the main checksums"""
        try:
            text = self.get(BASE_ROOM_URL + room_name).text
            cs2 = re.search(r'checksum2\s*:\s*"(\w+?)"', text).group(1)
            text = self.get(
                "https://static.volafile.io/static/js/main.js?c=" + cs2).text
            cs1 = re.search(r'config\.checksum\s*=\s*"(\w+?)"', text).group(1)

            return cs1, cs2
        except Exception:
            raise IOError("Failed to get checksums")

    def add_listener(self, event_type, callback):
        """Add a listener for specific event type.
        You'll need to actually listen for changes using the listen method"""
        if event_type not in EVENT_TYPES:
            raise ValueError("Invalid event type: {}".format(event_type))
        thread = get_thread_ident()
        with self.lock:
            self.listeners[event_type][thread].add(callback)
            if event_type == "file":
                for file in self.room.files:
                    self.enqueue_data(event_type, file)
        self.process_queues()

    def enqueue_data(self, event_type, data):
        """Enqueue a data item for specific event type"""
        with self.lock:
            for listener in self.listeners[event_type].values():
                listener.enqueue(data)
                self.must_process = True

    def process_queues(self):
        """Process queues if any have data queued"""
        with self.lock:
            if not self.must_process:
                return
            with ARBITRATOR.condition:
                ARBITRATOR.condition.notify_all()
            self.must_process = False

    @property
    def _listeners_for_thread(self):
        """All Listeners for the current thread"""
        thread = get_thread_ident()
        with self.lock:
            return [l for m in self.listeners.values()
                    for (tid, l) in m.items() if tid == thread]

    def validate_listeners(self):
        """Validates that some listeners are actually registered"""
        listeners = self._listeners_for_thread
        if not sum(len(l) for l in listeners):
            raise ValueError("No active listeners")

    def listen(self):
        """Listen for changes in all registered listeners."""
        self.validate_listeners()
        with ARBITRATOR.condition:
            while self.connected:
                ARBITRATOR.condition.wait()
                if not self.run_queues():
                    break

    def run_queues(self):
        """Run all queues that have data queued"""
        with self.lock:
            listeners = self._listeners_for_thread
        return sum(l.process() for l in listeners) > 0


class Room:

    """ Use this to interact with a room as a user
    Example:
        with Room("BEEPi", "ptc") as r:
            r.post_chat("Hello, world!")
            r.upload_file("onii-chan.ogg")
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, name=None, user=None, subscribe=True):
        """name is the room name, if none then makes a new room
        user is your user name, if none then generates one for you"""

        self.conn = Connection(self)

        room_resp = None
        self.name = name
        if not self.name:
            room_resp = self.conn.get(BASE_URL + "/new")
            url = room_resp.url
            try:
                self.name = re.search(r'r/(.+?)$', url).group(1)
            except Exception:
                raise IOError("Failed to create room")

        self._config = {}
        try:
            if not room_resp:
                room_resp = self.conn.get(BASE_ROOM_URL + self.name)
            text = room_resp.text
            text = text.replace('\n', '')
            text = re.sub(
                r'(\w+):(?=([^"\\]*(\\.|"([^"\\]*\\.)*[^"\\]*"))*[^"]*$)',
                r'"\1":',
                text)
            text = text.replace('true', '"true"').replace('false', '"false"')
            text = re.search(r'config=({.+});', text).group(1)
            config = json.loads(text)

            self._config['title'] = config['name']
            self._config['private'] = config['private'] == 'true'
            self._config['motd'] = config['motd']
            secret_key = config.get('secretToken')

            self._config['max_title'] = config['max_room_name_length']
            self._config['max_message'] = config['max_message_length']
            max_nick = config['max_alias_length']
            self._config['max_file'] = config['file_max_size']
            self._config['ttl'] = config.get('file_ttl')
            if self._config['ttl'] is None:
                self._config['ttl'] = config['file_time_to_live']
            else:
                # convert hours to seconds
                self._config['ttl'] *= 3600
            self._config['session_lifetime'] = config['session_lifetime']

        except Exception:
            raise IOError("Failed to get room config for {}".format(self.name))

        if not subscribe and not user:
            user = random_id(6)
        self.user = User(user, self.conn, max_nick)
        self.owner = bool(secret_key)

        self._user_count = 0
        self._files = OrderedDict()
        self._chat_log = []

        if subscribe:
            self.conn.subscribe(self.name, self.user.name, secret_key)

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

    def add_listener(self, event_type, callback):
        """Add a listener for specific event type.
        You'll need to actually listen for changes using the listen method"""
        return self.conn.add_listener(event_type, callback)

    def listen(self, onmessage=None, onfile=None, onusercount=None):
        """Listen for changes in all registered listeners.
        Please note that the on* arguments are present solely for legacy
        purposes. New code should use add_listener."""
        if onmessage:
            self.add_listener("chat", onmessage)
        if onfile:
            self.add_listener("file", onfile)
        if onusercount:
            self.add_listener("user_count", onusercount)
        return self.conn.listen()

    def add_data(self, data):
        """Add data to given room's state"""
        # pylint: disable=too-many-branches
        # pylint: disable=too-many-statements
        for item in data[1:]:
            try:
                data_type = item[0][1][0]
            except IndexError:
                data_type = None
            try:
                data = item[0][1][1]
            except ValueError:
                data = dict()
            if data_type == "user_count":
                self._user_count = data
                self.conn.enqueue_data("user_count", self._user_count)
            elif data_type == "files":
                files = data['files']
                for file in files:
                    file = File(file[0],  # id
                                file[1],  # name
                                file[2],  # type
                                file[3],  # size
                                file[4] / 1000,  # expire time
                                file[6]['user'])
                    self._files[file.id] = file
                    self.conn.enqueue_data("file", file)
                    file.download_info = partial(
                        file.download_info,
                        conn=self.conn)
                    file.event = Event()
            elif data_type == "delete_file":
                del self._files[data]
            elif data_type == "chat":
                chat_message = parse_chat_message(data)
                self._chat_log.append(chat_message)
                self.conn.enqueue_data("chat", chat_message)
            elif data_type == "changed_config":
                change = data
                if change['key'] == 'name':
                    self._config['title'] = change['value']
                elif change['key'] == 'file_ttl':
                    self._config['ttl'] = change['value'] * 3600
                elif change['key'] == 'private':
                    self._config['private'] = change['value']
                elif change['key'] == 'motd':
                    self._config['motd'] = change.get('value') or ""
                else:
                    warnings.warn(
                        "unknown config key '{}'".format(
                            change['key']),
                        Warning)
                self.conn.enqueue_data("config", self)
            elif data_type == "chat_name":
                self.user.name = data
                self.conn.enqueue_data("user", self.user)
            elif data_type == "owner":
                self.owner = data['owner']
                self.conn.enqueue_data("owner", self.owner)
            elif data_type == "fileinfo":
                file = self._files[data['id']]
                file.info = data.get(file.type)
                file.event.set()
                del file.event
            elif data_type == "time":
                self.conn.enqueue_data("time", data / 1000)
            elif data_type == "submitChat":
                self.conn.enqueue_data("chat_success", data)
            elif data_type in ("update_assets", "subscribed",
                               "hooks", "time", "login"):
                self.conn.enqueue_data(data_type, data)
            else:
                warnings.warn(
                    "unknown data type '{}' with data '{}'".format(
                        data_type,
                        data),
                    Warning)
        self.conn.process_queues()

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
        for fid in self._files.keys():
            if self._files[fid].expired:
                del self._files[fid]
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
        # pylint: disable=invalid-name
        if len(msg) > self._config['max_message']:
            raise ValueError(
                "Chat message must be at most {} characters".format(
                    self._config['max_message']))

        while not self.user.name:
            with ARBITRATOR.condition:
                ARBITRATOR.condition.wait()
        if not me:
            self.conn.make_call("chat", [self.user.name, msg])
        else:
            self.conn.make_call("command", [self.user.name, "me", msg])

    def upload_file(self, filename, upload_as=None, blocksize=None,
                    callback=None):
        """
        Uploads a file with given filename to this room.
        You may specify upload_as to change the name it is uploaded as.
        You can also specify a blocksize and a callback if you wish.
        Returns the file's id on success and None on failure."""
        file = filename if hasattr(filename, "read") else open(filename, 'rb')
        filename = upload_as or os.path.split(filename)[1]
        try:
            file.seek(0, 2)
            if file.tell() > self._config['max_file']:
                raise ValueError(
                    "File must be at most {} GB".format(
                        self._config['max_file'] >> 30))
        finally:
            try:
                file.seek(0)
            # pylint: disable=bare-except
            except:
                pass

        files = Data({'file': {"name": filename, "value": file}},
                     blocksize=blocksize,
                     callback=callback)

        headers = {'Origin': 'https://volafile.io'}
        headers.update(files.headers)

        key, server, file_id = self._generate_upload_key()
        params = {'room': self.name,
                  'key': key,
                  'filename': filename}

        post = self.conn.post("https://{}/upload".format(server),
                              params=params,
                              data=files,
                              headers=headers)
        if post.status_code == 200:
            return file_id
        else:
            return None

    def close(self):
        """Close connection to this room"""
        if self.connected:
            self.conn.close()

    def report(self):
        """Reports this room to moderators"""
        self.conn.make_call("submitReport", [{}])

    @property
    def title(self):
        """Gets the title name of the room (e.g. /g/entoomen)"""
        return self._config['title']

    def set_title(self, new_name):
        """Sets the room name (e.g. /g/entoomen)"""
        if not self.owner:
            raise RuntimeError("You must own this room to do that")
        if len(new_name) > self._config['max_title'] or len(new_name) < 1:
            raise ValueError(
                "Room name length must be between 1 and {} characters.".format(
                    self._config['max_title']))
        self.conn.make_call("editInfo", [{"name": new_name}])
        self._config['title'] = new_name

    @property
    def private(self):
        """True if the room is private, False otherwise"""
        return self._config['private']

    def set_private(self, value):
        """Sets the room to private if given True, else sets to public"""
        if not self.owner:
            raise RuntimeError("You must own this room to do that")
        self.conn.make_call("editInfo", [{"private": value}])
        self._config['private'] = value

    @property
    def motd(self):
        """Returns the message of the day for this room"""
        return self._config['motd']

    def set_motd(self, motd):
        """Sets the room's MOTD"""
        if not self.owner:
            raise RuntimeError("You must own this room to do that")
        if len(motd) > 1000:
            raise ValueError("Room's MOTD must be at most 1000 characters")
        self.conn.make_call("editInfo", [{"motd": motd}])
        self._config['motd'] = motd

    def clear(self):
        """Clears the cached information, if any"""
        self._chat_log.clear()
        self._files.clear()

    def _generate_upload_key(self):
        """Generates a new upload key"""
        # Wait for server to set username if not set already.
        while not self.user.name:
            with ARBITRATOR.condition:
                ARBITRATOR.condition.wait()
        info = json.loads(self.conn.get(BASE_REST_URL + "getUploadKey",
                                        params={"name": self.user.name,
                                                "room": self.name}).text)
        return info['key'], info['server'], info['file_id']


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
    # pylint: disable=invalid-name
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-instance-attributes

    def __init__(
            self,
            file_id,
            name,
            file_type=None,
            size=None,
            expire_time=None,
            uploader=None,
    ):
        self.id = file_id
        self.name = name
        self.type = file_type
        self.size = size
        self.expire_time = expire_time
        self.uploader = uploader
        self._info = None
        self.event = None

    @property
    def url(self):
        """Gets the download url of the file"""
        return "{}/get/{}/{}".format(BASE_URL, self.id, self.name)

    @property
    def expired(self):
        """Returns true if the file has expired, false otherwise"""
        return time.time() >= self.expire_time

    @property
    def time_left(self):
        """Returns how many seconds before this file expires"""
        return self.expire_time - time.time()

    @property
    def thumbnail(self):
        """Returns the thumbnail url for this image, audio, or video file."""
        if self.type not in ("video", "image", "audio"):
            raise RuntimeError("Only videos, audio and images have thumbnails")
        vid = "video_" if self.type == "video" else ""
        return "{}/asset/{}/{}thumb".format(BASE_URL, self.id, vid)

    @property
    def resolution(self):
        """Gets the resolution of this image or video file in format (W, H)"""
        if self.type not in ("video", "image"):
            raise RuntimeError("Only videos and images have resolutions")
        return (self.info['width'], self.info['height'])

    @property
    def duration(self):
        """Returns the duration in seconds of this audio or video file"""
        if self.type not in ("video", "audio"):
            raise RuntimeError("Only videos and audio have durations")
        return self.info.get('length') or self.info.get('duration')

    def __repr__(self):
        return ("<File({},{},{},{})>".
                format(self.id, self.size, self.uploader, self.name))

    @property
    def info(self):
        """Returns info about the file"""
        if not self._info:
            self.download_info()
            self.event.wait()
        return self._info

    @info.setter
    def info(self, val):
        """Sets the value of info"""
        self._info = val

    def download_info(self, conn):
        """Asks the server for the file info"""
        conn.make_call("get_fileinfo", [self.id])


class User:

    """Used by Room. Currently not very useful by itself"""

    def __init__(self, name, conn, max_len):
        self._max_length = max_len
        if name is None:
            self.name = ""
        else:
            self._verify_username(name)
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
        self._verify_username(new_nick)

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

    def _verify_username(self, username):
        """Raises an exception if the given username is not valid."""
        if len(username) > self._max_length or len(username) < 3:
            raise ValueError(
                "Username must be between 3 and {} characters.".format(
                    self._max_length))
        if any(
                c not in string.ascii_letters +
                string.digits for c in username):
            raise ValueError(
                "Usernames can only contain alphanumeric characters.")

    def __repr__(self):
        return "<User({}, {})>".format(self.name, self.logged_in)


def listen_many(*rooms):
    """Listen for changes in all registered listeners in all specified rooms"""
    rooms = set(r.conn for r in rooms)
    for room in rooms:
        room.validate_listeners()
    with ARBITRATOR.condition:
        while any(r.connected for r in rooms):
            ARBITRATOR.condition.wait()
            rooms = [r for r in rooms if r.run_queues()]
            if not rooms:
                return
