import os
import posixpath
import pysftp


def upload_to_sftp(server, username, password, source_path, target_dir):
    with pysftp.Connection(server, username=username, password=password) as sftp:
        try:
            sftp.put(source_path, posixpath.join(target_dir, os.path.basename(source_path)))
        except OSError as e:
            print(f"An error occurred while uploading the file: {e}")


# def download_from_sftp(server, username, password, source_path, target_path):
#     ensure_dir_exists(os.path.dirname(target_path))
#     with pysftp.Connection(server, username=username, password=password) as sftp:
#         sftp.get(source_path, target_path)


# def download_file_from_url(url, target_dir, new_name=None):
#     ensure_dir_exists(target_dir)
#     response = requests.get(url)
#     file_name = new_name if new_name else os.path.basename(urlparse(url).path)
#     target_path = os.path.join(target_dir, file_name)
#
#     with open(target_path, 'wb') as file:
#         file.write(response.content)
#
#     return target_path

# TODO: Add host key manually
def move_old_files_to_sftp(server, username, password, source_dir, target_dir):
    print("=================Moving old files to SFTP===================")
    # if source dir is empty, do nothing
    if not os.listdir(source_dir):
        print(f"Source directory {source_dir} is empty. No files to upload.")
        print("===========================================================")
        return

    # set the target directory path so that it is not overwritten
    target_dir_path = target_dir

    with pysftp.Connection(server, username=username, password=password) as sftp:
        # if the target directory does not exist, create it
        ensure_sftp_dir_exists(sftp, target_dir_path)

        print(f"Uploading files from {source_dir} to {target_dir}")
        for file in os.listdir(source_dir):
            file_format = file.split('.')[-1]
            target_dir = target_dir_path

            if os.path.isfile(os.path.join(source_dir, file)):
                try:
                    target_dir = posixpath.join(target_dir, file_format)

                    # if the target directory does not exist, create it
                    ensure_sftp_dir_exists(sftp, target_dir)

                    sftp.put(os.path.join(source_dir, file), posixpath.join(target_dir, file))
                    os.remove(os.path.join(source_dir, file))
                except OSError as e:
                    print(f"An error occurred while uploading the file: {e}")
        print("All files uploaded successfully")
    print("===========================================================")


def ensure_dir_exists(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)


def ensure_sftp_dir_exists(sftp, directory):
    if not sftp.exists(directory):
        sftp.mkdir(directory)
