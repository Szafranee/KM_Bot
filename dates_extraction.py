import csv
import os

def extract_unique_dates(csv_path='data/csv/KM_table_current.csv'):
    """
    Extracts a list of unique date formats from a CSV file.

    Parameters:
        csv_path (str): The path to the CSV file

    Returns:
        list: List of unique date formats
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"File {csv_path} does not exist")

    unique_dates = set()

    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=';')
            for row in reader:
                if len(row) >= 2:
                    date_entry = row[-2] if len(row) > 2 else row[-1]
                    if date_entry.strip():
                        unique_dates.add(date_entry)
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
        return []

    return list(unique_dates)

def main():
    dates = extract_unique_dates()
    print(f"Found {len(dates)} unique date formats.")
    print(dates)

if __name__ == "__main__":
    main()