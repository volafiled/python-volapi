
BASE_URL = "https://volafile.io/rest/"

class Room:

    def __init__(self, name=None):
        pass

    def getFiles(self):
        pass

    def getChat(self):
        pass

    def uploadFile(self):
        pass

class Chat:

    def __init__(self, room):
        pass

    def postMessage(self):
        pass

    def startLogging(self):
        pass

    def stopLogging(self):
        pass

class File:

    def __init__(self):
        pass

    def getInfo(self):
        pass

class User:

    def __init__(self, name):
        pass

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

