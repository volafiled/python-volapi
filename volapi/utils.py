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

import json
import random
import string

from html.parser import HTMLParser


class MLStripper(HTMLParser):
    """Used for stripping HTML from text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        """Gets the non-HTML data from text that was fed in"""

        return ''.join(self.fed)


def html_to_text(html):
    """Strips HTML tags from given text and returns it."""

    stripper = MLStripper()
    stripper.feed(html)
    return stripper.get_data()


def random_id(length):
    """Generates a random ID of given length"""

    def char():
        """Generate single random char"""

        return random.choice(string.ascii_letters + string.digits)

    return ''.join(char() for _ in range(length))


def to_json(obj):
    """Create a compact JSON string from an object"""

    return json.dumps(obj, separators=(',', ':'))
