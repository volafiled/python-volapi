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
import warnings

from volapi import Room

room = Room()


class TestVolapi(unittest.TestCase):

    """Main testing suite for volapi"""

    recv_index = 1

    def test_user_count(self):
        """Make sure there is 1 user (you) in room"""
        def compare_user_count(count):
            # pylint: disable=missing-docstring
            self.assertEqual(room.user_count, count)
            self.assertEqual(1, count)
            return False

        room.listen(onusercount=compare_user_count)

    def test_chat_log(self):
        """Make sure chatlog is the same as recieved chats and they
        arrive in the right order"""

        def compare_chat(msg):
            # pylint: disable=missing-docstring
            if not msg.admin:
                self.assertEqual("TEST123" + str(self.recv_index), msg.msg)
                self.recv_index += 1
                self.assertEqual(room.user.name, msg.nick)
                self.assertIn(msg, room.chat_log)
                if self.recv_index == 3:
                    return False

        for send_index in range(1, 3):
            room.post_chat("TEST123" + str(send_index))
            send_index += 1
            time.sleep(1)

        room.listen(onmessage=compare_chat)

    def test_files(self):
        """Test uploading and looking at files."""
        def compare_file(file):
            # pylint: disable=missing-docstring
            self.assertEqual("test.py", file.name)
            self.assertEqual(room.user.name, file.uploader)
            self.assertIn(file, room.files)
            self.assertEqual(file, room.get_file(file.file_id))
            return False

        room.upload_file(__file__, upload_as="test.py")
        room.listen(onfile=compare_file)

    def test_user_change_nick(self):
        """Make sure nickname changes correctly"""
        def compare_nick(msg):
            # pylint: disable=missing-docstring
            if "newnick" in msg.msg:
                self.assertIn("newnick", msg.msg)
                self.assertTrue(msg.admin)
                self.assertEqual(room.user.name, "newnick")
                return False

        room.user.change_nick("newnick")
        room.listen(onmessage=compare_nick)

    def test_get_user_stats(self):
        """Test inquires about registered users"""
        self.assertIsNone(room.get_user_stats("bad_user"))
        self.assertIsNotNone(room.get_user_stats("lain"))

    def test_room_title(self):
        """Test setting and getting room's title"""
        self.assertTrue(room.owner)
        self.assertEqual("New Room", room.title)
        room.set_title("titlechange")
        self.assertEqual("titlechange", room.title)

    def test_private(self):
        """Test setting and getting room's privacy"""
        self.assertEqual(True, room.private)
        room.set_private(False)
        self.assertEqual(False, room.private)

    def test_motd(self):
        """Test setting and getting room's MOTD"""
        self.assertEqual("", room.motd)
        room.set_motd("new motd")
        self.assertEqual("new motd", room.motd)

if __name__ == "__main__":
    unittest.main()
