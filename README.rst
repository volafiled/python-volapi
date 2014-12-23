=====================
Volafile API (volapi)
=====================

Installation
------------
::

    pip3 install volapi

Examples
-------

Basic
~~~~~
.. code-block:: python

    # Import volapi and a Room interface
    from volapi import Room
    
    # beepi will close at the end of this scope
    with Room("BEEPi", "ptc") as beepi:
        # login using a password
        beepi.user.login("hunter2")
        # Upload a file under a new filename and save the id
        id = beepi.upload_file("images/disgusted.jpg", upload_as="mfw.jpg")
        # Show off your file in the chat
        beepi.post_chat("Hey guys check out my file @{}".format(id))
        # Print out chat messages since you got to the room
        for msg in beepi.chat_log:
            print(msg.nick + ": " + msg.msg)

Listening
~~~~~~~~~~

.. code-block:: python

    with Room("BEEPi", "Stallman") as room:
        def interject(msg):
            if "linux" in msg.msg.lower():
                room.post_chat("Don't you mean GNU/Linux?")
        room.add_listener("chat", interject)
        room.listen()
