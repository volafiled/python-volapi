Volafile-API version 0.1
============

Example:

```python
from volapi import room
beepi = Room("BEEPi", "ptc")
beepi.postChat("kek")
beepi.uploadFile("shekel.jewpeg")
for msg in beepi.getChatLog():
    print msg.nick + ": " + msg.msg
beepi.close()
```
