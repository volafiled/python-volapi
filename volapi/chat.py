from enum import Enum

from .utils import html_to_text


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
            if "staff" in options:
                return cls.SYSTEM
        return cls.WHITE

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value


class ChatMessage(str):
    """Basically a struct for a chat message. self holds the
    text of the message, files is a list of Files that were
    linked in the message, and rooms are a list of room
    linked in the message. There are also flags for whether the
    user of the message was logged in, a donor, or an admin."""

    # pylint: disable=no-member

    def __new__(cls, room, nick, msg, role=Roles.WHITE, options=None, **kw):
        if role not in Roles:
            raise ValueError("Invalid role")
        obj = super().__new__(cls, msg)
        obj.room = room
        obj.nick = nick
        obj.role = role
        obj.options = options or dict()

        # Optionals
        obj.files = kw.get("files", list())
        obj.rooms = kw.get("rooms", dict())
        obj.data = kw.get("data", dict())
        obj.mymsg = obj.data.get("self", False)
        return obj

    @staticmethod
    def from_data(room, data):
        """Construct a ChatMessage instance from raw protocol data"""
        files = list()
        rooms = dict()
        msg = str()

        for part in data["message"]:
            ptype = part["type"]
            if ptype == "text":
                val = part["value"]
                msg += val
            elif ptype == "break":
                msg += "\n"
            elif ptype == "file":
                fileid = part["id"]
                fileobj = room.filedict.get(fileid)
                if fileobj:
                    files += (fileobj,)
                fileid = f"@{fileid}"
                msg += fileid
            elif ptype == "room":
                roomid = part["id"]
                rooms[roomid] = part["name"]
                roomid = f"#{roomid}"
                msg += roomid
            elif ptype == "url":
                msg += part["text"]
            elif ptype == "raw":
                msg += html_to_text(part["value"])
            else:
                import warnings

                warnings.warn(f"unknown message type '{ptype}'", Warning)

        nick = data.get("nick", "n/a")
        options = data.get("options", dict())
        data = data.get("data", dict())

        message = ChatMessage(
            room,
            nick,
            msg,
            role=Roles.from_options(options),
            options=options,
            data=data,
            files=files,
            rooms=rooms,
        )
        return message

    def timeout(self, duration=3600):
        self.room.check_owner()
        if duration <= 0:
            raise RuntimeError("Timeout duration have to be a positive number")
        msg_id = self.data.get("id")
        if msg_id is None:
            raise RuntimeError("No message ID, you can't timeout system or mods")
        self.room.conn.make_call("timeoutChat", msg_id, duration)

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
        return f"<Msg({prefix}{self.nick}, {self})>"
