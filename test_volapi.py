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
from threading import Thread, Barrier
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
            self.assertEqual(self.r.user_count, count)
            self.assertEqual(1, count)
            return False

        self.r.listen(onusercount=compare_user_count)

    def test_get_chat_log(self):
        self.y = 1
        b = Barrier(2)
        def compare_chat(msg):
            self.assertEqual("TEST123" + str(self.y), msg.msg)
            self.y += 1
            self.assertEqual(self.r.user.name, msg.nick)
            self.assertIn(msg, self.r.chat_log)
            if self.y == 5:
                self.t = None
                return False
            

        def send_messages():
            x = 0
            b.wait()
            while self.t:
                try:
                   self.r.post_chat("TEST123" + str(x))
                   x += 1
                except:
                    break
                time.sleep(1)

        self.t = Thread(target=send_messages, daemon=True)
        self.t.start()
        b.wait()
        self.r.listen(onmessage=compare_chat)

    def test_get_files(self):
        def compare_file(f):
            self.assertEqual("test.py", f.name)
            self.assertEqual(self.r.user.name, f.uploader)
            self.assertIn(f, self.r.files)
            self.t = None
            return False

        def upload_files():
            while self.t:
                try:
                    self.r.upload_file(__file__, upload_as="test.py")
                except:
                    break
                time.sleep(1)

        self.t = Thread(target=upload_files)
        self.t.start()
        self.r.listen(onfile=compare_file)

    def test_user_change_nick(self):
        def compare_nick(msg):
            self.assertIn("newnick", msg.msg)
            self.assertTrue(msg.admin)
            self.assertEqual(self.r.user.name, "newnick")
            self.t = None
            return False

        def change_nick():
            while self.t:
                try:
                   self.r.user.change_nick("newnick")
                except:
                    break
                time.sleep(1)

        self.t = Thread(target=change_nick)
        self.t.start()
        self.r.listen(onmessage=compare_nick)

    def test_get_user_stats(self):
        self.assertIsNone(self.r.get_user_stats("bad_user"))
        self.assertIsNotNone(self.r.get_user_stats("lain"))

if __name__ == "__main__":
    unittest.main()
