import sqlite3
from typing import List, Tuple, Optional


class DatabaseManager:
    def __init__(self, db_file: str = None):
        """Initialize the DatabaseManager with an optional database file path."""
        self.db_file = db_file
        self.connection = None

        if db_file:
            self.connect(db_file)

    def connect(self, db_file: str) -> sqlite3.Connection:
        """Create a database connection to the SQLite database specified by db_file."""
        try:
            self.connection = sqlite3.connect(db_file)
            self.db_file = db_file
            return self.connection
        except sqlite3.Error as e:
            print(f"Error connecting to database: {e}")
            return None

    def close(self):
        """Close the database connection if it exists."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def convert_to_inserts(self, csv_file: str) -> List[str]:
        """Convert CSV file data to SQL insert statements."""
        with open(csv_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        inserts = []

        for line in lines[1:]:  # Skip header
            if ',' in line.split(';')[5]:
                lines_to_insert = self._split_into_two_rows(line)
                for insert_line in lines_to_insert:
                    inserts.extend(self._generate_sql_inserts(*self._get_values_from_row(insert_line)))
            else:
                # extend because _generate_sql_inserts returns a list of inserts
                inserts.extend(self._generate_sql_inserts(*self._get_values_from_row(line)))

        return inserts

    @staticmethod
    def _split_dates_into_separate_rows(line: str) -> List[str]:
        """Split a row into multiple rows if it contains multiple dates or date ranges."""
        values = line.strip().split(';')
        dates = values[7].split(',')

        # If there's only one date or date range, return the original line
        if len(dates) == 1:
            return [line]

        # Create a new row for each date or date range
        result_rows = []
        for date in dates:
            new_values = values.copy()
            new_values[7] = date.strip()  # Replace with single date or date range
            result_rows.append(';'.join(new_values))

        return result_rows

    @staticmethod
    def _generate_sql_inserts(arrival_station: str, arrival_time: str, dates: List[str], departure_station: str,
                              departure_time: str, train_model: str, count: str, train_nr_1: str,
                              train_nr_2: Optional[str]) -> List[str]:
        """Generate SQL insert statements for train schedule data."""
        generated_inserts = []

        for d in dates:
            if '-' in d:
                d = d.split('-')
                start_date = d[0]
                end_date = d[1]
            else:
                start_date = d
                end_date = d

            insert = (
                f"INSERT INTO train_schedule (train_nr, departure_station, departure_time, arrival_station, arrival_time, train_model, count, start_date, end_date)"
                f" VALUES ('{train_nr_1}', '{departure_station}', '{departure_time}', '{arrival_station}', '{arrival_time}', '{train_model}', '{count}', '{start_date}', '{end_date}');")
            generated_inserts.append(insert)

            # train number 2 is not always present
            if train_nr_2:
                insert = (
                    f"INSERT INTO train_schedule (train_nr, departure_station, departure_time, arrival_station, arrival_time, train_model, count, start_date, end_date)"
                    f" VALUES ('{train_nr_2}', '{departure_station}', '{departure_time}', '{arrival_station}', '{arrival_time}', '{train_model}', '{count}', '{start_date}', '{end_date}');")
                generated_inserts.append(insert)

        return generated_inserts

    def _get_values_from_row(self, line: str) -> Tuple[str, str, List[str], str, str, str, str, str, Optional[str]]:
        """Extract values from a CSV row."""
        values = line.strip().split(';')
        train_nr_1, train_nr_2 = self._get_two_train_numbers(values)
        departure_station = values[1]
        departure_time = values[2]
        arrival_station = values[3]
        arrival_time = values[4]
        train_model = values[5]
        count = values[6]
        date = values[7]
        dates = date.split(',')

        return arrival_station, arrival_time, dates, departure_station, departure_time, train_model, count, train_nr_1, train_nr_2

    @staticmethod
    def _get_two_train_numbers(values: List[str]) -> Tuple[str, Optional[str]]:
        """Extract train numbers from values."""
        train_nr_raw = values[0]
        if '/' in train_nr_raw:
            train_nr_1 = train_nr_raw.split('/')[0]
            train_nr_2 = train_nr_raw[:4] + train_nr_raw.split('/')[1]
        else:
            train_nr_1 = train_nr_raw
            train_nr_2 = None
        return train_nr_1, train_nr_2

    @staticmethod
    def _split_into_two_rows(row_to_split: str) -> List[str]:
        """Split a row into two if it contains multiple train models."""
        values = row_to_split.strip().split(';')
        train_models = values[5].split(',')

        # a safety check to make sure that the row is split only if there are two train models
        if len(train_models) == 1:
            return [';'.join(values)]

        row_1 = values.copy()
        row_2 = values.copy()

        row_1[5] = train_models[0]
        row_2[5] = train_models[1]

        return [';'.join(row_1), ';'.join(row_2)]

    def insert_data(self, inserts: List[str]):
        """Execute SQL insert statements and commit the transaction."""
        if not self.connection:
            raise ValueError("Database connection not established. Call connect() first.")

        for insert in inserts:
            self.connection.execute(insert)
        self.connection.commit()

    @staticmethod
    def write_inserts_to_file(inserts: List[str], file_name: str):
        """Write SQL insert statements to a file."""
        with open(file_name, 'w', encoding='utf-8') as file:
            for insert in inserts:
                file.write(insert + '\n')

    def convert_to_inserts_with_date_splitting(self, csv_file: str) -> List[str]:
        """Convert CSV file data to SQL insert statements with date splitting."""
        with open(csv_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        inserts = []

        for line in lines[1:]:  # Skip header
            # First split by dates
            date_split_rows = self._split_dates_into_separate_rows(line)

            for date_row in date_split_rows:
                # Then handle train model splitting if needed
                if ',' in date_row.split(';')[5]:
                    model_split_rows = self._split_into_two_rows(date_row)
                    for model_row in model_split_rows:
                        inserts.extend(self._generate_sql_inserts(*self._get_values_from_row(model_row)))
                else:
                    inserts.extend(self._generate_sql_inserts(*self._get_values_from_row(date_row)))

        return inserts


# Example usage
if __name__ == "__main__":
    db_manager = DatabaseManager()

    # Convert CSV to SQL inserts with date splitting
    inserts = db_manager.convert_to_inserts_with_date_splitting('data/csv/KM_table_current.csv')

    # Write inserts to file
    db_manager.write_inserts_to_file(inserts, 'data/inserts.sql')

    # Connect to DB and insert data
    db_manager.connect('km_bot.db')
    db_manager.insert_data(inserts)
    db_manager.close()