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
import warnings

from volapi import Room

class TestVolapi(unittest.TestCase):

    room_name = None
    r = None

    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        if not self.r or not self.r.connected:
            self.r = Room(name=self.room_name)
            self.room_name = self.r.name

    def test_user_count(self):
        def compare_user_count(count):
            self.assertEqual(self.r.get_user_count(), count)
            self.assertEqual(1, count)
            return False

        self.r.listen(onusercount=compare_user_count)

    def test_get_chat_log(self):
        def compare_chat(msg):
            self.assertEqual("TEST123", msg.msg)
            self.assertEqual(self.r.user.name, msg.nick)
            self.assertIn(msg, self.r.get_chat_log())
            self.send_msg = False
            self.t.stop()
            return False

        def send_messages():
            while self.r.connected:
                try:
                   self.r.post_chat("TEST123")
                except:
                    break
                time.sleep(1)

        self.t = Thread(target=send_messages)
        self.t.start()
        self.r.listen(onmessage=compare_chat)

    def test_get_files(self):
        def compare_file(f):
            self.assertEqual("test.py", f.name)
            self.assertEqual(self.r.user.name, f.uploader)
            self.assertIn(f, self.r.get_files())
            self.t.stop()
            return False

        def upload_files():
            while self.r.connected:
                try:
                    self.r.upload_file(__file__, upload_as="test.py")
                except:
                    break
                time.sleep(1)

        self.t = Thread(target=upload_files)
        self.t.start()
        self.r.listen(onfile=compare_file)

    def test_close(self):
        self.assertTrue(self.r.connected)
        self.r.close()
        self.assertFalse(self.r.connected)

    def test_user_change_nick(self):
        def compare_nick(msg):
            self.assertIn("newnick", msg.msg)
            self.assertTrue(msg.admin)
            self.assertEqual(self.r.user.name, "newnick")
            self.t.stop()
            return False

        def change_nick():
            while self.r.connected:
                try:
                   self.r.user_change_nick("newnick")
                except:
                    break
                time.sleep(1)

        self.t = Thread(target=change_nick)
        self.t.start()
        self.r.listen(onmessage=compare_nick)

    def test_user_login(self):
        self.assertRaises(ValueError, self.r.user_login, "badpass")

    def test_get_user_stats(self):
        self.assertIsNone(self.r.get_user_stats("bad_user"))
        self.assertIsNotNone(self.r.get_user_stats("lain"))

    def test_user_logout(self):
        self.assertRaises(RuntimeError, self.r.user_logout)

if __name__ == "__main__":
    unittest.main()
