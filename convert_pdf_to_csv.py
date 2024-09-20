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

# PDF_IN_PATH = download_file_from_url(pdf_remote_url + '/Zestawienie pociągów KM kursujących w dniach 12 II-9 III.pdf',
#                                      'data/pdfs')
CSV_OUT_PATH = 'data/temp/KM_table_current.csv'

TRAIN_MODELS = ['ER75', 'ER160', '45WEkm', 'EN76', 'SA135', 'SA222', 'Vt627', '111Eb', 'EU47', 'EN57wKM', 'EN57AKMw1',
                'EN57ALwKM', 'EN71KM', 'SN82']


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


def join_split_line(i, split_line, columns, condition, until_has):
    # if until_has is True, then join until the condition is not found
    if until_has:
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


def join_csv_files(source_dir, output_file_name, target_dir=None):
    if target_dir is None:
        target_dir = source_dir
    output_file = os.path.join(target_dir, output_file_name)
    csv_files = [os.path.join(source_dir, file) for file in os.listdir(source_dir) if file.endswith('.csv')]
    with open(output_file, 'w', encoding='utf-8') as file:
        file.write('nr poc;z;odj.;do;przyj.;typ taboru;ilość;termin kursowania\n')
        for csv_file in csv_files:
            with open(csv_file, 'r', encoding='utf-8') as f:
                file.write(f.read())


# converted csv formatting
def format_converted_csv(csv_file):
    formatted_lines = read_csv_file(csv_file)
    formatted_lines = initial_formatting(formatted_lines)
    formatted_lines = additional_formatting_dates(formatted_lines)
    formatted_lines = additional_formatting_station_names(formatted_lines)
    formatted_lines = additional_formatting_train_models(formatted_lines)
    formatted_lines = remove_empty_lines(formatted_lines)
    formatted_lines = separate_train_counts_from_date(formatted_lines)
    formatted_lines = remove_n_last_lines(formatted_lines, 1)
    formatted_lines = combine_columns_into_lines(formatted_lines)
    formatted_lines = final_dates_formatting_and_cleanup(formatted_lines)
    return formatted_lines


def read_csv_file(csv_file):
    with open(csv_file, 'r', encoding='utf-8') as file:
        return [line for line in file]


def initial_formatting(formatted_lines):
    """
    Function to perform initial formatting on a list of lines by removing lowercase letters, periods, double quotes,
    and date patterns in the format 'YYYY-MM-DD - YYYY-MM-DD'.

    Parameters:
    - formatted_lines: A list of strings representing the lines to be formatted.

    Returns:
    A list of strings with the specified characters and date patterns removed.
    """

    date_pattern = r'\d{4}-\d{2}-\d{2} - \d{4}-\d{2}-\d{2}'
    cleaned_lines = []
    for line in formatted_lines:
        formatted_line = re.sub(r'[a-ząćęłńóśźż.]|"', '', line)
        formatted_line = re.sub(date_pattern, '', formatted_line)
        cleaned_lines.append(formatted_line)
    return cleaned_lines


def additional_formatting_dates(formatted_lines):
    for i, line in enumerate(formatted_lines):
        # if line ends with a digit and next starts with a month in roman numerals
        if (line.endswith(('0 \n', '1 \n', '2 \n', '3 \n', '4 \n', '5 \n', '6 \n', '7 \n', '8 \n', '9 \n'))
                and re.match(r'\b[I|V|X]+\b', formatted_lines[i + 1].strip())):
            formatted_lines[i] = line + ' ' + formatted_lines[i + 1]
            formatted_lines[i + 1] = ""

    return formatted_lines


def additional_formatting_station_names(formatted_lines):
    """
    Perform additional formatting on station names in the provided list of lines.

    This function specifically looks for lines ending with "PERON \n" or "LOTNISKO \n" and applies the following changes:
    - Adds a space before "WARSZAWA" if it is found in the line.
    - Combines the current line with the next line.
    - Replaces "PERON  9" with "PERON 9 ".
    - Replaces "LOTNISKO  CHOPINA" with "LOTNISKO CHOPINA ".
    - Clears the next line after combining.

    Parameters:
    formatted_lines (list of str): The list of lines to be formatted.

    Returns:
    list of str: The formatted list of lines.
    """
    for i, line in enumerate(formatted_lines):
        if line.endswith("PERON \n"):
            line = re.sub(r'WARSZAWA', r' WARSZAWA', line)
            formatted_lines[i] = line.strip('\n') + ' ' + formatted_lines[i + 1]
            line = re.sub(r'PERON {2}9', r'PERON 9 ', formatted_lines[i])
            formatted_lines[i] = line
            formatted_lines[i + 1] = ""
        elif line.endswith("LOTNISKO \n"):
            line = re.sub(r'WARSZAWA', r' WARSZAWA', line)
            formatted_lines[i] = line.strip('\n') + ' ' + formatted_lines[i + 1]
            line = re.sub(r'LOTNISKO {2}CHOPINA', r'LOTNISKO CHOPINA ', formatted_lines[i])
            formatted_lines[i] = line
            formatted_lines[i + 1] = ""
    return formatted_lines


def additional_formatting_train_models(formatted_lines):
    """
    Perform additional formatting on train models in the provided list of lines.

    This function applies the following changes:
    - Replaces specific train model codes with their corresponding formatted versions.
    - Replaces the second occurrence of 'B' with 'Bs' in each line.
    - Replaces the second occurrence of 'P' with 'Ps' in each line.

    Parameters:
    formatted_lines (list of str): The list of lines to be formatted.

    Returns:
    list of str: The formatted list of lines.
    """
    pattern_mapping = {
        r'EN57ALKM': r'EN57ALwKM',
        r'EN57AKM1': r'EN57AKMw1',
        r'45WE': r'45WEkm',
        r'111E': r'111Eb',
    }
    for i, line in enumerate(formatted_lines):
        for pattern, replacement in pattern_mapping.items():
            formatted_lines[i] = re.sub(pattern, replacement, formatted_lines[i])
    formatted_lines = [re.sub(r'\bB\b', 'Bs', line, count=2) for line in formatted_lines]
    formatted_lines = [re.sub(r'\bP\b', 'Ps', line, count=2) for line in formatted_lines]
    return formatted_lines


def remove_empty_lines(formatted_lines):
    return [line for line in formatted_lines if line.strip()]


def separate_train_counts_from_date(formatted_lines):
    """
    Separate train counts from dates in the provided list of formatted lines.

    This function iterates over each line and splits it into words. If a word matches a train model
    from the TRAIN_MODELS list and the next word has a length of 2 or 3, it inserts a space in the next word.

    Parameters:
    formatted_lines (list of str): The list of lines to be processed.

    Returns:
    list of str: The formatted list of lines with train counts separated from dates.
    """
    for i, line in enumerate(formatted_lines):
        split_line = line.split(' ')
        numbers_separated = False
        for j in range(len(split_line)):
            if numbers_separated:
                break

            if split_line[j].strip(",. ") in TRAIN_MODELS:
                for k in range(j + 1, len(split_line)):
                    if '-' in split_line[k]:
                        split_by_dash = split_line[k].split('-')
                        if len(split_by_dash[0]) == 2 or len(split_by_dash[0]) == 3:
                            split_line[k] = split_line[k][0] + ' ' + split_line[k][1:]
                            numbers_separated = True
                            break

        formatted_lines[i] = ' '.join(split_line)
    return formatted_lines


def remove_n_last_lines(formatted_lines, n):
    return formatted_lines[:-n]


def combine_columns_into_lines(formatted_lines):
    """
    Combine columns into lines for the provided list of formatted lines.

    This function processes each line by splitting it into columns and then combining
    the columns into a single line separated by semicolons. It ensures that columns
    starting with digits (0, 1, 2) - time columns, are treated as separate columns.

    Parameters:
    formatted_lines (list of str): The list of formatted lines to be processed.

    Returns:
    list of str: The list of combined lines.
    """
    combined_lines = []
    for line in formatted_lines:
        count = 0
        count += 1

        columns = line.split()
        combined_columns = [columns[0]]
        combined_columns_counter = 1
        i = 1
        while combined_columns_counter < 5:
            temp = ''
            while i < len(columns) and not columns[i].startswith(('0', '1', '2')):
                temp += columns[i] + ' '
                i += 1

            combined_columns.append(temp.strip())
            combined_columns_counter += 1

            if i < len(columns):
                combined_columns.append(columns[i])
                combined_columns_counter += 1
                i += 1

        # combine multi column train models
        if columns[i].startswith(('111Eb', 'EU47')):
            # combine until the next column is a digit
            for j in range(i, len(columns)):
                temp = columns[j] + ' '
                while j + 1 < len(columns) and not columns[j + 1].startswith(
                        ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9')):
                    temp += columns[j + 1] + ' '
                    j += 1
                    i += 1
                combined_columns.append(temp.strip())
                break
        else:
            combined_columns.append(columns[i])
        i += 1

        # combine multi column train counts
        if columns[i].endswith(','):
            for j in range(i, len(columns)):
                temp = columns[j] + ' '
                while j + 1 < len(columns) and columns[j + 1].endswith(','):
                    temp += columns[j + 1] + ' '
                    j += 1
                    i += 1
                temp += columns[j + 1]
                i += 1

                combined_columns.append(temp.strip())
                break
        else:
            combined_columns.append(columns[i])
        i += 1

        dates = ''
        while i < len(columns):
            dates += columns[i] + ' '
            i += 1

        combined_columns.append(dates.strip())

        if not combined_columns[-1] == '':
            combined_lines.append(';'.join(combined_columns) + '\n')

    return combined_lines


def write_csv_file(formatted_lines, csv_file):
    with open(csv_file, 'w', encoding='utf-8') as file:
        file.writelines(formatted_lines)


# convert every pdf file in the data/pdfs directory to a csv file
def convert_pdfs_to_csvs(source_dir, target_dir):
    for file in os.listdir(source_dir):
        if file.endswith('.pdf'):
            pdf_path = os.path.join(source_dir, file)
            words = extract_words_from_pdf(pdf_path)
            csv_path = os.path.join(target_dir, file.replace('.pdf', '.csv'))
            save_words_to_csv(words, csv_path)
            format_converted_csv(csv_path)
            write_csv_file(format_converted_csv(csv_path), csv_path)
    join_csv_files(source_dir, 'KM_table_current.csv')


def upload_converted_csv_to_sftp(server, username, password, source_path, target_dir):
    if os.path.exists(CSV_OUT_PATH):
        upload_to_sftp(server, username, password, CSV_OUT_PATH, csv_remote_dir)
    else:
        print(f"The file {CSV_OUT_PATH} does not exist.")


def convert_and_upload_csvs_to_sftp():
    convert_pdfs_to_csvs('data/pdfs', 'data/temp')
    # upload_converted_csv_to_sftp(server, username, password, CSV_OUT_PATH, csv_remote_dir)


if __name__ == '__main__':
    convert_pdfs_to_csvs('data/pdfs', 'data/temp')
