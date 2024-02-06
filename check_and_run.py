import psutil
import subprocess
import os
import sys
import time


def is_process_running(process_name):
    for process in psutil.process_iter(['pid', 'name']):
        if process.info['name'] == process_name:
            return True
    return False


def start_process(process_name):
    try:
        subprocess.Popen(['python', process_name])
    except Exception as e:
        print(f"Error starting {process_name}: {e}")


def main():
    script_name = "KM_bot.py"

    if is_process_running(script_name):
        print(f"{script_name} is already running. Exiting.")
        sys.exit(0)
    else:
        print(f"{script_name} is not running. Starting...")
        start_process(script_name)
        time.sleep(2)  # Give the process some time to start

        if is_process_running(script_name):
            print(f"{script_name} started successfully.")
        else:
            print(f"Failed to start {script_name}. Please check for errors.")


if __name__ == "__main__":
    main()
