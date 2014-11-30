=====================
Volafile API (volapi)
=====================

Installation
------------
::

    pip3 install volapi

Example
-------
::

    from volapi import Room
    beepi = Room("BEEPi", "ptc")
    beepi.postChat("kek")
    beepi.uploadFile("shekel.jewpeg")
    for msg in beepi.getChatLog():
        print(msg.nick + ": " + msg.msg)
    beepi.close()
