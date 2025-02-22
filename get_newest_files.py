import shutil
import dotenv
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
import os

from sftp_actions import move_old_files_to_sftp

dotenv.load_dotenv()

server = os.getenv('SFTP_SERVER')
port = int(os.getenv('SFTP_PORT'))
username = os.getenv('SFTP_USERNAME')
password = os.getenv('SFTP_PASSWORD')
pdf_remote_dir = os.getenv('SFTP_PDFS_DIR')
old_data_remote_dir = os.getenv('SFTP_OLD_DIR')

# URL of the main page with train schedules
MAIN_URL = "https://www.mazowieckie.com.pl/pl/kategoria/rozklady-jazdy"


# Function to get links to PDF files from a given page
def get_pdf_links(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    pdf_links = []
    for link in soup.find_all("a", href=True):
        if "download" not in link.get("class", []):
            continue
        if link.get("href").endswith(".pdf"):
            pdf_links.append(link)
    return pdf_links


# Function to get the name of a PDF file from its URL
def get_pdf_name(pdf_url):
    pdf_name_encoded = pdf_url.split("/")[-1]
    pdf_name = unquote(pdf_name_encoded)
    return pdf_name


# List to store the names of the PDFs that are attempted to be downloaded
CURRENT_PDFS = []


# Function to check if a PDF file has already been downloaded, and download it if not
def check_and_download(pdf_url, pdf_name):
    pdf_path = os.path.join("data", "pdf", pdf_name)  # Adjusted path to the 'pdf' folder
    if not os.path.exists(pdf_path):
        # Download the PDF file
        pdf_response = requests.get(pdf_url)
        # Save the file to disk
        with open(pdf_path, "wb") as f:
            f.write(pdf_response.content)
        print(f"Downloaded: {pdf_name} ({pdf_url})")
    else:
        print(f"The file {pdf_name} already exists.")

    CURRENT_PDFS.append(pdf_name)
    if len(CURRENT_PDFS) == 0:
        print("No new PDFs found.")


def move_non_current_pdfs(current_dir, old_dir):
    os.makedirs(old_dir, exist_ok=True)  # Create the old directory if it doesn't exist

    saved_pdf_files = [f for f in os.listdir(current_dir) if f.endswith('.pdf')]

    # If a PDF is in the pdf_dir but not in the current_pdfs list, it is not a "newest one"
    non_current_pdfs = [pdf for pdf in saved_pdf_files if pdf not in CURRENT_PDFS]

    for pdf_file in non_current_pdfs:
        shutil.move(os.path.join(current_dir, pdf_file), os.path.join(old_dir, pdf_file))


def download_pdfs(main_url):
    # Get links to individual train schedule periods
    response = requests.get(main_url)
    soup = BeautifulSoup(response.content, "html.parser")
    period_links = soup.find_all("p", class_="title")  # Changed to look for links with class "title"
    print("Number of period links found:", len(period_links))
    for link in period_links:
        print(link)  # Print out the found links for inspection

    # Get links to PDF files from each period
    for period_link in period_links:
        period_url = period_link.find_next("a")["href"]  # Find the next <a> tag and get its href attribute

        # if period_url is a not a valid URL skip it
        if not period_url.startswith("http"):
            continue

        pdf_links = get_pdf_links(period_url)
        for link in pdf_links:
            pdf_url = urljoin(period_url, link["href"])  # Construct the full PDF URL
            pdf_name = get_pdf_name(pdf_url)
            if pdf_name.startswith("Zestawienie pociągów KM kursujących"):
                print(pdf_name)
                check_and_download(pdf_url, pdf_name)


def download_and_leave_newest_pdfs(main_url):
    download_pdfs(main_url)
    move_non_current_pdfs('data/pdf', 'data/old')


if __name__ == "__main__":
    download_and_leave_newest_pdfs(MAIN_URL)

    
