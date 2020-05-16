import logging
import warnings

from functools import partial


from .file import File
from .chat import ChatMessage
from .auxo import ARBITRATOR

LOGGER = logging.getLogger(__name__)

GENERICS = [
    "roomScore",
    "submitChat",
    "submitCommand",
    "pro",
    "room_old",
    "upload",
    "reconnectTimeout",
]


class Handler:
    def __init__(self, conn):
        self.conn = conn
        self.room = conn.room
        self.__head = "_handle_"
        self.__callbacks = {}
        self.__cid = 0
        for g in GENERICS:
            setattr(self, f"{self.__head}{g}", partial(self._handle_generic, g))

    def add_data(self, rawdata):
        """Add data to given room's state"""

        for data in rawdata:
            try:
                item = data[0]
                if item[0] == 2:
                    # Flush messages but we got nothing to flush
                    continue
                if item[0] != 0:
                    warnings.warn(f"Unknown message type '{item[0]}'", Warning)
                    continue
                item = item[1]
                # convert target to string because error codes are ints
                target = str(item[0])
                try:
                    data = item[1]
                except IndexError:
                    data = {}
                try:
                    method = getattr(self, f"{self.__head}{target}")
                    method(data)
                except AttributeError:
                    self._handle_unhandled(target, data)
            except IndexError:
                LOGGER.warning("Wrongly constructed message received: %r", data)

        self.conn.process_queues()

    def register_callback(self):
        """Register callback that we will have to wait for"""

        cid = str(self.__cid)
        self.__cid += 1
        event = ARBITRATOR.loop.create_future()
        self.__callbacks[cid] = event
        return cid, event

    def _handle_generic(self, target, data):
        """Handle generic notifications"""

        self.conn.enqueue_data(target, data)

    @staticmethod
    def _handle_unhandled(target, data):
        """Handle life, the universe and the rest"""

        warnings.warn(f"unknown data type '{target}' with data '{data}'", Warning)

    def _handle_401(self, data):
        """Handle Lain being helpful"""

        ex = ConnectionError(
            "Can't login to a protected room without a proper password", data
        )
        self.conn.reraise(ex)

    def _handle_429(self, data):
        """Handle Lain being helpful"""

        ex = IOError("Too fast", data)
        self.conn.reraise(ex)

    def _handle_callback(self, data):
        """Handle lain's callback. Only used with getFileinfo so far"""

        cb_id = data.get("id")
        args = data.get("args")
        event = self.__callbacks.pop(cb_id, None)
        if not event:
            return
        if not args:
            event.cancel()
            return
        err, info = args
        if err is None:
            event.set_result(info)
        else:
            LOGGER.warning("Callback returned error of %s", str(err))
            event.set_result(err)

    def _handle_userCount(self, data):
        """Handle user count changes"""

        self.room.user_count = data
        self.conn.enqueue_data("user_count", self.room.user_count)

    def _handle_userInfo(self, data):
        """Handle user information"""

        for k, v in data.items():
            if k == "nick":
                if v == "None":
                    v = "Volaphile"
                setattr(self.room.user, k, v)
                self.conn.enqueue_data(k, self.room.user.nick)
            elif k != "profile":
                if not hasattr(self.room, k):
                    warnings.warn(f"Skipping unset property {k}", ResourceWarning)
                    continue
                setattr(self.room, k, v)
                self.conn.enqueue_data(k, getattr(self.room, k))
            self.room.user_info = k, v
        self.conn.enqueue_data("user_info", self.room.user_info)

    def _handle_removeMessages(self, data):
        """Handle mods purging stuff"""

        try:
            removed_msgs = data.get("msgIds")
        except AttributeError:
            removed_msgs = []
        self.conn.enqueue_data("removed_messages", removed_msgs)

    def _handle_key(self, data):
        """Handle keys"""

        self.room.key = data
        self.conn.enqueue_data("key", self.room.key)

    def _handle_config(self, data):
        """Handle initial config push and config changes"""

        self.room.config.update(data)
        self.conn.enqueue_data("config", data)

    def _handle_files(self, data):
        """Handle new files being uploaded"""

        initial = data.get("set", False)
        files = data["files"]
        for f in files:
            try:
                fobj = File(
                    self.room,
                    self.conn,
                    f[0],
                    f[1],
                    type=f[2],
                    size=f[3],
                    expire_time=int(f[4]) / 1000,
                    uploader=f[6].get("nick") or f[6].get("user"),
                )
                self.room.filedict = fobj.fid, fobj
                if not initial:
                    self.conn.enqueue_data("file", fobj)
            except Exception:
                import pprint

                LOGGER.exception("bad file")
                pprint.pprint(f)
        if initial:
            self.conn.enqueue_data("initial_files", self.room.filedict.values())

    def _handle_delete_file(self, data):
        """Handle files being removed"""

        file = self.room.filedict.get(data)
        if file:
            self.room.filedict = data, None
            self.conn.enqueue_data("delete_file", file)

    def _handle_chat(self, data):
        """Handle chat messages"""

        self.conn.enqueue_data(
            "chat", ChatMessage.from_data(self.room, self.conn, data)
        )

    def _handle_changed_config(self, change):
        """Handle configuration changes"""

        key, value = change.get("key"), change.get("value")
        self.room.config.update({key: value})
        self.conn.enqueue_data("config", self.room.config)

    def _handle_chat_name(self, data):
        """Handle user name changes"""

        self.room.user.nick = data
        self.conn.enqueue_data("user", self.room.user)

    def _handle_time(self, data):
        """Handle time changes"""

        self.conn.enqueue_data("time", data / 1000)

    def _handle_subscribed(self, data):
        """Room is armed and ready to get DDoSed"""

        LOGGER.debug("armed and ready to receive messages")
        self.conn.enqueue_data("subscribed", data)
