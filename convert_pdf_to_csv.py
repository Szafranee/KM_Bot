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

    # removes empty lines
    formatted_lines = [line for line in formatted_lines if line.strip()]

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

    with open("output_2.csv", "w", encoding='utf-8') as file:
        file.writelines(formatted_lines)


format_converted_csv(CSV_PATH)
