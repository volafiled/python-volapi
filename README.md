Volafile-API version 0.2
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

```python
class Room(builtins.object)

   __init__(self, name=None, user=None)
       # name is the room name, if none then makes a new room
       # user is your user name, if none then generates one for you
   
   close(self)
       # close connection to this room
   
   getChatLog(self)
       # returns list of ChatMessage objects for this room
   
   getFiles(self)
       # returns list of File objects for this room.
   
   getUserCount(self)
       # returns number of users in this room
   
   postChat(self, msg)
       # Posts a msg to this room's chat
   
   uploadFile(self, filename)
       # uploads a file with given filename to this room.
   
   userChangeNick(self, new_nick)
       # Change the name of your user.
       # Note: Must be logged out to change nick.
   
   userLogin(self, password)
       # Attempts to log in as the current user with given password.
   
   userLogout(self)
       # Logs your user out.

class File(builtins.object)
    # Basically a struct for a file's info on volafile, with an additional
    # method to retrieve the file's URL.
    
    # Constructor
    __init__(self, fileID, name, fileType, uploader)
    
    # Gets the URL for downloading the file
    getURL(self)

    # Fields
    self.fileID
    self.name
    self.fileType
    self.uploader
    
class ChatMessage(builtins.object)
    # Basically a struct for a chat message. self.msg holds the
    # text of the message, files is a list of Files that were
    # linked in the message, and rooms are a list of rooms 
    # linked in the message.

    # Constructor
    __init__(self, nick, msg, files, rooms)

    # Fields
    self.nick
    self.msg
    self.files
    self.rooms
```
