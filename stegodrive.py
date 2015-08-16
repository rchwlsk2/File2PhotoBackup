import gdata.photos.service
import gdata.media
import gdata.geo
import gdata.gauth

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



####################
# CONSTANTS
####################

email = "stallionsunite@gmail.com"
password = "StallionsFTW"
username = "stallionsunite"

secret = "config/client_secret_108601353483-fnbcbps0b9iunmaufrtvveft5o6ttb86.apps.googleusercontent.com.json"
credentials = "config/creds.txt"

albumName = "StenoDrive-DoNotDelete"
folderName = "files"
tempName = "temp"
config = "config/config.json"
dbName = "config/filemap.db"



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

        outname = convertPath(event.src_path) + '.jpg'
        outpath = os.path.join(tempName, outname)
        encode(event.src_path, outpath)

        albums = self.client.GetUserFeed()
        for album in albums.entry:
            if album.title.text == albumName:
                album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
                photo = self.client.InsertPhotoSimple(album_url, outname, 'StenoDrive: ' + outname, outpath, content_type='image/jpeg')

        os.remove(outpath)
        return

    def on_deleted(self, event):
        print 'File deleted', event.src_path
        if os.path.isfile(event.src_path):
            photoname = convertPath(event.src_path) + '.jpg'

            albums = self.client.GetUserFeed()
            for album in albums.entry:
                if album.title.text == albumName:
                    album_url = '/data/feed/api/user/default/albumid/%s' % album.gphoto_id.text
                    photos = self.client.GetFeed(album_url + '?kind=photo')

                    for photo in photos.entry:
                        if photo.title.text == photoname:
                            self.client.Delete(photo)
                            return

        # TODO: Add support for deleting folders (delete all files inside)
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

        photoname = convertPath(event.src_path) + '.jpg'
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
                break

        os.remove(outpath)
        return

    def on_moved(self, event):
        print 'File moved', event.src_path, event.dest_path
        oldname = convertPath(event.src_path) + '.jpg'
        newname = convertPath(event.dest_path) + '.jpg'

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



####################
# FOLDER MANAGEMENT
####################

# Adds all of the files in the folders to the db
def syncFolders(client):
    rows = ['files']
    files = []
    for folder in rows:
        for root, directories, filenames in os.walk(folder):
            for filename in filenames:
                name = os.path.join(root,filename)
                files.append(name)
                addFile(client, name)

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
# METADATA
####################

def remove_metadata(image):
    im = Image.open(image)
    im.save("NOMETA"+image)



####################
# MAIN LOOP
####################

def main():
    client = OAuth2Login(secret, credentials, email)
    event_handler = StenoDriveHandler(client)
    observer = Observer()

    observer.schedule(event_handler, path=folderName, recursive=True)
    observer.start()

    print 'Initializing photo album...'
    didMakeAlbum = initializeAlbum(client)
    if not didMakeAlbum:
        print 'Album already exists! Did not create a new one'

    syncFolders(client)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == '__main__':
    main()
