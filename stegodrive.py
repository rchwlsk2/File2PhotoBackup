import gdata.photos.service
import gdata.media
import gdata.geo
import gdata.gauth

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from datetime import datetime, timedelta
from oauth2client.file import Storage
from oauth2client.client import flow_from_clientsecrets

import webbrowser
import urllib
import httplib2
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import sqlite3 as sql
from PIL import Image
from scipy.misc import fromimage
import numpy as np
import sys
import os
import math
import time
import json
import shutil
import zipfile



####################
# CONSTANTS
####################

email = ""
password = ""

secret = "config/client_secret_108601353483-fnbcbps0b9iunmaufrtvveft5o6ttb86.apps.googleusercontent.com.json"
credentials = "config/creds.txt"

albumName = "StegoDrive-DoNotDelete"
folderName = "files"
tempName = "temp"
config = "config/config.json"
dbName = "config/revisions.json"



####################
# EVENT HANDLER
####################

class StenoDriveHandler(FileSystemEventHandler):

    def __init__(self, client):
        self.client = client

    def on_created(self, event):
        print 'File created', event.src_path
        if os.path.isdir(event.src_path) or event.src_path.endswith('.DS_Store'):
            return

        outname = convertPath(event.src_path) + '.png'
        outpath = os.path.join(tempName, outname)
        encode(event.src_path, outpath)

        albums = self.client.GetUserFeed()
        for album in albums.entry:
            if album.title.text == albumName:
                album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
                photo = self.client.InsertPhotoSimple(album_url, outname, 'StenoDrive: ' + outname, outpath, content_type='image/jpeg')

                if not photo.media.keywords:
                    photo.media.keywords = gdata.media.Keywords()
                photo.media.keywords.text = str(0)
                self.client.UpdatePhotoMetadata(photo)

                addToDb(outname, 0, True)

        os.remove(outpath)
        return

    def on_deleted(self, event):
        print 'File deleted', event.src_path
        if not os.path.isdir(event.src_path):
            photoname = convertPath(event.src_path) + '.png'

            albums = self.client.GetUserFeed()
            for album in albums.entry:
                if album.title.text == albumName:
                    album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
                    photos = self.client.GetFeed(album_url + '?kind=photo')

                    for photo in photos.entry:
                        if photo.title.text == photoname:
                            self.client.Delete(photo)
                            delFromDb(photoname)
                            return

        else:
            photostart = convertPath(event.src_path)

            albums = self.client.GetUserFeed()
            for album in albums.entry:
                if album.title.text == albumName:
                    album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
                    photos = self.client.GetFeed(album_url + '?kind=photo')

                    for photo in photos.entry:
                        if photo.title.text.startswith(photostart):
                            self.client.Delete(photo)

        return

    def on_modified(self, event):
        print 'File modified', event.src_path
        if os.path.isdir(event.src_path) or event.src_path.endswith('.DS_Store'):
            return

        photoname = convertPath(event.src_path) + '.png'
        outpath = os.path.join(tempName, photoname)
        encode(event.src_path, outpath)

        albums = self.client.GetUserFeed()
        for album in albums.entry:
            if album.title.text == albumName:
                album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
                photos = self.client.GetFeed(album_url + '?kind=photo')

                for photo in photos.entry:
                    if photo.title.text == photoname:
                        self.client.Delete(photo)
                        break

                photo = self.client.InsertPhotoSimple(album_url, photoname, 'StenoDrive: ' + photoname, outpath, content_type='image/jpeg')

                rev = getFromDb(photoname)
                addToDb(photoname, rev + 1, False)

                if not photo.media.keywords:
                    photo.media.keywords = gdata.media.Keywords()
                photo.media.keywords.text = str(rev + 1)
                self.client.UpdatePhotoMetadata(photo)

                break

        os.remove(outpath)
        return

    def on_moved(self, event):
        print 'File moved', event.src_path, event.dest_path
        oldname = convertPath(event.src_path) + '.png'
        newname = convertPath(event.dest_path) + '.png'

        albums = self.client.GetUserFeed()
        for album in albums.entry:
            if album.title.text == albumName:
                album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
                photos = self.client.GetFeed(album_url + '?kind=photo')

                for photo in photos.entry:
                    if photo.title.text == oldname:
                        photo.title.text = newname
                        photo.summary.text = 'StenoDrive: ' + newname
                        self.client.UpdatePhotoMetadata(photo)
                        return
        return



#####################
# INITIALIZATION
#####################

# Logs into picasa for photo management
def OAuth2Login(client_secrets, credential_store, email):
    scope='https://picasaweb.google.com/data/'
    user_agent='StenoDrive'

    storage = Storage(credential_store)
    credentials = storage.get()
    if credentials is None or credentials.invalid:
        flow = flow_from_clientsecrets(client_secrets, scope=scope, redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        uri = flow.step1_get_authorize_url()
        webbrowser.open(uri)
        code = raw_input('Enter the authentication code: ').strip()
        credentials = flow.step2_exchange(code)
        storage.put(credentials)

    if (credentials.token_expiry - datetime.utcnow()) < timedelta(minutes=5):
        http = httplib2.Http()
        http = credentials.authorize(http)
        credentials.refresh(http)

    gd_client = gdata.photos.service.PhotosService(source=user_agent,
                                               email=email,
                                               additional_headers={'Authorization' : 'Bearer %s' % credentials.access_token})

    return gd_client

# Creates the album on Photos if it does not exist
def initializeAlbum(client):
    if not doesAlbumExist(client, albumName):
        album = client.InsertAlbum(title=albumName, summary='Album for StenoDrive. Do not delete if contains sensitive files. Also do not upload sensitive files.')
        return True
    return False

# Determines whether an album exists
def doesAlbumExist(client, albumName):
    albums = client.GetUserFeed()
    for album in albums.entry:
        if album.title.text == albumName:
            return True
    return False

def initDb():
    if not os.path.exists(dbName):
        with open(dbName, 'w') as data_file:
            json.dump({}, data_file)
        return True
    return False

def addToDb(key, val, existsCheck):
    with open(dbName, 'r') as data_file:
        try:
            data = json.load(data_file)
        except ValueError:
            data = {}

    if existsCheck:
        if key not in data:
            data[key] = val
    else:
        data[key] = val

    with open(dbName, 'w') as data_file:
        json.dump(data, data_file)

def delFromDb(key):
    with open(dbName, 'r') as data_file:
        try:
            data = json.load(data_file)
        except ValueError:
            data = {}

    if key in data:
        del data[key]

    with open(dbName, 'w') as data_file:
        json.dump(data, data_file)

def getFromDb(key):
    with open(dbName, 'r') as data_file:
        try:
            data = json.load(data_file)
        except ValueError:
            data = {}

    if key in data:
        return data[key]

    return -1

def compareRevisions(client):
    albums = client.GetUserFeed()
    for album in albums.entry:
        if album.title.text == albumName:
            album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
            photos = client.GetFeed(album_url + '?kind=photo')

            for photo in photos.entry:
                tags = client.GetFeed('/data/feed/api/user/default/albumid/%s/photoid/%s?kind=tag' % (album.gphoto_id.text, photo.gphoto_id.text))
                for entry in tags.entry:
                    if getFromDb(photo.title.text) < int(entry.title.text):
                        downSync(client)
                        return
                    elif getFromDb(photo.title.text) > int(entry.title.text):
                        upSync(client, photo, entry)

    return

def updateLocalDb(client):
    albums = client.GetUserFeed()
    for album in albums.entry:
        if album.title.text == albumName:
            album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
            photos = client.GetFeed(album_url + '?kind=photo')

            for photo in photos.entry:
                tags = client.GetFeed('/data/feed/api/user/default/albumid/%s/photoid/%s?kind=tag' % (album.gphoto_id.text, photo.gphoto_id.text))
                for entry in tags.entry:
                      addToDb(photo.title.text, int(entry.title.text), False)

    return


####################
# FOLDER MANAGEMENT
####################

# Adds all of the files in the folders to the db
def downSync(client):
    url = getZipUrl()
    downloadFromUrl(url)
    resolveEncodedFiles()
    updateLocalDb(client)
    return

def upSync(client, photo, rev):
    sourceFile = devertPath(photo.title.text)
    tempPath = os.path.join(tempName, sourceFile[-1])
    encode('/'.join(sourceFile), tempPath)

    albums = client.GetUserFeed()
    for album in albums.entry:
        if album.title.text == albumName:
            album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
            photo = client.InsertPhotoSimple(album_url, photo.title.text, 'StenoDrive: ' + photo.title.text, tempPath, content_type='image/jpeg')

            if not photo.media.keywords:
                photo.media.keywords = gdata.media.Keywords()
            photo.media.keywords.text = str(rev)
            client.UpdatePhotoMetadata(photo)

    os.remove(tempPath)
    return


#####################
# FILE MANAGEMENT
#####################

# Converts path to google photos usable name
def convertPath(path):
    pathlist = path.split('/')
    safepath = '#'.join(pathlist)
    safepath += '#'
    return safepath

# Changes a converted path to a list that can be followed like a directory traverse
def devertPath(path):
    pathlist = path.split('#')
    return pathlist[:-1]

# Gets all photos associated with a file and assembles it
def getFile(client, filename):
    return

# Turns a file into photos for uploadage
def addFile(client, filename):
    return



######################
# ENCODE
######################

def encode(filename, output_name):
    f = open(filename, "rb")

    size = get_filesize(f)
    rez = get_filerez(size)
    data = np.zeros((rez,rez,4), dtype=np.uint8)
    create_header(size, data)
    fill_data(f, data)

    f.close

    save_img(data, output_name)

def get_filesize(f):
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0, 0)
    return size

def get_filerez(size):
    size_with_header = size + 1
    size_with_header = size_with_header / 4.0
    return math.ceil(math.sqrt(size_with_header))

def create_header(size, data):
    binary_size = bin(size)[2:]
    while len(binary_size) < 32:
        binary_size = "0" + binary_size

    c = 0
    for size_chunk in range(0, len(binary_size), 8):
        data[0][0][c] = binary_size[size_chunk:size_chunk+8]
        c+=1

def fill_data(f, data):
    byte = f.read(1)

    rez = len(data)
    for index, value in np.ndenumerate(data):
        if index[0] != 0 or index[1] != 0:
            if byte != "":
                data[index] = ord(byte)
                byte = f.read(1)

def save_img(data, output_name):
    img = Image.fromarray(data, 'RGBA')
    img.save(output_name)



######################
# DECODE
######################

def decode(image, output):
    im = Image.open(image)
    im_array = fromimage(im)
    size = get_header_size(im_array)
    byte_array = get_bytes_from_image_array(im_array, size)
    save_file(byte_array, output)


def get_header_size(im_array):
    rgba = im_array[0][0]
    size = ""
    for i in rgba:
        val = str(i)
        while len(val) < 3:
            val = "0" + val
        size += val
    return size

def get_bytes_from_image_array(array, size):
    bytes = bytearray()

    c = 0
    for index, value in np.ndenumerate(array):
        if index[0] != 0 or index[1] != 0:
            if c < size:
                bytes.append(value)
                c+=1

    return bytes

def save_file(byte_array, output):
    f = open(output, "wb")
    f.write(byte_array)
    f.close



####################
# Jank
####################

def getZipUrl():
    driver = webdriver.Firefox()
    driver.get("https://photos.google.com/login")
    emaild = driver.find_element_by_id("Email")
    emaild.send_keys(email)
    emaild.send_keys(Keys.RETURN)
    try:
        passwd = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "Passwd"))
            )
    finally:
        passwd = driver.find_element_by_id("Passwd")
        passwd.send_keys(password)
        passwd.send_keys(Keys.RETURN)

    try:
        on_page = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "aria-label-appbar-title"))
            )
    finally:
        driver.get("https://photos.google.com/collections")
        time.sleep(1)

    try:
        loaded_collections = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "_ij"))
        )
    finally:
        src = driver.page_source
        position = src.find("data:function(){return ")
        position += len("data:function(){return ")

        stack = [src[position]]
        albums_source = "["

        while len(stack) > 0:
            position += 1
            if src[position] == '[':
                stack.append('[')
            elif src[position] == ']':
                stack.pop()
            albums_source += src[position]

        j = json.loads(albums_source)
        j = j[0]
        for album in j:
            name = album[2].itervalues().next()[1]
            if name == "StegoDrive-DoNotDelete":
                driver.get("https://photos.google.com/album/" + album[0])
                time.sleep(1)

        src = driver.page_source
        position = src.find("https://video.googleusercontent.com/")
        position += len("https://video.googleusercontent.com/")
        end_pos = src.find("\"", position)

        zip_url = "https://video.googleusercontent.com/" + src[position:end_pos]
        driver.quit()
        return zip_url

def downloadFromUrl(url):
    (filename, headers) = urllib.urlretrieve(url)

    fn = headers.dict['content-disposition']
    fn = fn.split('filename=')[1];
    fn = fn.strip('"')

    zipname = os.path.join(tempName, fn)
    shutil.move(filename, zipname)

    if zipname.endswith('zip'):
        with zipfile.ZipFile(zipname, "r") as z:
            z.extractall(tempName)
        os.remove(zipname)

    return

def resolveEncodedFiles():
    files = os.listdir(tempName)
    print files
    for filename in files:
        if filename == '.DS_Store':
            continue
        longpath = devertPath(filename)
        filename = os.path.join(tempName, filename)

        builtpath = None
        for directory in longpath[:-1]:
            if builtpath is None:
                builtpath = directory
            else:
                builtpath = os.path.join(builtpath, directory)

            if not os.path.exists(builtpath):
                os.makedirs(builtpath)

        filepath = '/'.join(longpath)
        decode(filename, filepath)
        os.remove(filename)



####################
# MAIN LOOP
####################

if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit("Usage: python stegodrive.py <email> <password>")

    if not os.path.exists(tempName):
        os.makedirs(tempName)

    email = sys.argv[1]
    password = sys.argv[2]

    client = OAuth2Login(secret, credentials, email)

    print 'Initializing photo album...'
    didMakeAlbum = initializeAlbum(client)
    if not didMakeAlbum:
        print 'Album already exists! Did not create a new one'
    else:
        print 'Album created :)'

    print 'Initializing JSON database...'
    didMakeJson = initDb()
    if not didMakeJson:
        print 'DB already exists! Did not create a new one'
    else:
        print 'DB created :)'

    if len(sys.argv) == 4:
        if sys.argv[3] == '-u':
            downSync(client)
            sys.exit(0)

    event_handler = StenoDriveHandler(client)
    observer = Observer()

    if not os.path.exists(folderName):
        os.makedirs(folderName)
    observer.schedule(event_handler, path=folderName, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(5)
            compareRevisions(client)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
