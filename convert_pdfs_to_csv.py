import csv
import os
import re
import time

import pymupdf


# TODO:
# 1. Date convertion

def extract_table_from_text(text: str) -> list:
    """
    Extracts table rows from the provided page text by processing each line.
    Skips lines that contain any of the specified keywords as separate words.

    The keywords "odj." and "przyj." are handled with an optional period,
    so both "odj" and "odj." (and similarly for "przyj") will be matched.

    Parameters:
        text (str): The plain text extracted from a PDF page.

    Returns:
        list: A list of rows, where each row is a list of strings.
    """
    raw_keywords = [
        "okres", "nr poc", "relacja", "handlowa", "zestawienie", "termin",
        "kursowania", "z", "odj\\.?", "do", "przyj\\.?", "typ", "taboru", "ilość"
    ]
    patterns = [re.compile(r'\b' + keyword + r'\b', re.IGNORECASE) for keyword in raw_keywords]

    rows = []
    row = []
    lines = text.splitlines()
    column_counter = 0

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line:
            continue

        if any(pattern.search(line) for pattern in patterns):
            continue

        if column_counter < 8:
            # if 8th column is made only from numbers or contains "/" don't append that row:
            if column_counter == 6:
                next_line = lines[i].strip() if i < len(lines) else ""
                if not any(c.isalpha() for c in next_line) or "/" in next_line:
                    column_counter = 0
                    row = []
                    continue
            if ("PERON" in line or "LOTNISKO" in line) and i < len(lines):
                next_line = lines[i].strip()
                line = line + " " + next_line
                i += 1
            row.append(line)
            column_counter += 1
        else:
            rows.append(row)
            row = [line]
            column_counter = 1

    if row:
        rows.append(row)
    return rows



def convert_dates_from_roman(row: list) -> list:
    """
    Converts dates in the row from Roman numerals to Arabic numerals.

    Parameters:
        row (list): A list of strings representing a row.

    Returns:
        list: The row with dates converted to Arabic numerals.
    """
    date = row[-1]

    roman_to_arabic = {
        "I": "01", "II": "02", "III": "03", "IV": "04", "V": "05", "VI": "06",
        "VII": "07", "VIII": "08", "IX": "09", "X": "10", "XI": "11", "XII": "12"
    }

    roman_number = re.search(r'[IVX]+\b', date)


    if roman_number and '-' in date:  # date like "1-5 VI"
        roman = roman_number.group()
        arabic = roman_to_arabic.get(roman)

        date = date.replace(roman, '').strip()

        days = date.split('-')

        for i, day in enumerate(days):
            # add leading zero to day if needed
            if len(day) == 1:
                day = "0" + day
            days[i] = day + "." + arabic  # add month to day

        new_dates = "-".join(days)
        row[-1] = new_dates
    elif roman_number and ',' in date:  # date like "1,2 VI"
        roman = roman_number.group()
        arabic = roman_to_arabic.get(roman)

        date = date.replace(roman, '').strip()

        days = date.split(',')

        for i, day in enumerate(days):
            # add leading zero to day if needed
            if len(day) == 1:
                day = "0" + day
            days[i] = day + "." + arabic  # add month to day

        new_dates = ", ".join(days)
        row[-1] = new_dates

    elif roman_number and len(re.findall(r'[IVX]+', date)) == 1:  # date like "1 VI"
        roman = roman_number.group()
        arabic = roman_to_arabic.get(roman)
        if arabic:
            row[-1] = date.replace(roman, arabic).replace(" ", ".")

        # add leading zero to day if needed
        if len(row[-1].split(".")[0]) == 1:
            row[-1] = "0" + row[-1]

    return row





def process_pdf_to_rows(pdf_path):
    """
    Processes a PDF file and returns the extracted table rows.

    Parameters:
        pdf_path (str): The path to the PDF file.

    Returns:
        list: A list of table rows extracted from the PDF.
    """
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF file {pdf_path}: {e}")
        return []

    all_rows = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        rows = extract_table_from_text(page.get_text("text"))
        all_rows.extend(rows)

    return all_rows


def convert_all_pdfs_to_single_csv(source_dir='data/pdf', output_csv='data/csv/KM_table_current.csv'):
    """
    Converts all PDF files in the specified source directory to a single CSV file.

    Parameters:
        source_dir (str): The directory containing PDF files.
        output_csv (str): The path where the combined CSV file will be saved.
    """
    all_rows = []

    for file in os.listdir(source_dir):
        if file.endswith('.pdf'):
            pdf_path = os.path.join(source_dir, file)
            rows = process_pdf_to_rows(pdf_path)
            all_rows.extend(rows)

    try:
        with open(output_csv, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file, delimiter=";")
            for row in all_rows:
                writer.writerow(row)
        print(f"All data combined and saved to {output_csv}.")
    except Exception as e:
        print(f"Error writing to CSV {output_csv}: {e}")


if __name__ == '__main__':
    start = time.time()
    convert_all_pdfs_to_single_csv('data/pdf')
    end = time.time()
    print(f"Time taken: {end - start:.2f} seconds.")
