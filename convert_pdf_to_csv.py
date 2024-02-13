import os
import re

import dotenv
from PyPDF2 import PdfReader
import pandas as pd

from sftp_actions import download_file_from_url, upload_to_sftp

dotenv.load_dotenv()

server = os.getenv('SFTP_SERVER')
port = int(os.getenv('SFTP_PORT'))
username = os.getenv('SFTP_USERNAME')
password = os.getenv('SFTP_PASSWORD')
pdf_remote_url = os.getenv('SFTP_PDFS_URL')
csv_remote_url = os.getenv('SFTP_CSVS_URL')
pdf_remote_dir = os.getenv('SFTP_PDFS_DIR')
csv_remote_dir = os.getenv('SFTP_CSVS_DIR')


PDF_IN_PATH = download_file_from_url(pdf_remote_url + '/Zestawienie pociągów KM kursujących w dniach 8 II-9 III.pdf', 'data/temp')
CSV_OUT_PATH = 'data/temp/KM_table_current.csv'


# Open the PDF file
def extract_words_from_pdf(pdf_path):
    with open(pdf_path, 'rb') as file:
        reader = PdfReader(file)
        return [word for page in reader.pages for word in page.extract_text().split('\n')]


# Convert the list of words into a DataFrame and save as a CSV file
def save_words_to_csv(words, csv_path):
    pd.DataFrame(words).to_csv(csv_path, header=False, index=False)


def replace_second_occurrence(pattern, replacement, string):
    count = [0]

    def replacer(match):
        count[0] += 1
        return replacement if count[0] == 2 else match.group(0)

    return re.sub(pattern, replacer, string, count=2)


def join_split_line(i, split_line, columns, condition, is_until_has):
    # if is_until_has is True, then join until the condition is not found
    if is_until_has:
        for j in range(i, len(split_line)):
            temp = split_line[j] + ' '
            while j + 1 < len(split_line) and condition in split_line[j]:
                temp += split_line[j + 1] + ' '
                j += 1
                i += 1
            columns.append(temp.strip())
            break
        return i + 1
    else:
        for j in range(i, len(split_line)):
            temp = split_line[j] + ' '
            while j + 1 < len(split_line) and condition not in split_line[j + 1]:
                temp += split_line[j + 1] + ' '
                j += 1
                i += 1
            columns.append(temp.strip())
            break
        return i + 1


# converted csv formatting
def format_converted_csv(csv_file):
    with open(csv_file, 'r', encoding='utf-8') as file:
        formatted_lines = []
        date_pattern = r'\d{8} - \d{8}'

        for line in file:
            # removes lowercase letters from each line
            formatted_line = "".join(char for char in line if not char.islower())

            # removes periods (.) from each line
            formatted_line = formatted_line.replace(".", "")

            # removes quotes ("") from each line
            formatted_line = formatted_line.replace('"', "")

            # Pattern to match dates in the format "08022024 - 09032024"
            formatted_line = re.sub(date_pattern, '', formatted_line)

            formatted_lines.append(formatted_line)

        for i, line in enumerate(formatted_lines):
            if line.endswith("PERON \n"):
                # adds space before "WARSZAWA"
                formatted_lines[i] = re.sub(r'WARSZAWA', r' WARSZAWA', line)

                # splices the next line to the current line
                formatted_lines[i] = formatted_lines[i].strip('\n') + ' ' + formatted_lines[i + 1]

                # adds space after first "9" after "PERON" in formatted_lines[i]
                formatted_lines[i] = re.sub(r'PERON {2}9', r'PERON 9 ', formatted_lines[i])

                formatted_lines[i + 1] = ""

        for i, line in enumerate(formatted_lines):
            if line.endswith("LOTNISKO \n"):
                # adds space before "WARSZAWA"
                formatted_lines[i] = re.sub(r'WARSZAWA', r' WARSZAWA', line)

                # splices the next line to the current line
                formatted_lines[i] = formatted_lines[i].strip('\n') + ' ' + formatted_lines[i + 1]

                # adds space after first "9" after "PERON" in formatted_lines[i]
                formatted_lines[i] = re.sub(r'LOTNISKO {2}CHOPINA', r'LOTNISKO CHOPINA ', formatted_lines[i])

                formatted_lines[i + 1] = ""

        pattern_mapping = {
            r'EN57ALKM': r'EN57ALwKM',
            r'EN57AKM1': r'EN57AKMw1',
            r'45WE': r'45WEkm',
            r'111E': r'111Eb',
        }
        # replaces patterns in formatted_lines
        for i, line in enumerate(formatted_lines):
            for pattern, replacement in pattern_mapping.items():
                formatted_lines[i] = re.sub(pattern, replacement, formatted_lines[i])

        # replaces SECOND standalone "B" with "Bs"
        formatted_lines = [replace_second_occurrence(r'\bB\b', 'Bs', line) for line in formatted_lines]

        # replaces SECOND standalone "P" with "Ps"
        formatted_lines = [replace_second_occurrence(r'\bP\b', 'Ps', line) for line in formatted_lines]

        # removes empty lines
        formatted_lines = [line for line in formatted_lines if line.strip()]

        # removes last line
        formatted_lines = formatted_lines[:-1]

        with open(csv_file, "w", encoding='utf-8') as file:
            file.write('nr poc;z;odj.;do;przyj.;typ taboru;ilość;termin kursowania\n')

            for line in formatted_lines:
                columns = []
                split_line = line.split()

                i = 0
                temp = ''

                columns.append(split_line[i])
                i += 1

                for j in range(i, len(split_line)):
                    if not split_line[j].startswith(('0', '1', '2')):
                        temp += split_line[j] + ' '
                        i += 1
                    else:
                        columns.append(temp.strip())
                        temp = ''
                        break

                columns.append(split_line[i])
                i += 1

                for j, element in enumerate(split_line[i:]):
                    if not split_line[j].startswith(('0', '1', '2')):
                        temp += split_line[j] + ' '
                        i += 1
                    else:
                        columns.append(temp.strip())
                        temp = ''
                        break

                columns.append(split_line[i])
                i += 1

                if ',' in split_line[i]:
                    i = join_split_line(i, split_line, columns, ',', True)
                else:
                    columns.append(split_line[i])
                    i += 1

                if ',' in split_line[i]:
                    i = join_split_line(i, split_line, columns, ',', True)
                else:
                    columns.append(split_line[i])
                    i += 1

                temp = ''
                for j in range(i, len(split_line)):
                    temp += split_line[j] + ' '
                columns.append(temp.strip())

                columns = [column.strip(' ').strip('\n') for column in columns]

                formatted_line = ';'.join(columns) + '\n'

                file.write(formatted_line)


words = extract_words_from_pdf(PDF_IN_PATH)
save_words_to_csv(words, CSV_OUT_PATH)
format_converted_csv(CSV_OUT_PATH)

if os.path.exists(CSV_OUT_PATH):
    upload_to_sftp(server, username, password, CSV_OUT_PATH, csv_remote_dir)
else:
    print(f"The file {CSV_OUT_PATH} does not exist.")
