import csv
import os
import re
import time

import pymupdf

import dates_extraction
import gemini_date_conversion


def convert_all_pdfs_to_single_csv(source_dir='data/pdf', output_csv='data/csv/KM_table_current.csv') -> None:
    """
    Converts all PDF files in the specified source directory to a single CSV file.

    This function combines the functionality of extract_rows_from_all_pdfs and write_rows_to_csv.
    The process includes extracting data from PDFs, formatting dates, converting Roman numerals,
    extracting date annotations, and writing the final data to a CSV file.

    Parameters:
        source_dir (str): The directory containing PDF files.
        output_csv (str): The path where the combined CSV file will be saved.
    """
    all_rows = extract_rows_from_all_pdfs(source_dir)

    # Process dates and extract annotations
    processed_rows = []
    for row in all_rows:
        if row:  # Skip empty rows
            row = normalize_date_string_whitespace(row)
            row = separate_date_annotations_to_new_column(row)
            processed_rows.append(row)

    # Convert dates in the processed rows
    processed_rows = convert_dates(processed_rows)

    write_rows_to_csv(processed_rows, output_csv)


def extract_rows_from_all_pdfs(source_dir='data/pdf') -> list[list[str]]:
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
        rows = parse_table_from_page_text(page.get_text("text"))
        all_rows.extend(rows)

    return all_rows


def parse_table_from_page_text(page_text: str) -> list[list[str]]:
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

    train_number_pattern = re.compile(r'^\d{5}(/\d)?$')  # (e.g. 12345 or 12345/6)

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

                # if the 8th column is a train number, OR is empty, don't append that row, start a new one
                # that's because the 8th column is a date, and for some reason (KM moment) it is sometimes empty, making the row invalid (at least I assumed that from manually checking if these trains exist)
                if train_number_pattern.match(next_line) or not next_line:
                    column_counter = 1
                    row = []
                    continue

            if column_counter == 8:
                next_line = lines[i].strip() if i < len(lines) else ""
                # We need to keep checking if the next line is not a train number (new row) or phrase to skip.
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

    return rows


def normalize_date_string_whitespace(row: list[str]) -> list:
    """
    Formats date strings in the last element of a row.

    Standardises date formatting by ensuring consistent spacing around hyphens and commas.

    Args:
        row: A list where the last element contains date information.

    Returns:
        The modified row with cleaned date formatting in the last element.
    """
    dates = row[-1]
    dates = dates.replace("-", " - ").replace(",", ", ").replace("  ", " ").strip()

    row[-1] = dates
    return row


def separate_date_annotations_to_new_column(row: list[str]) -> list:
    """
    Extracts special annotations from date strings and moves them to a separate column.

    Handles annotations like (C), (+), (1-6) that indicate special operating conditions
    such as weekends only or Monday to Saturday operation.

    Parameters:
        row (list): A list of strings representing a row, with the last element containing date information.

    Returns:
        list: The modified row with date annotations moved to a new column.
    """
    if not row:
        return row

    dates = row[-1]

    # find everything after " (" to the end of the string
    bracket_position = dates.find("(")
    if bracket_position != -1:
        annotation = dates[bracket_position:]
        dates = dates[:bracket_position].strip()
        row.append(annotation)
        row[-2] = dates
    else:
        row.append("")

    return row


def convert_dates(rows: list[list[str]]) -> list[list[str]]:
    """
    Converts dates in the rows of a dataset to a standardised format.

    This function processes a list of rows, extracts unique dates, converts them to a
    different format using an external date conversion module, and replaces the original
    dates in the specified column with their converted counterparts. If a date does not
    have a corresponding conversion in the map, a warning is printed.

    Args:
        rows (list[list[str]]): The dataset represented as a list of rows, where each
            row is a list of strings. The date to be converted is expected to be
            the second-to-last element in each row.

    Returns:
        list[list[str]]: The dataset with dates replaced by their converted
        counterparts in the second-to-last column.
    """

    # Extract unique dates from the rows
    unique_dates = dates_extraction.extract_unique_dates_from_rows(rows)

    # Convert the unique dates using the Gemini date conversion module
    date_converter = gemini_date_conversion.DateConverter()
    converted_dates = date_converter.get_converted_dates(dates=unique_dates)

    date_map = {date: converted for date, converted in zip(unique_dates, converted_dates)}

    for row in rows:
        if row and len(row) > 2:
            original_date = row[-2]
            if original_date in date_map:
                row[-2] = date_map[original_date]
            else:
                print(f"Warning: Date '{original_date}' not found in conversion map.")

    return rows


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


if __name__ == '__main__':
    start = time.time()
    convert_all_pdfs_to_single_csv('data/pdf')
    end = time.time()
    print(f"Time taken: {end - start:.2f} seconds.")