class Config(dict):

    """Class that allows accessing room config dict by using attribute names.
    Mapping specifies what values will be read/written by our API."""

    def __init__(self):
        super().__init__()
        self.setdefault("janitors", list())
        self.setdefault("disabled", False)
        self.setdefault("owner", str())
        self.__cfg_mapping = dict(
            adult=("adult", bool),
            private=("private", bool),
            disabled=("disabled", bool),
            owner=("owner", str),
            janitors=("janitors", list),
            room_id=("room_id", str),
            alias=("custom_room_id", str),
            title=("name", str),
            motd=("motd", str),
            max_title=("max_room_name_length", int),
            max_message=("chat_max_message_length", int),
            max_nick=("chat_max_alias_length", int),
            max_file=("file_max_size", int),
            session_lifetime=("session_lifetime", int),
            file_ttl=("file_ttl", int),
            creation_time=("created_time", int),
        )

    def __getattr__(self, key):
        if key not in self.__cfg_mapping:
            raise KeyError(f"Mapping for the key `{key}` doesn't exist")
        return self[key]

    def update(self, config):
        for k, v in self.__cfg_mapping.items():
            if v[0] not in config:
                continue
            if isinstance(config[v[0]], v[1]):
                self[k] = config[v[0]]
            else:
                self[k] = v[1]()

    def get_real_key(self, key):
        return self.__cfg_mapping[key][0]
