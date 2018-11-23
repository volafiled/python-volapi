=====================
Volafile API (volapi)
=====================

.. image:: https://img.shields.io/badge/style-BLACKED-black.svg?longCache=true&style=flat-square
    :target: https://github.com/ambv/black

Installation
------------
::

    pip3 install volapi

If you have it installed already but want to update

::

   pip3 install -U volapi

Examples
--------

Basic
~~~~~

.. code-block:: python

    # Import volapi and a Room interface
    from volapi import Room

    # beepi will close at the end of this scope
    with Room("BEEPi", "SameFag") as beepi:
        # optional login using a password
        beepi.user.login("hunter2")
        # Upload a file under a new filename and save the id
        fid = beepi.upload_file("images/disgusted.jpg", upload_as="mfw.jpg")
        # Show off your file in the chat
        beepi.post_chat("mfw posting from volapi @{}".format(fid))

Listening
~~~~~~~~~

Getting urls of all the files in the room:

.. code-block:: python

   from volapi import Room

   with Room("BEEPi", "ScrappyBoy") as BEEPi:
       BEEPi.listen(once=True)
       for f in BEEPi.files:
           print(f.url)

Some basic trolling can be achieved with just a few lines of code.

.. code-block:: python

    from volapi import Room

    with Room("BEEPi", "Stallman") as BEEPi:
        def interject(msg):
            if "linux" in msg.lower() and msg.nick != BEEPi.user.nick:
                BEEPi.post_chat("Don't you mean GNU/Linux?")
        BEEPi.add_listener("chat", interject)
        BEEPi.listen()

You can troll more than one room in parallel:

.. code-block:: python

    from functools import partial
    from volapi import Room, listen_many

    with Room("BEEPi", "Stallman") as BEEPi, Room("HvoXwS", "Popman") as HvoXwS:
        def interjectBEEPi(msg, room):
            if "linux" in msg.lower() and msg.nick != room.user.nick:
                room.post_chat("Don't you mean GNU/Linux?")
        def interjectHvoXwS(msg, room):
            if "hollywood" in msg.lower() and msg.nick != room.user.nick:
                room.post_chat("Don't you mean GNU/Hollywood?")
        BEEPi.add_listener("chat", partial(interjectBEEPi, room=BEEPi))
        HvoXwS.add_listener("chat", partial(interjectHvoXwS, room=HvoXwS))
        listen_many(BEEPi, HvoXwS)

Contributing
~~~~~~~~~~~~

Just do whatever, and post a pull request. No guarantee of a merge tho!

If you cannot code, then please consider making a donation to our favorite
charity "Cucks in Need Croatia" as one of our own, a user named "auxo", is
politically procecuted for being a cuck in his native Croatia.
