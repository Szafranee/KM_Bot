import csv
import os

def extract_unique_dates_from_csv(csv_path='data/csv/KM_table_current.csv'):
    """
    Extracts unique dates from a CSV file at the provided file path. The function reads
    the CSV file, where values in the second-to-last column (or last column in smaller
    rows) are considered as date entries. These entries are checked for non-empty
    values, and unique dates are returned as a list.

    Args:
        csv_path (str): The path to the CSV file. Defaults to
            'data/csv/KM_table_current.csv'.

    Raises:
        FileNotFoundError: If the specified file path does not exist.

    Returns:
        list: A list containing unique non-empty date entries found in the specified
            CSV file.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"File {csv_path} does not exist")

    unique_dates = []
    seen = set()

    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=';')
            for row in reader:
                if len(row) >= 2:
                    date_entry = row[-2] if len(row) > 2 else row[-1]
                    if date_entry.strip() and date_entry not in seen:
                        unique_dates.append(date_entry)
                        seen.add(date_entry)
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
        return []

    return unique_dates


def extract_unique_dates_from_rows(csv_rows:[list[list[str]]]):
    """
    Extracts unique dates from a list of CSV rows. Each row is expected to be a list
    of strings, where the date information is typically located in the last or
    second-to-last column. Any blank or whitespace-only entries are ignored. The
    method ensures that only valid entries are considered when determining unique
    dates.

    Args:
        csv_rows (list[list[str]]): A list of CSV rows, where each row is a list
            of strings representing fields in a single record.

    Returns:
        list[str]: A list of unique date strings extracted from the input CSV rows.
    """
    unique_dates = []
    seen = set()

    for row in csv_rows:
        if len(row) >= 2:
            date_entry = row[-2] if len(row) > 2 else row[-1]
            if date_entry.strip() and date_entry not in seen:
                unique_dates.append(date_entry)
                seen.add(date_entry)
    return unique_dates


def main():
    dates = extract_unique_dates_from_csv()
    print(f"Found {len(dates)} unique dates")
    for date in dates:
        print(date)

if __name__ == "__main__":
    main()