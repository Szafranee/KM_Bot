import os
import posixpath
from urllib.parse import urlparse

import paramiko
import pysftp
import requests


def ensure_dir_exists(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)


def upload_to_sftp(server, username, password, source_path, target_dir):
    with pysftp.Connection(server, username=username, password=password) as sftp:
        try:
            sftp.put(source_path, posixpath.join(target_dir, os.path.basename(source_path)))
        except OSError as e:
            print(f"An error occurred while uploading the file: {e}")


def download_from_sftp(server, username, password, source_path, target_path):
    ensure_dir_exists(os.path.dirname(target_path))
    with pysftp.Connection(server, username=username, password=password) as sftp:
        sftp.get(source_path, target_path)


def download_file_from_url(url, target_dir, new_name=None):
    ensure_dir_exists(target_dir)
    response = requests.get(url)
    file_name = new_name if new_name else os.path.basename(urlparse(url).path)
    target_path = os.path.join(target_dir, file_name)

    with open(target_path, 'wb') as file:
        file.write(response.content)

    return target_path


def sync_files_to_sftp(server, username, password, source_dir, sftp_target_dir, current_pdfs):
    transport = paramiko.Transport((server, 22))
    transport.connect(username=username, password=password)

    sftp = paramiko.SFTPClient.from_transport(transport)

    try:
        for file in os.listdir(source_dir):
            sftp.put(posixpath.join(source_dir, file), posixpath.join(sftp_target_dir, file))
    except OSError as e:
        print(f"An error occurred while uploading the files: {e}")

    # After files have been uploaded, move them to the 'old' directory on the SFTP server
    old_dir = '/www/KM_Bot/data/old'
    try:
        sftp.listdir(old_dir)
    except IOError:
        sftp.mkdir(old_dir)  # Create the old directory if it doesn't exist

    try:
        files = sftp.listdir(sftp_target_dir)
    except IOError:
        print(f"The directory {sftp_target_dir} does not exist on the SFTP server.")
        files = []

    # If a file is in the source_dir but not in the current_pdfs list, it is not a "newest one"
    non_current_files = [file for file in files if file not in current_pdfs]

    for file in non_current_files:
        try:
            print(posixpath.join(sftp_target_dir, file))
            print(posixpath.join(old_dir, file))
            sftp.rename(posixpath.join(sftp_target_dir, file), posixpath.join(old_dir, file))
        except OSError as e:
            print(f"An error occurred while renaming the file: {e}")

    sftp.close()
    transport.close()
