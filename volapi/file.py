import time

from .constants import BASE_URL


class File:
    """Basically a struct for a file's info on volafile, with an additional
    method to retrieve the file's URL."""

    def __init__(self, room, file_id, name, **kw):
        self.room = room
        self.conn = room.conn
        self.fid = file_id
        self.name = name

        self.__additional = dict(kw)

    def __getattr__(self, name):
        if name not in (
            "type",
            "size",
            "expire_time",
            "uploader",
            "checksum",
            "info",
            "thumb",
        ):
            raise AttributeError(f"Not a valid key: {name}")
        try:
            return self.__additional[name]
        except KeyError:
            self.conn.queues_enabled = False
            data = self.room.fileinfo(self.fid)
            self.name = data["name"]
            add = self.__additional
            add["type"] = "other"
            for file_type in ("book", "image", "video", "audio", "archive"):
                if file_type in data:
                    add["type"] = file_type
                    break
            if add["type"] in ("image", "video", "audio"):
                add["thumb"] = data.get("thumb", dict())
            # checksum is md5
            add["checksum"] = data["checksum"]
            add["expire_time"] = data["expires"] / 1000
            add["size"] = data["size"]
            add["info"] = data.get(self.type, dict())
            add["uploader"] = data["user"]
            if self.room.admin:
                add["info"].update({"room": data.get("room")})
                add["info"].update({"uploader_ip": data.get("uploader_ip")})
            self.conn.queues_enabled = True
            return self.__additional[name]

    @property
    def url(self):
        """Gets the download url of the file"""

        return f"{BASE_URL}/get/{self.fid}/{self.name}"

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
        """Returns the thumbnail url for this image, audio, or video file.
        Returns `None` if the file has no thumbnail"""

        if self.type not in ("video", "image", "audio"):
            raise RuntimeError("Only video, audio and image files have thumbnails")
        thumb_srv = self.thumb.get("server")
        url = f"https://{thumb_srv}" if thumb_srv else None
        if url:
            return f"{url}/asset/{self.fid}/thumb"
        return None

    @property
    def resolution(self):
        """Gets the resolution of this image or video file in format (W, H)"""

        if self.type not in ("video", "image"):
            raise RuntimeError("Only videos and images have resolutions")
        return (self.info["width"], self.info["height"])

    @property
    def duration(self):
        """Returns the duration in seconds of this audio or video file"""

        if self.type not in ("video", "audio"):
            raise RuntimeError("Only videos and audio have durations")
        return self.info.get("length") or self.info.get("duration")

    @property
    def album(self):
        """Returns album name of audio file"""

        if self.type not in ("audio",):
            raise RuntimeError("Only audio files can have album names")
        return self.info.get("album")

    @property
    def artist(self):
        """Returns artist name of audio file"""

        if self.type not in ("audio",):
            raise RuntimeError("Only audio files can have artist names")
        return self.info.get("artist")

    @property
    def codec(self):
        """Returns codec type of media file"""

        if self.type not in ("video", "audio"):
            raise RuntimeError("Only audio and video files can have codecs")
        return self.info.get("codec")

    @property
    def title(self):
        """Returns title of media file"""

        if self.type not in ("video", "audio"):
            raise RuntimeError("Only audio and video files can have titles")
        return self.info.get("title")

    @property
    def ip_address(self):
        """Returns the uploader ip if you are a mod"""
        self.room.check_admin()
        return self.info.get("uploader_ip")

    @property
    def host_room(self):
        """Returns ID of the room to which the file is uploaded if you are a mod"""
        self.room.check_admin()
        return self.info.get("room")

    def delete(self):
        """ Remove this file """
        self.room.check_owner()
        self.conn.make_call("deleteFiles", [self.fid])

    def timeout(self, duration=3600):
        """ Timeout the uploader of this file """
        self.room.check_owner()
        self.conn.make_call("timeoutFile", self.fid, duration)

    def __repr__(self):
        return f"<File({self.fid}, {self.size}, {self.uploader}, {self.name})>"
