=====================
Volafile API (volapi)
=====================

Installation
------------
::

    pip install volapi

Example
-------
::

    from volapi import Room
    beepi = Room("BEEPi", "ptc")
    beepi.post_chat("kek")
    beepi.upload_file("images/disgusted.jpg", upload_as="mfw.jpg")
    for msg in beepi.chat_log:
        print(msg.nick + ": " + msg.msg)
    beepi.close()
