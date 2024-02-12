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

    Returns:
        int: Updated index.
        :param is_until_has:
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
        lines = file.readlines()

    # removes lowercase letters from each line
    formatted_lines = ["".join(char for char in line if not char.islower()) for line in lines]

    # removes periods (.) from each line
    formatted_lines = [line.replace(".", "") for line in formatted_lines]

    # removes quotes ("") from each line
    formatted_lines = [line.replace('"', "") for line in formatted_lines]

    # Pattern to match dates in the format "08022024 - 09032024"
    pattern = r'\d{8} - \d{8}'
    formatted_lines = [re.sub(pattern, '', line) for line in formatted_lines]

    # removes last 2 lines
    formatted_lines = formatted_lines[:-2]

    # if line ens in "PERON" then add a space after it and add the next line to it
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

    # small letters fixes
    # replaces all "EN57ALKM" to "EN57ALwKM"
    formatted_lines = [re.sub(r'EN57ALKM', r'EN57ALwKM', line) for line in formatted_lines]

    # replaces all "EN57AKM1" to "EN57AKMw1"
    formatted_lines = [re.sub(r'EN57AKM1', r'EN57AKMw1', line) for line in formatted_lines]

    # replaces all "45WE" to "45WEkm"
    formatted_lines = [re.sub(r'45WE', r'45WEkm', line) for line in formatted_lines]

    # replaces all "111E" to "111Eb"
    formatted_lines = [re.sub(r'111E', r'111Eb', line) for line in formatted_lines]

    # replaces SECOND standalone "B" with "Bs"
    formatted_lines = [replace_second_occurrence(r'\bB\b', 'Bs', line) for line in formatted_lines]

    # replaces SECOND standalone "P" with "Ps"
    formatted_lines = [replace_second_occurrence(r'\bP\b', 'Ps', line) for line in formatted_lines]

    # removes empty lines
    formatted_lines = [line for line in formatted_lines if line.strip()]

    for line in formatted_lines:
        # Split the line into columns
        columns = []
        split_line = line.split(' ')
        i = 0
        temp = ''

        # add first column
        columns.append(split_line[i])
        i += 1

        # add second column
        for j in range(i, len(split_line)):
            if not split_line[j].startswith(('0', '1', '2')):
                temp += split_line[j] + ' '
                i += 1
            else:
                columns.append(temp.strip())
                temp = ''
                break

        # add third column
        columns.append(split_line[i])
        i += 1

        # add fourth column
        for j in range(i, len(split_line)):
            if not split_line[j].startswith(('0', '1', '2')):
                temp += split_line[j] + ' '
                i += 1
            else:
                columns.append(temp.strip())
                temp = ''
                break

        # add fifth column
        columns.append(split_line[i])
        i += 1

        # add sixth column
        if ',' in split_line[i]:
            i = join_split_line(i, split_line, columns, ',', True)
        else:
            columns.append(split_line[i])
            i += 1

        # add seventh column
        if ',' in split_line[i]:
            i = join_split_line(i, split_line, columns, ',', True)
        else:
            columns.append(split_line[i])
            i += 1

        # add seventh column
        temp = ''
        for j in range(i, len(split_line)):
            temp += split_line[j] + ' '
        columns.append(temp.strip())

        columns = [column.strip(' ').strip('\n') for column in columns]

        formatted_line = ';'.join(columns) + '\n'

        # replace the current line with the formatted line
        formatted_lines[formatted_lines.index(line)] = formatted_line

    # add headers
    formatted_lines.insert(0, 'nr poc;z;odj.;do;przyj.;typ taboru;ilość;termin kursowania\n')

    with open("output_final.csv", "w", encoding='utf-8') as file:
        file.writelines(formatted_lines)


format_converted_csv(CSV_PATH)
