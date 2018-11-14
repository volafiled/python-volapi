import string


class User:
    """Used by Room. Currently not very useful by itself"""

    def __init__(self, nick, conn, max_len):
        self._max_length = max_len
        if nick is None:
            self.nick = ""
        else:
            self._verify_username(nick)
        self.nick = nick
        self.conn = conn
        self.logged_in = False
        self.session = None

    def login(self, password):
        """Attempts to log in as the current user with given password"""

        self.conn.room.ensure_cfg.wait()
        if self.logged_in:
            raise RuntimeError("User already logged in!")

        params = {"name": self.nick, "password": password}
        json_resp = self.conn.make_api_call("login", params=params)
        if "error" in json_resp:
            raise ValueError(f"Login unsuccessful: {json_resp['error']}")
        self.session = json_resp["session"]
        self.conn.make_call("useSession", self.session)
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
        if self.conn.connected:
            self.conn.make_call("logout")
        self.logged_in = False

    def change_nick(self, new_nick):
        """Change the name of your user
        Note: Must be logged out to change nick"""

        if self.logged_in:
            raise RuntimeError("User must be logged out")
        self._verify_username(new_nick)

        self.conn.make_call("command", self.nick, "nick", new_nick)
        self.nick = new_nick

    def register(self, password):
        """Registers the current user with the given password."""

        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")

        params = {"name": self.nick, "password": password}
        json_resp = self.conn.make_api_call("register", params=params)

        if "error" in json_resp:
            raise ValueError(f"User '{self.nick}' is already registered")

        self.conn.make_call("useSession", json_resp["session"])
        self.conn.cookies.update({"session": json_resp["session"]})
        self.logged_in = True

    def change_password(self, old_pass, new_pass):
        """Changes the password for the currently logged in user."""

        if len(new_pass) < 8:
            raise ValueError("Password must be at least 8 characters.")

        params = {"name": self.nick, "password": new_pass, "old_password": old_pass}
        json_resp = self.conn.make_api_call("changePassword", params=params)

        if "error" in json_resp:
            raise ValueError("Wrong password.")

    def _verify_username(self, username):
        """Raises an exception if the given username is not valid."""

        if len(username) > self._max_length or len(username) < 3:
            raise ValueError(
                f"Username must be between 3 and {self._max_length} characters."
            )
        if any(c not in string.ascii_letters + string.digits for c in username):
            raise ValueError("Usernames can only contain alphanumeric characters.")

    def __repr__(self):
        return f"<User({self.nick}, {self.logged_in})>"
