=====================
Volafile API (volapi)
=====================

Installation
------------
::

    pip3 install volapi

Example
-------
.. code-block:: python

    from volapi import Room
    with Room("BEEPi", "ptc") as beepi:
        id = beepi.upload_file("images/disgusted.jpg", upload_as="mfw.jpg")
        beepi.post_chat("Hey guys check out my file @{}".format(id))
        for msg in beepi.chat_log:
            print(msg.nick + ": " + msg.msg)
