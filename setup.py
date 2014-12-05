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

from setuptools import setup
import re


def find_version(filename):
    """
    Search for assignment of __version__ string in given file and
    return what it is assigned to.
    """
    with open(filename, 'r') as filep:
        version_file = filep.read()
        version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
        if version_match:
            return version_match.group(1)
        raise RuntimeError("Unable to find version string.")

setup(
    name='volapi',
    version=find_version('volapi/volapi.py'),
    description='RESTful API for Volafile.io',
    long_description=open('README.rst', 'r').read(),
    url='https://github.com/PhearTheCeal/Volafile-API',
    license='GPLv3',
    author='PhearTheCeal',
    author_email='ptc@ptc.pe',
    packages=['volapi'],
    include_package_data=True,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        "Operating System :: POSIX",
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    install_requires=['websocket-client', 'requests']
)
