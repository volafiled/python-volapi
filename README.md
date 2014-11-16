Volafile-API version 0.1
============

Requires the websocket-client package
```
pip3 install websocket-client
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
