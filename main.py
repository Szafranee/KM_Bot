import os

from convert_pdf_to_csv import convert_pdfs_to_csvs
from get_newest_files import download_and_leave_newest_pdfs
from sftp_actions import move_old_files_to_sftp

MAIN_URL = "https://www.mazowieckie.com.pl/pl/kategoria/rozklady-jazdy"
server = os.getenv('SFTP_SERVER')
port = int(os.getenv('SFTP_PORT'))
username = os.getenv('SFTP_USERNAME')
password = os.getenv('SFTP_PASSWORD')
old_data_remote_dir = os.getenv('SFTP_OLD_DIR')
old_data_dir = os.getenv('OLD_DATA_DIR')

if __name__ == '__main__':
    download_and_leave_newest_pdfs(MAIN_URL)
    convert_pdfs_to_csvs()
    move_old_files_to_sftp(server, username, password, old_data_dir, old_data_remote_dir)


