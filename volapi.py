
import random, string, websocket, _thread, time, requests, re, json

BASE_URL = "https://volafile.io"
BASE_ROOM_URL = BASE_URL + "/r/"
BASE_REST_URL = BASE_URL + "/rest/"
BASE_WS_URL = "wss://volafile.io/api/"

# Use this to interact with a room as a user
# Example: 
# r = Room("BEEPi", "ptc")
# r.postChat("Hello, world!")
# r.uploadFile("onii-chan.ogg")
# r.close()
class Room:

    # name is the room name, if none then makes a new room
    # user is your user name, if none then generates one for you
    def __init__(self, name=None, user=None):
        if name != None:
            self.name = name
        else:
            self.name = re.search(r'r/(.+?)$', requests.get(BASE_URL + "/new").url).group(1)
        if user != None:
            self.user = User(user)
        else:
            self.user = User(self._randomID(5))
        checksum, checksum2 = self._getChecksums()
        self.ws_url = BASE_WS_URL
        self.ws_url += "?rn=" + self._randomID(6)
        self.ws_url += "&EIO=3&transport=websocket"
        self.ws_url += "&t=" + str(int(time.time()*1000))
        self.ws = websocket.create_connection(self.ws_url)
        self._startPinging()
        self._subscribe(checksum, checksum2)
        self.sendCount = 1
        self.userCount = 0
        self.files = []
        self.chatLog = []

        self.ws.recv() # read out initial websocket info
        self.ws.recv() # continue reading out...

        self._listenForever()

    # Listens for new data about the room from the websocket
    # and updates Room state accordingly.
    def _listenForever(self):
        def listen():
            while self.ws.connected:
                try:
                    new_data = self.ws.recv()
                except TypeError:
                    pass
                except WebSocketConnectionClosedException:
                    self.ws = websocket.create_connection(self.ws_url)
                try:
                    self._addData(json.loads(new_data[1:]))
                except ValueError:
                    pass
        _thread.start_new_thread(listen, ())

    def _addData(self,data):
        i = 1
        while i < len(data):
            data_type = data[i][0][1][0]
            if data_type == "user_count":
                self.userCount = data[i][0][1][1]
            elif data_type == "files":
                files = data[i][0][1][1]['files']
                for f in files:
                    self.files.append(File(f[0], f[1], f[2], f[6]['user']))
            elif data_type == "chat":
                nick = data[i][0][1][1]['nick']
                msgParts = data[i][0][1][1]['message']
                files = []
                rooms = []
                msg = ""
                for part in msgParts:
                    if part['type'] == 'text':
                        msg += part['value']
                    elif part['type'] == 'file':
                        files.append(File(part['id'], part['name'], None, None))
                        msg += "@" + part['id']
                    elif part['type'] == 'room':
                        rooms.append(part['id'])
                        msg += "#" + part['id']
                    elif part['type'] == 'url':
                        msg += part['text']
                self.chatLog.append(ChatMessage(nick, msg, files, rooms))
            i += 1

    # returns list of ChatMessage objects for this room
    def getChatLog(self):
        return self.chatLog

    # returns number of users in this room
    def getUserCount(self):
        return self.userCount

    # returns list of File objects for this room.
    def getFiles(self):
        return self.files

    # Posts a msg to this room's chat
    def postChat(self, msg):
        self.ws.send('4[1337,[[0,["call",{"fn":"chat","args":["'+self.user.name+'","'+msg+'"]}]],'+str(self.sendCount)+']]')
        self.sendCount += 1

    # uploads a file with given filename to this room.
    def uploadFile(self, filename):
        f = open(filename, 'rb')
        files = {'file' : f}
        headers = {'Origin':'https://volafile.io'}
        key, server = self._generateUploadKey()
        params = {'room':self.name, 'key':key, 'filename':filename}
        return requests.post("https://" + server + "/upload", params=params, files=files, headers=headers)

    # close connection to this room
    def close(self):
        self.ws.close()

    def _subscribe(self, checksum, checksum2):
        self.ws.send('4[-1,[[0,["subscribe",{"room":"'+self.name+'","checksum":"'+checksum+'","checksum2":"'+checksum2+'","nick":"'+self.user.name+'"}]],0]]')

    # Change the name of your user.
    # Note: Must be logged out to change nick.
    def userChangeNick(self, new_nick):
        if not self.user.loggedIn:
            self.ws.send('4[15,[[0,["call",{"fn":"command","args":["'+self.user.name+'","nick","'+new_nick+'"]}]],'+str(self.sendCount)+']]')
            self.sendCount += 1
            self.user.name = new_nick

    # Attempts to log in as the current user with given password.
    def userLogin(self, password):
        if not self.user.loggedIn:
            json_resp = json.loads(requests.get(BASE_REST_URL + "login",params={"name": self.user.name, "password": password}).text)
            if json_resp.has_key('error'):
                return
            self.ws.send('4[17,[[0,["call",{"fn":"useSession","args":["'+json_resp['session']+'"]}]],'+str(self.sendCount)+']]')
            self.user.login()
            self.sendCount += 1

    # Logs your user out.
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
                try:
                    self.ws.send('3')
                except BrokenPipeError:
                    pass
        _thread.start_new_thread(pingForever, ())

    def _generateUploadKey(self):
        info = json.loads(requests.get(BASE_REST_URL + "getUploadKey", params={"name":self.user.name,"room":self.name}).text)
        return info['key'], info['server']

    def _getChecksums(self):
        text = requests.get(BASE_ROOM_URL + self.name).text
        cs2 = re.search(r'checksum2\s*:\s*"(\w+?)"',text).group(1)
        text = requests.get("https://static.volafile.io/static/js/main.js?c=" + cs2).text
        cs1 = re.search(r'config\.checksum\s*=\s*"(\w+?)"', text).group(1)

        return cs1, cs2

# Basically a struct for a chat message. self.msg holds the
# text of the message, files is a list of Files that were
# linked in the message, and rooms are a list of rooms 
# linked in the message.
class ChatMessage:

    def __init__(self, nick, msg, files, rooms):
        self.nick = nick
        self.msg = msg
        self.files = files
        self.rooms = rooms

# Basically a struct for a file's info on volafile, with an additional
# method to retrieve the file's URL.
class File:

    def __init__(self, fileID, name, fileType, uploader):
        self.fileID = fileID
        self.name = name
        self.fileType = fileType
        self.uploader = uploader

    def getURL(self):
        return BASE_URL + "/get/" + self.fileID + "/" + self.name

# Used by Room. Currently not very useful by itself.
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

