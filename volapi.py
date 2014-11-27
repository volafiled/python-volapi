
import os
import random, string, websocket, _thread, time, re, json
import requests as _requests
from .multipart import Data

requests = _requests.Session()

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
        self.connected = True
        self._subscribe(checksum, checksum2)
        self.sendCount = 1
        self.userCount = 0
        self.files = []
        self.chatLog = []
        self.maxID = '0'

        self._listenForever()

    # Listens for new data about the room from the websocket
    # and updates Room state accordingly.
    def _listenForever(self):
        def listen():
            last_time = time.time()
            while self.ws.connected:
                new_data = self.ws.recv()
                if new_data[0] == '1':
                    print("Volafile has requested this connection close.")
                    self.close()
                elif new_data[0] == '4':
                    json_data = json.loads(new_data[1:])
                    if type(json_data) is list and len(json_data) > 1:
                        self.maxID = str(json_data[1][-1])
                        self._addData(json_data)
                else:
                    pass # not implemented

                # send max msg ID seen every 10 seconds
                if time.time() > last_time + 10:
                    self.ws.send("4[" + self.maxID + "]")
                    last_time = time.time()

        def ping():
            while self.ws.connected:
                self.ws.send('2')
                time.sleep(20)

        _thread.start_new_thread(listen, ())
        _thread.start_new_thread(ping, ())

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
        msg = self._escape(msg)
        self.ws.send('4['+self.maxID+',[[0,["call",{"fn":"chat","args":["'+self.user.name+'","'+msg+'"]}]],'+str(self.sendCount)+']]')
        self.sendCount += 1

    # uploads a file with given filename to this room.
    def uploadFile(self, filename, uploadAs=None):
        f = open(filename, 'rb', buffering=512*1024)
        filename = self._escape(uploadAs or os.path.split(filename)[1])
        files = Data({'file' : {"name": filename, "value": f}})
        headers = {'Origin':'https://volafile.io'}
        headers.update(files.headers)
        key, server = self._generateUploadKey()
        params = {'room':self.name, 'key':key, 'filename':filename}
        return requests.post("https://" + server + "/upload", params=params, data=files, headers=headers)

    # close connection to this room
    def close(self):
        self.ws.close()
        self.connected = False

    def _subscribe(self, checksum, checksum2):
        self.ws.send('4[-1,[[0,["subscribe",{"room":"'+self.name+'","checksum":"'+checksum+'","checksum2":"'+checksum2+'","nick":"'+self.user.name+'"}]],0]]')

    # Change the name of your user.
    # Note: Must be logged out to change nick.
    def userChangeNick(self, new_nick):
        if not self.user.loggedIn:
            new_nick = self._escape(new_nick)
            self.ws.send('4['+self.maxID+',[[0,["call",{"fn":"command","args":["'+self.user.name+'","nick","'+new_nick+'"]}]],'+str(self.sendCount)+']]')
            self.sendCount += 1
            self.user.name = new_nick

    # Attempts to log in as the current user with given password.
    def userLogin(self, password):
        if not self.user.loggedIn:
            json_resp = json.loads(requests.get(BASE_REST_URL + "login",params={"name": self.user.name, "password": password}).text)
            if 'error' in json_resp.keys():
                raise IOError("Login unsuccessful: {}", json_resp["error"])
            msg = '4['+self.maxID+',[[0,["call",{"fn":"useSession","args":["'+json_resp['session']+'"]}]],'+str(self.sendCount)+']]'
            requests.cookies.update({"session": json_resp["session"]})
            self.ws.send(msg)
            self.user.login()
            self.sendCount += 1

    # Logs your user out.
    def userLogout(self):
        if self.user.loggedIn:
            self.ws.send('4['+self.maxID+',[[0,["call",{"fn":"logout","args":[]}]],'+str(self.sendCount)+']]')
            self.user.logout()
            self.sendCount += 1

    def _randomID(self, n):
        return ''.join(random.choice(string.ascii_letters+string.digits) for _ in range(n))

    def _generateUploadKey(self):
        info = json.loads(requests.get(BASE_REST_URL + "getUploadKey", params={"name":self.user.name,"room":self.name}).text)
        return info['key'], info['server']

    def _escape(self, string):
        return string.replace('\\', '\\\\').replace('"', '\\"')

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

