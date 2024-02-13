import os
from urllib.parse import urlparse
import pysftp
import requests


def upload_to_sftp(server, username, password, source_path, target_dir):
    with pysftp.Connection(server, username=username, password=password) as sftp:
        try:
            sftp.put(source_path, target_dir + '/' + os.path.basename(source_path))
        except OSError as e:
            print(f"An error occurred while uploading the file: {e}")


def download_from_sftp(server, username, password, source_path, target_path):
    with pysftp.Connection(server, username=username, password=password) as sftp:
        sftp.get(source_path, target_path)


def download_file_from_url(url, target_dir, new_name=None):
    response = requests.get(url)
    file_name = new_name if new_name else os.path.basename(urlparse(url).path)
    target_path = os.path.join(target_dir, file_name)

    with open(target_path, 'wb') as file:
        file.write(response.content)

    return target_path
