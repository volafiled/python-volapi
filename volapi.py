
import random, string, websocket, thread, time, requests, re, json

BASE_URL = "https://volafile.io"
BASE_ROOM_URL = BASE_URL + "/r/"
BASE_REST_URL = BASE_URL + "/rest/"
BASE_WS_URL = "wss://volafile.io/api/"

class Room:

    def __init__(self, name=None, user=None):
        if name != None:
            self.name = name
        else:
            self.name = re.search(r'r/(.+?)$', requests.get(BASE_URL + "/new").url).group(1)
        if user != None:
            self.user = user
        else:
            self.user = User(self._randomID(5))
        checksum, checksum2 = self._getChecksums()
        ws_url = BASE_WS_URL
        ws_url += "?rn=" + self._randomID(6)
        ws_url += "&EIO=3&transport=websocket"
        ws_url += "&t=" + str(int(time.time()*1000))
        self.ws = websocket.create_connection(ws_url)
        self._startPinging()
        self._subscribe(checksum, checksum2)
        self.uploadKey = self._generateUploadKey()
        self.sendCount = 1

    # TODO
    def getFiles(self):
        pass

    def postChat(self, msg):
        self.ws.send('4[1337,[[0,["call",{"fn":"chat","args":["'+self.user.name+'","'+msg+'"]}]],'+str(self.sendCount)+']]')
        self.sendCount += 1

    # TODO
    def uploadFile(self):
        pass

    def close(self):
        self.ws.close()

    def _subscribe(self, checksum, checksum2):
        self.ws.send('4[-1,[[0,["subscribe",{"room":"'+self.name+'","checksum":"'+checksum+'","checksum2":"'+checksum2+'","nick":"'+self.user.name+'"}]],0]]')

    def userChangeNick(self, new_nick):
        if not self.user.loggedIn:
            self.ws.send('4[15,[[0,["call",{"fn":"command","args":["'+self.user.name+'","nick","'+new_nick+'"]}]],'+str(self.sendCount)+']]')
            self.sendCount += 1
            self.user.name = new_nick

    def userLogin(self, password):
        if not self.user.loggedIn:
            json_resp = json.loads(requests.get(BASE_REST_URL + "login",params={"name": self.user.name, "password": password}).text)
            if json_resp.has_key('error'):
                return
            self.ws.send('4[17,[[0,["call",{"fn":"useSession","args":["'+json_resp['session']+'"]}]],'+str(self.sendCount)+']]')
            self.user.login()
            self.sendCount += 1

    def userLogout(self):
        if self.user.loggedIn:
            self.ws.send('4[19,[[0,["call",{"fn":"logout","args":[]}]],'+str(self.sendCount)+']]')
            self.user.logout()
            self.sendCount += 1

    def _randomID(self, n):
        return ''.join(random.choice(string.ascii_letters+string.digits) for _ in range(n))

    def _startPinging(self):
        def pingForever():
            while self.ws.connected:
                time.sleep(20)
                self.ws.send('3')
        thread.start_new_thread(pingForever, ())

    def _generateUploadKey(self):
        return json.loads(requests.get(BASE_REST_URL + "getUploadKey", params={"name":self.user.name,"room":self.name}).text)

    def _getChecksums(self):
        text = requests.get(BASE_ROOM_URL + self.name).text
        cs2 = re.search(r'checksum2\s*:\s*"(\w+?)"',text).group(1)
        text = requests.get("https://static.volafile.io/static/js/main.js?c=" + cs2).text
        cs1 = re.search(r'config\.checksum\s*=\s*"(\w+?)"', text).group(1)

        return cs1, cs2

# this is gonna be a struct pretty much
class File:

    # TODO
    def __init__(self):
        pass

    # TODO
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

class User:

    def __init__(self, name):
        self.name = name
        self.loggedIn = False

    def getStats(self):
        return json.loads(requests.get(BASE_REST_URL + "getUserInfo", params={name: self.name}).text)

    def login(self):
        self.loggedIn = True

    def logout(self):
        self.loggedIn = False


hedone = User("JIDF")
room = Room("Lv5gSa", hedone)

