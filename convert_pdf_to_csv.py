import re
from PyPDF2 import PdfReader
import pandas as pd

PDF_PATH = 'data/pdfs/Zestawienie pociągów KM kursujących w dniach 8 II-9 III.pdf'
CSV_PATH = 'output.csv'

# Open the PDF file
with open(PDF_PATH, 'rb') as file:
    reader = PdfReader(file)

    # Extract text from each page and split into words
    words = []
    for page in reader.pages:
        text = page.extract_text()
        for line in text.split('\n'):
            # Podziel linię na słowa za pomocą spacji i przecinków
            words.append(line.split('\t'))

# Utwórz DataFrame i zapisz do pliku CSV
df = pd.DataFrame(words)
df.to_csv(CSV_PATH, header=False, index=False)


def replace_second_occurrence(pattern, replacement, string):
    count = [0]

    def replacer(match):
        count[0] += 1
        return replacement if count[0] == 2 else match.group(0)

    return re.sub(pattern, replacer, string, count=2)


def join_split_line(i, split_line, columns, condition, is_until_has):
    """
    Processes the split line, joining elements that match the condition
    until encountering the condition or reaching the end of the line.

    Args:
        i (int): Starting index for processing.
        split_line (list): List of split line elements.
        columns (list): List of columns.
        condition (str): Condition to check.
        :param is_until_has:

    Returns:
        int: Updated index.
    """
    # if is_until_has is True, then join until the condition is not found
    if is_until_has:
        for j in range(i, len(split_line)):
            # Check if the element matches the condition or is the last element in the list
            temp = split_line[j] + ' '
            while j+1 < len(split_line) and condition in split_line[j]:
                temp += split_line[j+1] + ' '
                j += 1
                i += 1
            columns.append(temp.strip())
            break
        return i + 1
    else:
        for j in range(i, len(split_line)):
            # Check if the element matches the condition or is the last element in the list
            temp = split_line[j] + ' '
            while j + 1 < len(split_line) and condition not in split_line[j+1]:
                temp += split_line[j+1] + ' '
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

        for line in file.readlines():
            # removes lowercase letters from each line
            formatted_line = "".join(char for char in line if not char.islower())

            # removes periods (.) from each line
            formatted_line = formatted_line.replace(".", "")

            # removes quotes ("") from each line
            formatted_line = formatted_line.replace('"', "")

            # Pattern to match dates in the format "08022024 - 09032024"
            formatted_line = re.sub(date_pattern, '', formatted_line)

            formatted_lines.append(formatted_line)

        # removes last two lines
        formatted_lines = formatted_lines[:-2]

        for i in range(len(formatted_lines)):
            if formatted_lines[i].endswith("PERON \n"):
                # adds space before "WARSZAWA"
                formatted_lines[i] = re.sub(r'WARSZAWA', r' WARSZAWA', formatted_lines[i])

                # splices the next line to the current line
                formatted_lines[i] = formatted_lines[i].strip('\n') + ' ' + formatted_lines[i + 1]

                # adds space after first "9" after "PERON" in formatted_lines[i]
                formatted_lines[i] = re.sub(r'PERON {2}9', r'PERON 9 ', formatted_lines[i])

                formatted_lines[i + 1] = ""

        for i in range(len(formatted_lines)):
            if formatted_lines[i].endswith("LOTNISKO \n"):
                # adds space before "WARSZAWA"
                formatted_lines[i] = re.sub(r'WARSZAWA', r' WARSZAWA', formatted_lines[i])

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
            r'\bB\b': 'Bs',
            r'\bP\b': 'Ps'
        }
        formatted_lines = [re.sub(pattern, replacement, line) for line in formatted_lines for pattern, replacement in pattern_mapping.items()]

        formatted_lines = [line for line in formatted_lines if line.strip()]

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

            formatted_lines[formatted_lines.index(line)] = formatted_line

        formatted_lines.insert(0, 'nr poc;z;odj.;do;przyj.;typ taboru;ilość;termin kursowania\n')

        with open("output_final.csv", "w", encoding='utf-8') as file:
            for line in formatted_lines:
                file.write(line)


format_converted_csv(CSV_PATH)
