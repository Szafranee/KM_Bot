import os
import time
from datetime import datetime
import csv
from threading import Thread
from typing import Final
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
from dotenv import load_dotenv

# Constants
load_dotenv()
api_key = os.getenv('TELEGRAM_API_TOKEN')
BOT_USERNAME: Final = '@kmkobot'
CSV_FILE_PATH = 'data/KM_table_csv_combined.csv'
MONTH_ROMAN_NUMERALS = {
    'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6,
    'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10, 'XI': 11, 'XII': 12
}
DAYS_OF_THE_WEEK = {
    '1': 'poniedziałek', '2': 'wtorek', '3': 'środa', '4': 'czwartek',
    '5': 'piątek', '6': 'sobota', '7': 'niedziela'
}
WORKDAYS = [0, 1, 2, 3, 4]
HOLIDAYS = {
    '1.01': 'Nowy Rok', '6.01': 'Trzech Króli', '1.05': 'Święto Pracy',
    '3.05': 'Święto Konstytucji 3 Maja', '15.08': 'Wniebowzięcie Najświętszej Maryi Panny',
    '1.11': 'Wszystkich Świętych', '11.11': 'Święto Niepodległości', '25.12': 'Boże Narodzenie',
    '26.12': 'Boże Narodzenie'
}
today = datetime.now().date()
year = datetime.now().year
TRAIN_IMAGES = {
    'Flirt 1': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/Flirt_1.jpg',
    'Flirt 3': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/Flirt_3.jpg',
    'Impuls': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/Impuls.jpg',
    'Elf': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/Elf.jpg',
    'SA135': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/SA135.jpg',
    'SA222': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/SA222.jpg',
    'Vt627': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/VT627.jpg',
    '111Eb': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/Pesa_111Eb.jpg',
    'EU47': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/EU47.jpg',
    'The Kibel': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/EN_57.jpg',
    'Kibel AKM': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/EN_57AKM.jpg',
    'Kibel AL': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/EN_57AL.jpg',
    'Kibel EN71': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/EN_71.jpg',
    'SN82 (dzierżawiony od SKPL)': 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/SN82.jpg',
}


def get_train_info(reader, train_nr):
    for row in reader:
        row_nr = row[0]
        row_sliced = None

        if len(row_nr) > 5:
            if row_nr[:4] == train_nr[:4] and row_nr[6] == train_nr[4]:
                row_sliced = row_nr[:4] + row_nr[6:]
            elif row_nr[:5] == train_nr:
                row_sliced = row_nr[:5]
        elif row_nr == train_nr:
            row_sliced = row_nr

        if row_sliced is not None:
            row[0] = row_sliced
            if is_valid_date_range(row[7]):
                return format_train_info(row)

    return {"numer_pociagu": train_nr, "typ_taboru": f"Nie znaleziono pociągu o numerze {train_nr}"}


def get_train_info_from_nr(train_nr: str):
    with open(CSV_FILE_PATH, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile, delimiter=';')
        next(reader, None)  # skip the headers
        return get_train_info(reader, train_nr)


def get_train_info_from_stations(start_station: str, end_station: str, time: str):
    with open(CSV_FILE_PATH, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile, delimiter=';')
        next(reader, None)  # skip the headers

        # Search for train number
        for row in reader:
            if row[1] == start_station.upper() and row[3] == end_station.upper() and row[2] == time:
                return format_train_info(row)
        return {"numer_pociagu": "Nie znaleziono pociągu", "typ_taboru": "Nie znaleziono pociągu"}


def is_valid_date_range(date_range):
    if '(' in date_range:
        date_range, additional_info = date_range.split("(", 1)[0].strip(), date_range.split("(", 1)[1].split(")")[
            0].strip()
    else:
        additional_info = None

    if process_additional_info(additional_info):
        if 'i' in date_range:
            date_ranges = date_range.split('i').trim()
            for dr in date_ranges:
                return is_valid_date_range(dr)

        if ',' in date_range:
            date_ranges = date_range.split(',')
            for dr in date_ranges:
                if '-' in dr:
                    start_date, end_date = dr.split('-')
                    if ' ' in start_date:
                        day = start_date.split(' ')[0]
                        month = start_date.split(' ')[1]
                        start_date = parse_date(day, year, month)
                    elif ' ' in end_date:
                        day = end_date.split(' ')[0]
                        month = end_date.split(' ')[1]
                        end_date = parse_date(day, year, month)
                    else:
                        day = end_date
                        month = date_range.split(' ')[1]
                        end_date = parse_date(day, year, month)

                    if start_date <= today <= end_date:
                        return True
                else:
                    if (' ' in dr) and (dr.split(' ')[0].isdigit()):
                        day = dr.split(' ')[0]
                        month = dr.split(' ')[1]
                        date = parse_date(day, year, month)
                    else:
                        day = dr
                        month = date_range.split(' ')[1]
                        date = parse_date(day, year, month)
                    if date == today:
                        return True
        elif '-' in date_range:
            start_date, end_date = date_range.split('-')

            start_date = split_and_parse_date(start_date, date_range)
            end_date = split_and_parse_date(end_date, date_range)

            if start_date <= today <= end_date:
                return True
        else:
            date = parse_date(date_range.strip(), year)
            if date == today:
                return True

    return False


def split_and_parse_date(date_str, date_range):
    if ' ' in date_str:
        day = date_str.split(' ')[0]
        month = date_str.split(' ')[1]
        parsed_date = parse_date(day, year, month)
    else:
        day = date_str
        month = date_range.split(' ')[1]
        parsed_date = parse_date(day, year, month)

    return parsed_date


def parse_date(date_str, year, month=None):
    if ' ' in date_str:
        day, month_from_roman = date_str.split(' ')
        month_from_roman = MONTH_ROMAN_NUMERALS[month_from_roman]
        day = int(day)
        date = datetime(year, month_from_roman, day).date()
    else:
        day = int(date_str)
        month_from_roman = MONTH_ROMAN_NUMERALS[month]
        date = datetime(year, month_from_roman, day).date()

    return date


def process_additional_info(additional_info):
    today_without_year = today.strftime('%d.%m')  # remove year from today's date
    if additional_info is None:
        return True

    if additional_info == 'A':  # runs on workdays
        return today.weekday() in WORKDAYS
    if additional_info == 'B':  # runs on workdays and sundays
        return today.weekday() in WORKDAYS or today.weekday() == 6
    if additional_info == 'C':  # runs on weekends and holidays
        return today.weekday() == 5 or today.weekday() == 6 or today_without_year in HOLIDAYS
    if additional_info == 'D':  # runs on workdays but not on holidays
        return today.weekday() in WORKDAYS and today_without_year not in HOLIDAYS
    if additional_info == 'E':  # runs on workdays and saturdays but not on holidays
        return (today.weekday() in WORKDAYS or today.weekday() == 5) and today_without_year not in HOLIDAYS
    if additional_info == '+':  # runs on holidays
        return today_without_year in HOLIDAYS
    if additional_info.isdigit():  # runs on specified day of the week
        return today.weekday() == int(additional_info) - 1
    if '-' in additional_info:  # runs on specified days of the week
        start_day, end_day = additional_info.split('-')
        return int(start_day) - 1 <= today.weekday() <= int(end_day) - 1

    return False


# Test cases
# print(is_valid_date_range("29 XI (A)"))  # Single day with note
# print(is_valid_date_range("23 XI-1 XII (B)"))  # Date range with note
# print(is_valid_date_range("27 XI,30 XI-1 XII (C)"))  # Mixed format with note
# print(is_valid_date_range("2,4-9 XII (D)"))  # Mixed format with note
# print(is_valid_date_range("2-3,9 XII (E)"))  # Mixed format with note
# print(is_valid_date_range("2,9 XII (1)"))  # Mixed format with note
# print(is_valid_date_range("11-16,18-23 XII (2-7)"))  # Date range with note
# print(is_valid_date_range("10-30 XI (5-6)"))  # Date range with note


def format_train_info(row: list):
    train_model_mapping = {
        'ER75': 'Flirt 1',
        'ER160': 'Flirt 3',
        '45WE': 'Impuls',
        'EN76': 'Elf',
        'SA135': 'SA135',
        'SA222': 'SA222',
        'Vt627': 'Vt627',
        '111Eb': 'Pesa 111Eb',
        'EU47': 'EU47',
        'EN57w': 'The Kibel',
        'EN57AKM': 'Kibel AKM',
        'EN57AL': 'Kibel AL',
        'EN71': 'Kibel EN71',
        'SN82': 'SN82 (dzierżawiony od SKPL)'
    }

    train_model = row[5]
    for key, value in train_model_mapping.items():
        if key in train_model:
            train_model = value
            break

    return {"numer_pociagu": row[0], "typ_taboru": train_model}


# Commands
async def start_command(update: Update, context: ContextTypes):
    await update.message.reply_text('Witam!')


async def help_command(update: Update, context: ContextTypes):
    await update.message.reply_text('Pomoc tutaj')


async def model_from_number_command(update: Update, context: ContextTypes):
    await update.message.reply_text('Podaj 5-cyfrowy numer pociągu KM')


async def model_from_stations_command(update: Update, context: ContextTypes):
    await update.message.reply_text(
        'Podaj stację początkową, stację końcową oraz godzinę odjazdu ze stacji początkowej')


# Responses
def handle_response(text: str):
    if '\n' in text:
        char_to_split = '\n'
    elif ',' in text:
        char_to_split = ','
    elif ';' in text:
        char_to_split = ';'
    else:
        char_to_split = None

    parameters = text.split(char_to_split)
    parameters = [x.strip() for x in parameters]
    parameters = [x.upper() for x in parameters]

    if len(text) == 5 and text.isdigit():
        return get_train_info_from_nr(text)
    elif len(parameters) == 3:
        return get_train_info_from_stations(parameters[0], parameters[1], parameters[2])
    else:
        return {"numer_pociagu": "Nieprawidłowy format", "typ_taboru": "Nieprawidłowy format"}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        message_type = update.message.chat.type
    except AttributeError:
        print("Update message or chat is None")
        return

    print(f'User {update.message.chat.username} in {message_type} sent: "{text}"')

    if message_type == 'group' and BOT_USERNAME not in text:
        return

    new_text = text.replace(BOT_USERNAME, '') if BOT_USERNAME in text else text
    response = handle_response(new_text)

    # Fetch the url based on the train model
    image_url = TRAIN_IMAGES.get(response['typ_taboru'],
                                 'https://users.pja.edu.pl/~s28102/KM_Bot/Images/default_pic.jpg')

    print('Bot responded with:', response)

    await update.message.reply_text(
        f"Numer pociągu: *{response['numer_pociagu']}*\n"
        f"Typ taboru: *{response['typ_taboru']}*\n"
        f"[{response['typ_taboru']}]({image_url})", parse_mode='Markdown')


async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f'Update {update} caused error {context.error}')


if __name__ == '__main__':
    print('Starting bot...')

    app = Application.builder().token(api_key).build()

    # Commands handling
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('help', help_command))
    # app.add_handler(CommandHandler('model', model_from_number_command))
    # app.add_handler(CommandHandler('model2', model_from_stations_command))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    # Errors
    app.add_error_handler(error)

    # Polls the bot
    print('Polling...')
    app.run_polling(poll_interval=1)
