import sqlite3


def create_connection(db_file: str) -> sqlite3.Connection:
    connection = None
    try:
        connection = sqlite3.connect(db_file)
    except sqlite3.Error as e:
        print(e)

    return connection


def convert_to_inserts(csv_file: str) -> [str]:
    with open(csv_file, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    inserts = []

    for line in lines[1:]:
        if ',' in line.split(';')[5]:
            lines_to_insert = split_into_two_rows(line)
            for insert_line in lines_to_insert:
                inserts.extend(generate_sql_inserts(*get_values_from_row(insert_line)))

        # extend because generate_sql_inserts returns a list of inserts
        inserts.extend(generate_sql_inserts(*get_values_from_row(line)))

    return inserts


def generate_sql_inserts(arrival_station, arrival_time, dates, departure_station, departure_time, train_model, count,
                         train_nr_1, train_nr_2) -> [str]:
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


def get_values_from_row(line):
    values = line.strip().split(';')
    train_nr_1, train_nr_2 = get_two_train_numbers(values)
    departure_station = values[1]
    departure_time = values[2]
    arrival_station = values[3]
    arrival_time = values[4]
    train_model = values[5]
    count = values[6]
    date = values[7]
    dates = date.split(',')

    return arrival_station, arrival_time, dates, departure_station, departure_time, train_model, count, train_nr_1, train_nr_2


def get_two_train_numbers(values):
    train_nr_raw = values[0]
    if '/' in train_nr_raw:
        train_nr_1 = train_nr_raw.split('/')[0]
        train_nr_2 = train_nr_raw[:4] + train_nr_raw.split('/')[1]
    else:
        train_nr_1 = train_nr_raw
        train_nr_2 = None
    return train_nr_1, train_nr_2


def split_into_two_rows(row_to_split: str) -> [str]:
    row_to_split = row_to_split.strip().split(';')
    train_models = row_to_split[5].split(',')

    # a safety check to make sure that the row is split only if there are two train models
    if len(train_models) == 1:
        return [row_to_split]

    row_1 = row_to_split.copy()
    row_2 = row_to_split.copy()

    row_1[5] = train_models[0]
    row_2[5] = train_models[1]

    row_1 = ';'.join(row_1)
    row_2 = ';'.join(row_2)

    return [row_1, row_2]


def insert_data(connection: sqlite3.Connection, inserts: [str]):
    for insert in inserts:
        connection.execute(insert)
    connection.commit()


# write inserts to file
def write_inserts_to_file(inserts: [str], file_name: str):
    with open(file_name, 'w', encoding='utf-8') as file:
        for insert in inserts:
            file.write(insert + '\n')


inserts = convert_to_inserts('data/csv/KM_table_current.csv')

write_inserts_to_file(inserts, 'data/inserts.sql')
