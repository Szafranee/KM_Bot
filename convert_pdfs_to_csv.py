import csv
import os
import re
import time

import pymupdf


# TODO:
# 1. Date convertion

def extract_table_from_pdf_page(page_text: str) -> list:
    """
    Extracts table rows from the provided PDF page text by processing each line.
    Lines containing specific keywords are skipped to ensure only relevant data is captured.

    The keywords "odj." and "przyj." are handled with an optional period,
    allowing for matches with both "odj" and "odj." (and similarly for "przyj").

    Parameters:
        page_text (str): The plain text extracted from a PDF page.

    Returns:
        list: A list of rows, where each row is a list of strings representing table data.
    """
    raw_keywords = [
        "okres", "nr poc", "relacja", "handlowa", "zestawienie", "termin", "kursowania",
        "z", "odj\\.?", "do", "przyj\\.?", "typ", "taboru", "ilość", "legenda"
    ]
    keywords_pattern = [re.compile(r'\b' + keyword + r'\b', re.IGNORECASE) for keyword in raw_keywords]

    train_number_pattern = re.compile(r'^\d{5}(/\d+)?$')  # (e.g. 12345 or 12345/6)

    rows = []
    row = []
    lines = page_text.splitlines()
    column_counter = 1

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line:
            continue

        if any(pattern.search(line) for pattern in keywords_pattern):
            continue

        if column_counter < 9:
            if ("PERON" in line or "LOTNISKO" in line) and i < len(lines):
                next_line = lines[i].strip()
                line = line + " " + next_line
                i += 1

            if column_counter == 7:
                next_line = lines[i].strip() if i < len(lines) else ""

                # Special handling for EU47 trains to properly parse units and dates
                if lines[i - 2].strip().startswith("EU47"):
                    different_units_count = len(lines[i - 2].strip().split(", "))
                    line_parts = line.split(" ")
                    units_counts = line_parts[:different_units_count]
                    dates_part_1 = line_parts[different_units_count:]
                    dates_part_1 = " ".join(dates_part_1)

                    if i < len(lines) and not train_number_pattern.match(next_line):
                        dates = dates_part_1 + " " + next_line
                        lines[i] = dates

                    line = " ".join(units_counts)

                # if 8th column is a train number don't append that row, start new one
                # that's because 8th column is date and for some reason (KM moment) it is sometimes empty, making the row invalid (at least I assumed that from manually checking if these trains exist)
                if train_number_pattern.match(next_line):
                    column_counter = 0
                    row = []
                    continue

            if column_counter == 8:
                next_line = lines[i].strip() if i < len(lines) else ""
                # We need to keep checking if next line is not a train number (new row) or phrase to skip.
                # If it's neither of those, we need to append it to the current line because it's a part of the date.
                # If it's a train number or phrase to skip, we need to start a new row, because we reached the end of the current one.

                while (not train_number_pattern.match(next_line) and not any(
                        pattern.search(next_line) for pattern in keywords_pattern)) and i < len(lines):
                    line = line + " " + next_line
                    i += 1
                    next_line = lines[i].strip() if i < len(lines) else ""
            row.append(line)
            column_counter += 1
        else:
            rows.append(row)
            row = [line]
            column_counter = 2

    if row:
        rows.append(row)

    # Clean up date strings in the last element of each row
    rows = [format_date_strings(row) for row in rows]

    return rows


def format_date_strings(row: list) -> list:
    """
    Formats date strings in the last element of a row.

    Standardizes date formatting by ensuring consistent spacing around hyphens and commas.

    Args:
        row: A list where the last element contains date information.

    Returns:
        The modified row with cleaned date formatting in the last element.
    """
    dates = row[-1]
    dates = dates.replace("-", " - ").replace(",", ", ").replace("  ", " ").strip()

    row[-1] = dates
    return row


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


def extract_rows_from_pdf(pdf_path: str) -> list:
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
        rows = extract_table_from_pdf_page(page.get_text("text"))
        all_rows.extend(rows)

    return all_rows


def extract_rows_from_all_pdfs(source_dir='data/pdf') -> list:
    """
    Extracts rows from all PDF files in the specified source directory.

    Parameters:
        source_dir (str): The directory containing PDF files.

    Returns:
        list: A list of all rows extracted from all PDF files in the source directory.
    """
    all_rows = []

    for file in os.listdir(source_dir):
        if file.endswith('.pdf'):
            pdf_path = os.path.join(source_dir, file)
            rows = extract_rows_from_pdf(pdf_path)
            all_rows.extend(rows)

    return all_rows


def write_rows_to_csv(rows, output_csv='data/csv/KM_table_current.csv') -> None:
    """
    Writes the provided rows to a CSV file.

    Parameters:
        rows (list): The list of rows to write to the CSV file.
        output_csv (str): The path where the CSV file will be saved.
    """
    # Ensure the output directory exists
    output_dir = os.path.dirname(output_csv)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        with open(output_csv, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file, delimiter=";")
            for row in rows:
                writer.writerow(row)
        print(f"All data combined and saved to {output_csv}.")
    except Exception as e:
        print(f"Error writing to CSV {output_csv}: {e}")


def convert_all_pdfs_to_single_csv(source_dir='data/pdf', output_csv='data/csv/KM_table_current.csv') -> None:
    """
    Converts all PDF files in the specified source directory to a single CSV file.

    This function combines the functionality of extract_rows_from_all_pdfs and write_rows_to_csv.

    Parameters:
        source_dir (str): The directory containing PDF files.
        output_csv (str): The path where the combined CSV file will be saved.
    """
    all_rows = extract_rows_from_all_pdfs(source_dir)
    write_rows_to_csv(all_rows, output_csv)


if __name__ == '__main__':
    start = time.time()
    convert_all_pdfs_to_single_csv('data/pdf')
    end = time.time()
    print(f"Time taken: {end - start:.2f} seconds.")