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

import unittest
import time
from threading import Thread

from volapi import Room

ROOM = Room()

class TestVolapi(unittest.TestCase):

    """Main testing suite for volapi"""

    recv_index = 1

    def test_chat_log(self):
        """Make sure chatlog is the same as recieved chats and they
        arrive in the right order"""

        def compare_chat(msg):
            # pylint: disable=missing-docstring
            if not msg.admin:
                self.assertEqual("TEST123" + str(self.recv_index), msg.msg)
                self.recv_index += 1
                self.assertEqual(ROOM.user.name, msg.nick)
                self.assertIn(msg, ROOM.chat_log)
                if self.recv_index == 3:
                    return False

        Thread(daemon=True, target=lambda:ROOM.add_listener("chat", compare_chat) or ROOM.listen()).start()

        for send_index in range(1, 4):
            ROOM.post_chat("TEST123" + str(send_index))
            time.sleep(1)

    def test_files(self):
        """Test uploading and looking at files."""
        def compare_file(file):
            # pylint: disable=missing-docstring
            self.assertEqual("test.py", file.name)
            self.assertEqual(ROOM.user.name, file.uploader)
            self.assertIn(file, ROOM.files)
            self.assertEqual(file, ROOM.get_file(file.id))
            return False

        Thread(daemon=True, target=lambda:ROOM.add_listener("file", compare_file) or ROOM.listen()).start()
        ROOM.upload_file(__file__, upload_as="test.py")

    def test_user_change_nick(self):
        """Make sure nickname changes correctly"""
        def compare_nick(msg):
            # pylint: disable=missing-docstring
            if "newnick" in msg.msg:
                self.assertIn("newnick", msg.msg)
                self.assertTrue(msg.admin)
                self.assertEqual(ROOM.user.name, "newnick")
                return False

        Thread(daemon=True, target=lambda:ROOM.add_listener("chat", compare_nick) or ROOM.listen()).start()

    def test_get_user_stats(self):
        """Test inquires about registered users"""
        self.assertIsNone(ROOM.get_user_stats("bad_user"))
        self.assertIsNotNone(ROOM.get_user_stats("lain"))

    def test_room_title(self):
        """Test setting and getting room's title"""
        self.assertTrue(ROOM.owner)
        self.assertEqual("New Room", ROOM.title)
        ROOM.set_title("titlechange")
        self.assertEqual("titlechange", ROOM.title)

    def test_private(self):
        """Test setting and getting room's privacy"""
        self.assertEqual(True, ROOM.private)
        ROOM.set_private(False)
        self.assertEqual(False, ROOM.private)

    def test_motd(self):
        """Test setting and getting room's MOTD"""
        self.assertEqual("", ROOM.motd)
        ROOM.set_motd("new motd")
        self.assertEqual("new motd", ROOM.motd)

    def test_beepi(self):
        """Make sure BEEPi can open"""
        with Room("BEEPi") as beepi:
            def check_users(usercount):
                # pylint: disable=missing-docstring
                self.assertGreater(usercount, 1)
                return False
            beepi.add_listener("user_count", check_users)
            beepi.listen()

if __name__ == "__main__":
    unittest.main()
