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
# pylint: disable=bad-continuation,too-many-lines,broad-except,missing-docstring,locally-disabled

import asyncio
import json
import logging
import os
import re
import string
import time
import warnings

from collections import OrderedDict
from collections import defaultdict
from contextlib import suppress
from enum import Enum
from threading import RLock
from threading import Event
from threading import get_ident as get_thread_ident

import requests

from .auxo import ARBITRATOR, Listeners, Protocol, Barrier
from .multipart import Data
from .utils import delayed_close, html_to_text, random_id, to_json

LOGGER = logging.getLogger(__name__)

__version__ = "5.6.0"

MAX_UNACKED = 10
BASE_URL = "https://volafile.org"
MAIN_JS = "https://static.volafile.org/static/js/main.js?c="
BASE_ROOM_URL = BASE_URL + "/r/"
BASE_REST_URL = BASE_URL + "/rest/"
BASE_WS_URL = "wss://volafile.org/api/"


class Connection(requests.Session):
    """Bundles a requests/websocket pair"""

    def __init__(self, room):
        try:
            asyncio.get_event_loop()
        except Exception:
            asyncio.set_event_loop(asyncio.new_event_loop())

        super().__init__()

        self.room = room
        self.exception = None

        self.lastping = self.lastpong = 0

        agent = "Volafile-API/{}".format(__version__)

        self.headers.update({"User-Agent": agent})

        self.lock = RLock()
        self.conn_barrier = Barrier(2)
        self.listeners = defaultdict(lambda: defaultdict(Listeners))
        self.must_process = False
        self._queues_enabled = True

        self._ping_interval = 20  # default

        self.proto = Protocol(self)
        self.last_ack = self.proto.max_id

    def connect(self, username, checksum, token="", password=None, key=None):
        token = token or ""
        ws_url = "{url}?room={room}&cs={cs}&nick={user}&token={token}&rn={rnd}&EIO=3&transport=websocket&t={t}".format(
            cs=checksum,
            rnd=random_id(6),
            room=self.room.room_id,
            t=int(time.time() * 1000),
            token=token,
            url=BASE_WS_URL,
            user=username)
        if password:
            ws_url += "&password={password}".format(password=password)
        elif key:
            ws_url += "&key={key}".format(key=key)

        ARBITRATOR.create_connection(
                self.proto,
                ws_url,
                self.headers["User-Agent"],
                self.cookies
                )
        self.conn_barrier.wait()

    @property
    def ping_interval(self):
        """Gets the ping interval"""

        return self._ping_interval

    @property
    def connected(self):
        """Connection state"""

        return bool(hasattr(self, "proto") and self.proto.connected)

    def send_message(self, payload):
        """Send a message"""

        ARBITRATOR.send_message(self.proto, payload)

    def send_ack(self):
        """Send an ack message"""
        if self.last_ack == self.proto.max_id:
            return
        LOGGER.debug("ack (%d)", self.proto.max_id)
        self.last_ack = self.proto.max_id
        self.send_message("4" + to_json([self.proto.max_id]))

    def make_call(self, fun, args):
        """Makes a regular API call"""

        obj = {"fn": fun, "args": args}
        obj = [self.proto.max_id, [[0, ["call", obj]], self.proto.send_count]]
        self.send_message("4" + to_json(obj))
        self.proto.send_count += 1

    def make_api_call(self, call, *args, **kw):
        """Make a REST API call"""

        headers = kw.get("headers") or {}
        headers.update({
            "Origin": BASE_URL,
            "Referer": "{}/r/{}".format(BASE_URL, self.room.name)
            })
        kw["headers"] = headers
        return self.get(BASE_REST_URL + call, *args, **kw).json()

    def reraise(self, ex):
        """Reraise an exception passed by the event thread"""
        self.exception = ex
        self.process_queues(forced=True)

    def close(self):
        """Closes connection pair"""

        self.listeners.clear()
        self.proto.connected = False
        ARBITRATOR.close(self.proto)
        super().close()
        del self.room
        del self.proto

    def ensure_barrier(self):
        if self.conn_barrier:
            self.conn_barrier.wait()
            self.conn_barrier = None

    async def on_open(self):
        """DingDongmaster the connection is open"""
        self.ensure_barrier()
        while self.connected:
            try:
                if self.lastping > self.lastpong:
                    raise IOError("Last ping remained unanswered")

                self.send_message("2")
                self.send_ack()
                self.lastping = time.time()
                await asyncio.sleep(self.ping_interval)
            except Exception as ex:
                LOGGER.exception("Failed to ping")
                try:
                    try:
                        raise IOError("Ping failed") from ex
                    except Exception as ioex:
                        self.reraise(ioex)
                except Exception:
                    LOGGER.exception("failed to force close connection after ping error")
                break

    async def on_close(self):
        """DingDongmaster the connection is gone"""
        self.ensure_barrier()
        return None

    def on_frame(self, data):
        if not hasattr(self, "room"):
            LOGGER.debug("received out of bounds message [%r]", data)
            return
        LOGGER.debug("received message %r", data)
        if isinstance(data, list) and len(data) > 1:
            _our_ack, data = data[0], data[1:]
            last_ack = int(data[-1][-1])
            need_ack = last_ack > self.proto.max_id + MAX_UNACKED
            self.proto.max_id = last_ack
            if need_ack:
                LOGGER.debug("needing to ack (%d/%d)", last_ack, self.proto.max_id)
                self.send_ack()
            self.room.add_data(data)
        elif "session" in data:
            self.proto.session = data
        elif data == [1]:
            # ignore
            pass
        elif data == [0]:
            #raise IOError("Force disconnect?")
            pass
        elif isinstance(data, list):
            _our_ack = data[0]
            # not really handled further
        else:
            LOGGER.warning("unhandled message frame type %r", data)

    def on_message(self, new_data):
        """Processes incoming messages according to engine-io rules"""
        # https://github.com/socketio/engine.io-protocol

        LOGGER.debug("new frame [%r]", new_data)
        try:
            what = int(new_data[0])
            data = new_data[1:]
            data = data and json.loads(data)
            if what == 0:
                self._ping_interval = float(data['pingInterval']) / 1000
                LOGGER.debug("adjusted ping interval")
                return

            if what == 1:
                LOGGER.debug("received close")
                self.reraise(IOError("Connection closed remotely"))
                return

            if what == 3:
                self.lastpong = time.time()
                LOGGER.debug("received a pong")
                return

            if what == 4:
                self.on_frame(data)
                return

            if what == 6:
                LOGGER.debug("received noop")
                self.send_message("5")
                return

            LOGGER.debug("unhandled message: [%d] [%r]", what, data)
        except Exception as ex:
            self.reraise(ex)

    def _get_checksums(self):
        """Gets the main checksums"""

        try:
            return self.room.cs2, self.room.cs2
        except Exception:
            raise IOError("Failed to get checksums")

    def add_listener(self, event_type, callback):
        """Add a listener for specific event type.
        You'll need to actually listen for changes using the listen method"""

        if not self.connected:
            raise ValueError("Room is not connected")
        thread = get_thread_ident()
        with self.lock:
            listener = self.listeners[event_type][thread]
        listener.add(callback)
        if event_type == "file":
            for file in self.room.files:
                self.enqueue_data(event_type, file)
        self.process_queues()

    def enqueue_data(self, event_type, data):
        """Enqueue a data item for specific event type"""

        with self.lock:
            listeners = list(self.listeners[event_type].values())
            for listener in listeners:
                listener.enqueue(data)
                self.must_process = True

    @property
    def queues_enabled(self):
        """Whether queue processing is enabled"""

        return self._queues_enabled

    @queues_enabled.setter
    def queues_enabled(self, value):
        """Sets whether queue processing is enabled"""

        with self.lock:
            self._queues_enabled = value

    def process_queues(self, forced=False):
        """Process queues if any have data queued"""

        with self.lock:
            if (not forced and not self.must_process) or not self._queues_enabled:
                return
            self.must_process = False
        ARBITRATOR.awaken()

    @property
    def _listeners_for_thread(self):
        """All Listeners for the current thread"""

        thread = get_thread_ident()
        with self.lock:
            return [l for m in self.listeners.values()
                    for (tid, l) in m.items() if tid == thread]

    def validate_listeners(self):
        """Validates that some listeners are actually registered"""

        if self.exception:
            # pylint: disable=raising-bad-type
            raise self.exception

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

        if self.exception:
            # pylint: disable=raising-bad-type
            raise self.exception
        listeners = self._listeners_for_thread
        return sum(l.process() for l in listeners) > 0


class Room:
    """ Use this to interact with a room as a user
    Example:
        with Room("BEEPi", "SameFag") as r:
            r.post_chat("Hello, world!")
            r.upload_file("onii-chan.ogg")
    """
    # pylint: disable=unused-argument

    def __init__(self, name=None, user=None, key=None, password=None, subscribe=True, other=None):
        """name is the room name, if none then makes a new room
        user is your user name, if none then generates one for you"""

        self.name = name
        self.admin = False
        self.user_info = dict()
        self._config = dict()
        self._user_count = 0
        self._files = OrderedDict()
        self._filereqs = {}
        self._upload_count = 0
        self.key = key or ""
        self.password = password or ""

        self.conn = Connection(self)
        if other:
            self.conn.cookies.update(other.conn.cookies)
        try:
            self.room_id, secret_key = self._get_config()

            if not subscribe and not user:
                if other and other.user and other.user.name:
                    user = other.user.name
                else:
                    user = random_id(6)
            self.user = User(user, self.conn, self._config["max_nick"])
            self.conn.connect(
                    username=user,
                    checksum=self.cs2,
                    token=secret_key,
                    password=self.password,
                    key=self.key)
            self.owner = bool(secret_key)

            if subscribe and other and other.user and other.user.logged_in:
                self.user.login_transplant(other.user)

            # check for first exception ever
            if self.conn.exception:
                # pylint: disable=raising-bad-type
                raise self.conn.exception
        except Exception:
            self.close()
            raise

    def _get_config(self):
        """ Really connect """
        if not self.name:
            room_resp = self.conn.get(BASE_URL + "/new")
            room_resp.raise_for_status()
            url = room_resp.url
            try:
                self.name = re.search(r'r/(.+?)$', url).group(1)
            except Exception:
                raise IOError("Failed to create room")

        try:
            params = {"room": self.name}
            if self.key:
                params["key"] = self.key
            elif self.password:
                params["password"] = self.password
            config = self.conn.make_api_call("getRoomConfig", params=params)
            self.cs2 = config["checksum2"]
            self._process_config(config)
            return (
                    config.get("room_id", config.get("custom_room_id", self.name)),
                    config.get("secretToken")
                    )

        except Exception:
            raise IOError("Failed to get room config for {}".format(self.name))

    def _process_config(self, config):
        defs = dict(private=True, disabled=False, owner="")
        for k, v in defs.items():
            if k not in self._config:
                self._config[k] = v
        mapped = dict(
            private="private",
            disabled="disabled",
            owner="owner",
            title="name",
            motd="motd",
            max_title="max_room_name_length",
            max_message="chat_max_message_length",
            max_nick="chat_max_alias_length",
            max_file="file_max_size",
            session_lifetime="session_lifetime",
            ttl="file_time_to_live",
            creation_time="created_time"
        )
        for k, v in mapped.items():
            if v not in config:
                continue
            self._config[k] = config[v]

    def __repr__(self):
        return ("<Room({}, {}, connected={})>".
                format(self.name, self.user.name, self.connected))

    def __enter__(self):
        return self

    def __exit__(self, _extype, _value, _traceback):
        self.close()

    def __del__(self):
        self.close()

    @property
    def connected(self):
        """Room is connected"""

        return bool(hasattr(self, "conn") and self.conn.connected)

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

    def _handle_401(self, data, _):
        """Handle Lain being helpful"""
        ex = IOError("non-cryptographic authenticator phrase (NSAable)", data)
        self.conn.reraise(ex)

    def _handle_429(self, data, _):
        """Handle Lain being helpful"""
        ex = IOError("Too fast", data)
        self.conn.reraise(ex)

    def _handle_userCount(self, data, _):
        """Handle user count changes"""
        self._user_count = data
        self.conn.enqueue_data("user_count", self._user_count)

    def _handle_userInfo(self, data, _):
        """Handle user information"""
        for k, v in data.items():
            if k == "owner":
                self.owner = bool(v)
                self.conn.enqueue_data("owner", self.owner)
            if k == "admin":
                self.admin = bool(v)
                self.conn.enqueue_data("admin", self.admin)
            self.user_info[k] = v

    def _handle_key(self, data, _):
        """Handle keys"""

        self.key = data
        self.conn.enqueue_data("key", self.key)

    def _handle_config(self, data, _):
        """Handle initial config push"""

        self._process_config(data)
        self.conn.enqueue_data("config", data)

    def _handle_files(self, data, _):
        """Handle new files being uploaded"""

        initial = data.get("set", False)
        files = data['files']
        for file in files:
            try:
                file = File(self, file[0], file[1],
                        type=file[2],
                        size=file[3],
                        expire_time=int(file[4]) / 1000,
                        uploader=file[6].get("nick") or file[6].get("user"),
                        data=file[6])
                self._files[file.id] = file
                self.conn.enqueue_data("file", file)
            except Exception:
                import pprint
                LOGGER.exception("bad")
                pprint.pprint(file)
        if initial:
            self.conn.enqueue_data("received_files", True)

    def _handle_delete_file(self, data, _):
        """Handle files being removed"""

        file = self._files.get(data)
        if file:
            with suppress(KeyError):
                del self._files[data]
            self.conn.enqueue_data("delete_file", file)

    def _handle_chat(self, data, _):
        """Handle chat messages"""
        self.conn.enqueue_data("chat", ChatMessage.from_data(self, data))

    def _handle_changed_config(self, change, _):
        """Handle configuration changes"""

        try:
            key, value = change.get("key"), change.get("value")
            try:
                if key == 'name':
                    self._config["title"] = value or ""
                    return
                if key == 'file_ttl':
                    self._config["ttl"] = (value or 48) * 3600
                    return
                if key == 'private':
                    # Yeah, I have seen both, a simple bool and a string m(
                    self._config["private"] = (value and value != "false") or False
                    return
                if key == "disabled":
                    self._config["disabled"] = (value and value != "false") or False
                    return
                if key == 'motd':
                    self._config["motd"] = value or ""
                    return

                warnings.warn("unknown config key '{}': {} ({})".
                        format(key, value, type(value)),
                        Warning)
            except Exception:
                warnings.warn("Failed to handle config key'{}': {} ({})\nThis might be a bug!".
                        format(key, value, type(value)),
                        Warning)

        finally:
            self.conn.enqueue_data("config", self)

    def _handle_chat_name(self, data, _):
        """Handle user name changes"""

        self.user.name = data
        self.conn.enqueue_data("user", self.user)

    def _handle_fileinfo(self, data, _):
        """Handle file information responses"""

        file = self._files.get(data["id"])
        if not file:
            file = self._filereqs.get(data["id"])
            if file:
                with suppress(KeyError):
                    del self._filereqs[data["id"]]
        if file:
            file.add_info(data)

    def _handle_time(self, data, _):
        """Handle time changes"""

        self.conn.enqueue_data("time", data / 1000)

    def _handle_submitChat(self, data, _):
        """Handle successfully submitted chat message notifications"""

        # pylint: disable=invalid-name
        # for compat reasons
        self.conn.enqueue_data("chat_success", data)
        self.conn.enqueue_data("submitChat", data)


    def _handle_generic(self, data, target):
        """Handle generic notifications"""

        self.conn.enqueue_data(target, data)

    _handle_update_assets = _handle_generic
    _handle_subscribed = _handle_generic
    _handle_hooks = _handle_generic
    _handle_login = _handle_generic
    _handle_room_old = _handle_generic
    _handle_pro = _handle_generic

    def _handle_unhandled(self, data, target):
        """Handle life, the universe and the rest"""

        if not self:
            raise ValueError(self)
        warnings.warn("unknown data type '{}' with data '{}'".
                format(target, data),
                Warning)

    def add_data(self, rawdata):
        """Add data to given room's state"""

        for data in rawdata:
            try:
                item = data[0]
                if item[0] == 2:
                    # Flush messages but we got nothing to flush
                    continue
                if item[0] != 0:
                    warnings.warn(
                            "Unknown message type '{}'".format(item[0]),
                            Warning)
                    continue
                item = item[1]
                target = item[0]
                try:
                    data = item[1]
                except IndexError:
                    data = dict()
                method = getattr(self, "_handle_" + target,
                        self._handle_unhandled)
                method(data, target)
            except IndexError:
                LOGGER.warning("Wrongly constructed message received: %r", data)

        self.conn.process_queues()

    @property
    def user_count(self):
        """Returns number of users in this room"""

        return self._user_count

    def _expire_files(self):
        """Because files are always unclean"""
        self._files = OrderedDict(
                item for item in self._files.items() if not item[1].expired)

    @property
    def files(self):
        """Returns list of File objects for this room.
        Note: This will only reflect the files at the time
        this method was called."""

        self._expire_files()
        return list(self._files.values())

    @property
    def filedict(self):
        """Returns dict of File objects for this room.
        Note: This will only reflect the files at the time
        this method was called."""

        self._expire_files()
        return dict(self._files)

    def register_filereq(self, file):
        self._filereqs[file.id] = file

    def get_user_stats(self, name):
        """Return data about the given user. Returns None if user
        does not exist."""

        req = self.conn.get(BASE_URL + "/user/" + name)
        if req.status_code != 200 or not name:
            return None

        return self.conn.make_api_call("getUserInfo", params={"name": name})

    def post_chat(self, msg, is_me=False, is_admin=False):
        """Posts a msg to this room's chat. Set me=True if you want to /me"""

        if len(msg) > self._config['max_message']:
            raise ValueError(
                    "Chat message must be at most {} characters".format(
                        self._config['max_message']))
        while not self.user.name:
            with ARBITRATOR.condition:
                ARBITRATOR.condition.wait()
        if is_admin:
            self.conn.make_call("command", [self.user.name, "a", msg])
            return
        if is_me:
            self.conn.make_call("command", [self.user.name, "me", msg])
            return

        self.conn.make_call("chat", [self.user.name, msg])

    def upload_file(self, filename, upload_as=None, blocksize=None,
            callback=None, information_callback=None, allow_timeout=False):
        """
        Uploads a file with given filename to this room.
        You may specify upload_as to change the name it is uploaded as.
        You can also specify a blocksize and a callback if you wish.
        Returns the file's id on success and None on failure."""

        with delayed_close(filename
                if hasattr(filename, "read")
                else open(filename, 'rb')) as file:
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
                except Exception:
                    pass

            files = Data({'file': {"name": filename, "value": file}},
                    blocksize=blocksize,
                    callback=callback)

            headers = {'Origin': BASE_URL}
            headers.update(files.headers)

            while True:
                key, server, file_id = self._generate_upload_key(
                        allow_timeout=allow_timeout)
                info = dict(key=key, server=server, file_id=file_id,
                        room=self.room_id, filename=filename,
                        len=files.len, resumecount=0)
                if information_callback:
                    if information_callback(info) is False:
                        continue
                break

            params = {'room': self.room_id,
                    'key': key,
                    'filename': filename}

            while True:
                try:
                    post = self.conn.post("https://{}/upload".format(server),
                            params=params,
                            data=files,
                            headers=headers)
                    post.raise_for_status()
                    break

                except requests.exceptions.ConnectionError as ex:
                    if "aborted" not in repr(ex): # ye, that's nasty but "compatible"
                        raise
                    try:
                        resume = self.conn.get("https://{}/rest/uploadStatus".format(server),
                                params={"key": key, "c": 1}).text
                        resume = json.loads(resume)
                        resume = resume["receivedBytes"]
                        if resume <= 0:
                            raise ConnectionError("Cannot resume")
                        file.seek(resume)
                        files = Data({'file': {"name": filename, "value": file}},
                                blocksize=blocksize,
                                callback=callback,
                                logical_offset=resume)
                        headers.update(files.headers)
                        params["startAt"] = resume
                        info["resumecount"] += 1
                        if information_callback:
                            information_callback(info)
                    except requests.exceptions.ConnectionError as iex:
                        if "aborted" not in repr(iex): # ye, that's nasty but "compatible"
                            raise
                        continue # another day, another try
            return file_id

    def close(self):
        """Close connection to this room"""

        self.clear()
        if hasattr(self, "conn"):
            self.conn.close()
            del self.conn
        if hasattr(self, "user"):
            del self.user

    def report(self, reason=""):
        """Reports this room to moderators with optional reason."""

        self.conn.make_call("submitReport", [{"reason": reason}])

    @property
    def config(self):
        """Get config data for this room."""

        return dict(self._config)

    @property
    def title(self):
        """Gets the title name of the room (e.g. /g/entoomen)"""

        return self._config['title']

    @title.setter
    def title(self, new_name):
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

    @private.setter
    def private(self, value):
        """Sets the room to private if given True, else sets to public"""

        if not self.owner:
            raise RuntimeError("You must own this room to do that")
        self.conn.make_call("editInfo", [{"private": value}])
        self._config['private'] = value

    def check_owner(self):
        if not self.owner and not self.admin:
            raise RuntimeError("You must own this room to do that")

    def check_admin(self):
        if not self.admin:
            raise RuntimeError("You must be an admin to do that")

    @property
    def motd(self):
        """Returns the message of the day for this room"""

        return self._config['motd']

    @motd.setter
    def motd(self, motd):
        """Sets the room's MOTD"""

        self.check_owner()
        if len(motd) > 1000:
            raise ValueError("Room's MOTD must be at most 1000 characters")
        self.conn.make_call("editInfo", [{"motd": motd}])
        self._config['motd'] = motd

    def clear(self):
        """Clears the cached information, if any"""

        self._files.clear()

    def _generate_upload_key(self, allow_timeout=False):
        """Generates a new upload key"""

        # Wait for server to set username if not set already.
        while not self.user.name:
            with ARBITRATOR.condition:
                ARBITRATOR.condition.wait()
        while True:
            params = {
                    "name": self.user.name,
                    "room": self.room_id,
                    "c": self._upload_count}
            if self.key:
                params["key"] = self.key
            elif self.password:
                params["password"] = self.password
            info = self.conn.make_api_call("getUploadKey", params=params)
            self._upload_count += 1
            try:
                return info['key'], info['server'], info['file_id']
            except Exception:
                to = int(info.get("error", {}).get("info", {}).get("timeout", 0))
                if to <= 0 or not allow_timeout:
                    raise IOError("Failed to retrieve key {}".format(info))
                time.sleep(to / 10000)


    def delete_files(self, ids):
        """ Remove this file """
        self.check_owner()
        self.conn.make_call("deleteFiles", args=[ids])

    def timeout_message(self, message, duration=3600):
        self.check_owner()
        banid = message.data["id"]
        self.conn.make_call("timeoutChat", args=[banid, duration])

    def ban(self, address, hours, reason, options, nick=None):
        self.check_admin()
        who = []
        options = options or dict()
        if hasattr(address, "ip_address"):
            address = address.ip_address
            who.append({"ip": address})
        if isinstance(address, list):
            for a in address:
                who.append({"ip": a})
        if nick is not None:
            if isinstance(nick, str):
                who.append({"user": nick})
            if isinstance(nick, list):
                for n in nick:
                    who.append({"user": n})
        ropts = {
                "ban": False, "hellban": False, "mute": False, "purgeFiles": False,
                "hours": hours, "reason": reason
                }
        ropts.update(options)
        self.conn.make_call("banUser", args=[who, ropts])

    def unban(self, address, options, reason="", nick=None):
        self.check_admin()
        who = []
        if hasattr(address, "ip_address"):
            address = address.ip_address
            who.append({"ip": address})
        if isinstance(address, list):
            for a in address:
                who.append({"ip": a})
        if nick is not None:
            if isinstance(nick, str):
                who.append({"user": nick})
            if isinstance(nick, list):
                for n in nick:
                    who.append({"user": n})
        ropts = {
                "ban": True, "hellban": True, "mute": True, "timeout": True,
                "reason": reason
                }
        ropts.update(options)
        self.conn.make_call("unbanUser", args=[who, ropts])


class Roles(Enum):
    """All recognized roles"""
    WHITE = "white"
    USER = "green"
    PRO = "pro"
    JANITOR = "janitor"
    DONOR = "donor"
    STAFF = "trusted user"
    ADMIN = "admin"
    SYSTEM = "system"

    @classmethod
    def from_options(cls, options):
        user = "profile" in options
        if user:
            if "admin" in options:
                return cls.ADMIN
            if "staff" in options:
                return cls.STAFF
            if "pro" in options:
                return cls.PRO
            if "janitor" in options:
                return cls.JANITOR
            if "donator" in options:
                return cls.DONOR
            if "user" in options:
                return cls.USER
        else:
            if "admin" in options:
                return cls.SYSTEM
        return cls.WHITE

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value


class ChatMessage:
    """Basically a struct for a chat message. self.msg holds the
    text of the message, files is a list of Files that were
    linked in the message, and rooms are a list of room
    linked in the message. There are also flags for whether the
    user of the message was logged in, a donor, or an admin."""
    # pylint: disable=too-few-public-methods

    def __init__(self, nick, msg, role=Roles.WHITE, options=None, **kw):
        if role not in Roles:
            raise ValueError("Invalid role")
        self.nick = nick
        self.msg = msg
        self.role = role
        self.options = options or dict()

        # Optionals
        self.html_msg = kw.get("html_msg", "")
        self.files = kw.get("files", ())
        self.rooms = kw.get("rooms", {})
        self.data = kw.get("data", {})
        self.self = self.data.get("self", False)

    @staticmethod
    def from_data(room, data):
        """Construct a ChatMessage instance from raw protocol data"""
        files = []
        rooms = {}
        msg = ""
        html_msg = ""

        for part in data["message"]:
            ptype = part['type']
            if ptype == 'text':
                val = part["value"]
                msg += val
                html_msg += val
            elif ptype == 'break':
                msg += "\n"
                html_msg += "\n"
            elif ptype == 'file':
                fileid = part["id"]
                file = room.filedict.get(fileid, None)
                if not file:
                    file = File(room, fileid, part['name'])
                    room.register_filereq(file)
                files += (file,)
                fileid = "@{}".format(fileid)
                msg += fileid
                html_msg += fileid
            elif ptype == 'room':
                roomid = part["id"]
                rooms[roomid] = part['name']
                roomid = "#{}".format(roomid)
                msg += roomid
                html_msg += roomid
            elif ptype == 'url':
                msg += part['text']
                html_msg += part['text']
            elif ptype == 'raw':
                msg += html_to_text(part['value'])
                html_msg += part['value']
            else:
                warnings.warn(
                        "unknown message type '{}'".format(ptype),
                        Warning)

        nick = data.get("nick", "n/a")
        options = data.get("options", {})
        options.update(room.user_info)
        data = data.get("data", {})

        message = ChatMessage(
                nick,
                msg,
                role=Roles.from_options(options),
                options=options,
                data=data,
                files=files,
                rooms=rooms,
                html_msg=html_msg
                )
        return message

    @property
    def white(self):
        return self.role is Roles.WHITE

    @property
    def user(self):
        return self.role is Roles.USER

    @property
    def pro(self):
        return self.role is Roles.PRO

    @property
    def janitor(self):
        return self.role is Roles.JANITOR

    @property
    def donor(self):
        return self.role is Roles.DONOR

    @property
    def green(self):
        return self.pro or self.donor or self.user or self.janitor

    @property
    def staff(self):
        return self.role is Roles.STAFF

    @property
    def admin(self):
        return self.role is Roles.ADMIN

    @property
    def purple(self):
        return self.admin or self.staff

    @property
    def system(self):
        return self.role is Roles.SYSTEM

    @property
    def logged_in(self):
        return self.green or self.purple or self.janitor or self.pro

    @property
    def ip_address(self):
        """Returns the uploader ip if available"""
        return self.data.get("ip")

    def __repr__(self):
        prefix = ""
        if self.purple:
            prefix += "@"
        if self.pro:
            prefix += "✡"
        if self.janitor:
            prefix += "🧹"
        if self.donor:
            prefix += "💰"
        if self.green:
            prefix += "+"
        if self.system:
            prefix += "%"
        return "<Msg({}{}, {})>".format(prefix, self.nick, self.msg)


class File:
    """Basically a struct for a file's info on volafile, with an additional
    method to retrieve the file's URL."""

    def __init__(self, room, file_id, name, **kw):
        # pylint: disable=invalid-name
        self.room = room
        self.conn = room.conn
        self.id = file_id
        self.name = name

        self._additional = dict(kw)
        self._event = Event()
        self._added_infos = False

    def __getattr__(self, name):
        if name not in ("type", "size", "expire_time", "uploader", "info"):
            raise AttributeError("Not a valid key: {}".format(name))
        try:
            return self._additional[name]
        except KeyError as ex:
            if self._added_infos:
                raise AttributeError(str(ex)) from ex
            self.conn.queues_enabled = False
            try:
                self.conn.make_call("get_fileinfo", [self.id])
                self._event.wait()
                self._added_infos = True
                try:
                    return self._additional[name]
                except KeyError as iex:
                    raise AttributeError(str(iex)) from iex
            finally:
                self.conn.queues_enabled = True

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

    @property
    def album(self):
        """Returns album name of audio file"""

        if self.type not in ("audio",):
            raise RuntimeError("Only audio files can have album names")
        return self.info.get('album')

    @property
    def artist(self):
        """Returns artist name of audio file"""

        if self.type not in ("audio",):
            raise RuntimeError("Only audio files can have artist names")
        return self.info.get('artist')

    @property
    def codec(self):
        """Returns codec type of media file"""

        if self.type not in ("video", "audio"):
            raise RuntimeError("Only audio and video files can have codecs")
        return self.info.get('codec')

    @property
    def title(self):
        """Returns title of media file"""

        if self.type not in ("video", "audio"):
            raise RuntimeError("Only audio and video files can have titles")
        return self.info.get('title')

    @property
    def ip_address(self):
        """Returns the uploader ip if available"""
        try:
            return (self._additional.get("data", {}).get("ip", None)
                or self.info["uploader_ip"])
        except KeyError as ex:
            raise AttributeError("no ip available") from ex

    def __repr__(self):
        return ("<File({}, {}, {}, {})>".
                format(self.id, self.size, self.uploader, self.name))

    def add_info(self, info):
        """Adds info to the file."""

        self.name = info['name']
        add = self._additional
        add["type"] = "other"
        for file_type in ('book', 'image', 'video', 'audio', 'archive'):
            if file_type in info:
                add["type"] = file_type
        add["info"] = info.get(self.type, {})
        add["size"] = info['size']
        add["expire_time"] = info['expires'] / 1000
        add["uploader"] = info['user']
        self._event.set()

    def delete(self):
        """ Remove this file """
        self.room.check_owner()
        self.conn.make_call("deleteFiles", args=[[self.id,]])

    def timeout(self, duration=3600):
        """ Timeout the uploader of this file """
        self.room.check_owner()
        self.conn.make_call("timeoutFile", args=[self.id, duration])


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
        self.session = None

    def login(self, password):
        """Attempts to log in as the current user with given password"""

        if self.logged_in:
            raise RuntimeError("User already logged in!")

        params = {"name": self.name,
                "password": password}
        json_resp = self.conn.make_api_call("login", params=params)
        if 'error' in json_resp:
            raise ValueError("Login unsuccessful: {}".
                    format(json_resp["error"]))
        self.session = json_resp["session"]
        self.conn.make_call("useSession", [self.session])
        self.conn.cookies.update({"session": self.session})
        self.logged_in = True
        return True

    def login_transplant(self, other):
        """Attempts to carry over the login state from another room"""

        if not other.logged_in:
            raise ValueError("Other room is not logged in")
        cookie = other.session
        if not cookie:
            raise ValueError("Other room has no cookie")
        self.conn.cookies.update({"session": cookie})
        self.session = cookie
        self.logged_in = True
        return True

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
        json_resp = self.conn.make_api_call("register", params=params)

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
        json_resp = self.conn.make_api_call("changePassword", params=params)

        if 'error' in json_resp:
            raise ValueError("Wrong password.")

    def _verify_username(self, username):
        """Raises an exception if the given username is not valid."""

        if len(username) > self._max_length or len(username) < 3:
            raise ValueError(
                    "Username must be between 3 and {} characters.".format(
                        self._max_length))
        if any(c not in string.ascii_letters +
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
