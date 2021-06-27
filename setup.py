"""
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
"""

import re
from setuptools import setup


def find_version(filename):
    """
    Search for assignment of __version__ string in given file and
    return what it is assigned to.
    """
    with open(filename, "r") as filep:
        version_file = filep.read()
        version_match = re.search(
            r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M
        )
        if version_match:
            return version_match.group(1)
        raise RuntimeError("Unable to find version string.")


setup(
    name="volapi",
    version=find_version("volapi/constants.py"),
    description="API for Volafile.org",
    long_description=open("README.rst", "r").read(),
    url="https://github.com/volafiled/python-volapi",
    license="MIT",
    author="RealDolos, szero",
    author_email="dolos@cock.li, singleton@tfwno.gf",
    packages=["volapi"],
    extras_require={"FAST_JSON": ["orjson>=3,<4"]},
    include_package_data=True,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    install_requires=[l.strip() for l in open("requirements.txt").readlines()],
)
