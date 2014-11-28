Volafile-API version 0.3b
============

Requires the websocket-client and requests packages.
```
pip3 install websocket-client
pip3 install requests
```

Example:

```python
from volapi import Room
beepi = Room("BEEPi", "ptc")
beepi.postChat("kek")
beepi.uploadFile("shekel.jewpeg")
for msg in beepi.getChatLog():
    print(msg.nick + ": " + msg.msg)
beepi.close()
```
Documentation:

```pydoc
CLASSES
class ChatMessage(builtins.object)
     |  Basically a struct for a chat message. self.msg holds the
     |  text of the message, files is a list of Files that were
     |  linked in the message, and rooms are a list of room
     |  linked in the message. There are also flags for whether the
     |  user of the message was logged in, a donor, or an admin.
     |  
     |  Methods defined here:
     |  
     |  __init__(self, nick, msg, files, rooms, loggedIn, donor, admin)

    
    class File(builtins.object)
     |  Basically a struct for a file's info on volafile, with an additional
     |  method to retrieve the file's URL.
     |  
     |  Methods defined here:
     |  
     |  __init__(self, fileID, name, fileType, uploader)
     |  
     |  getURL(self)
    
    class Room(builtins.object)
     |  Use this to interact with a room as a user
     |  Example:
     |      r = Room("BEEPi", "ptc")
     |      r.postChat("Hello, world!")
     |      r.uploadFile("onii-chan.ogg")
     |      r.close()
     |  
     |  Methods defined here:
     |  
     |  __init__(self, name=None, user=None)
     |      name is the room name, if none then makes a new room
     |      user is your user name, if none then generates one for you
     |  
     |  close(self)
     |      Close connection to this room
     |  
     |  getChatLog(self)
     |      Returns list of ChatMessage objects for this room
     |  
     |  getFiles(self)
     |      Returns list of File objects for this room
     |  
     |  getUserCount(self)
     |      Returns number of users in this room
     |  
     |  postChat(self, msg)
     |      Posts a msg to this room's chat
     |  
     |  uploadFile(self, filename, uploadAs=None, blocksize=None, cb=None)
     |      Uploads a file with given filename to this room.
     |      You may specify uploadAs to change the name it is uploaded as.
     |      You can also specify a blocksize and a callback if you wish.
     |  
     |  userChangeNick(self, new_nick)
     |      Change the name of your user
     |      Note: Must be logged out to change nick
     |  
     |  userLogin(self, password)
     |      Attempts to log in as the current user with given password
     |  
     |  userLogout(self)
     |      Logs your user out
```
