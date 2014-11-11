
import random, string, websocket, thread, time, requests, re

BASE_URL = "https://volafile.io"
BASE_ROOM_URL = BASE_URL + "/r/"
BASE_REST_URL = BASE_URL + "/rest/"
BASE_WS_URL = "wss://volafile.io/api/"

# This will be the main websocket interface
class Room:

    # TODO add support for blank name (make new room)
    # TODO add support for blank user (let Vola generate random name)
    def __init__(self, name, user):
        self.name = name
        self.user = user
        checksum, checksum2 = self._getChecksums()
        ws_url = BASE_WS_URL
        ws_url += "?rn=" + self._randomID(6)
        ws_url += "&EIO=3&transport=websocket"
        ws_url += "&t=" + str(int(time.time()*1000))
        self.ws = websocket.create_connection(ws_url)
        self._startPinging()
        self._subscribe(checksum, checksum2)
        self.chatCount = 1

    def getFiles(self):
        pass

    def postChat(self, msg):
        self.ws.send('4[1337,[[0,["call",{"fn":"chat","args":["'+self.user.name+'","'+msg+'"]}]],'+str(self.chatCount)+']]')
        self.chatCount += 1

    def uploadFile(self):
        pass

    def close(self):
        pass

    def _subscribe(self, checksum, checksum2):
        self.ws.send('4[-1,[[0,["subscribe",{"room":"'+self.name+'","checksum":"'+checksum+'","checksum2":"'+checksum2+'","nick":"'+self.user.name+'"}]],0]]')

    def _randomID(self, n):
        return ''.join(random.choice(string.ascii_letters+string.digits) for _ in range(n))

    def _startPinging(self):
        def pingForever():
            while self.ws.connected:
                time.sleep(10)
                self.ws.send('3')
        thread.start_new_thread(pingForever, ())

    def _getChecksums(self):
        text = requests.get(BASE_ROOM_URL + self.name).text
        cs2 = re.search(r'checksum2\s*:\s*"(\w+?)"',text).group(1)
        text = requests.get("https://static.volafile.io/static/js/main.js?c=" + cs2).text
        cs1 = re.search(r'config\.checksum\s*=\s*"(\w+?)"', text).group(1)

        return cs1, cs2

# this is gonna be a struct pretty much
class File:

    def __init__(self):
        pass

    def getInfo(self):
        pass

# not sure if I need this yet
class Upload:

    def __init__(self):
        pass

    def abort(self):
        pass

    def status(self):
        pass

# managing user shit and cookies (yuk)
class User:

    def __init__(self, name):
        self.name = name

    def getStats(self):
        pass

    def setName(self):
        pass

    def setPassword(self):
        pass

    def login(self):
        pass

    def logout(self):
        pass

