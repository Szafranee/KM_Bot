import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
import dates_extraction

class DateConverter:
    def __init__(self, api_key=None, model="gemini-2.0-flash-lite"):
        load_dotenv()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model
        self.client = genai.Client(api_key=self.api_key)

    @staticmethod
    def get_dates():
        """Retrieves dates for conversion"""
        return dates_extraction.extract_unique_dates()

    @staticmethod
    def get_system_instruction():
        """Returns system instruction for the model"""
        return types.Part.from_text(
            text="""# Date Conversion Prompt System

                    ## System Prompt

                    You are a specialized date conversion assistant. Your task is to convert dates from various formats containing Roman numerals into standardized date formats with Arabic numerals. You will receive a list of dates in different formats, and you must return the converted list maintaining the same order.

                    ## Input Format Rules

                    The input may contain dates in the following formats:
                    - Single dates with Roman numerals for months: \"1 VI\" (June 1)
                    - Date ranges with Roman numerals: \"1 VI - 5 VII\" (June 1 - July 5)
                    - Multiple dates with the same Roman numeral month: \"1, 2 VI\" (June 1, June 2)
                    - Date ranges within the same month: \"1 - 5 VI\" (June 1 - June 5)
                    - Dates with annotations in parentheses: \"1 VI (C)\" or \"1-5 VI (+)\"

                    ## Output Format Requirements

                    Convert all dates to the following format:
                    - Single dates: \"DD.MM\" (e.g., \"01.06\")
                    - Date ranges: \"DD.MM - DD.MM\" (e.g., \"01.06 - 05.07\")
                    - Multiple dates: \"DD.MM, DD.MM\" (e.g., \"01.06, 02.06\")
                    - Preserve any annotations in parentheses at the end

                    ## Roman to Arabic Month Conversion
                    - I → 01 (January)
                    - II → 02 (February)
                    - III → 03 (March)
                    - IV → 04 (April)
                    - V → 05 (May)
                    - VI → 06 (June)
                    - VII → 07 (July)
                    - VIII → 08 (August)
                    - IX → 09 (September)
                    - X → 10 (October)
                    - XI → 11 (November)
                    - XII → 12 (December)

                    ## Additional Rules
                    - Always use two digits for both day and month (add leading zeros if necessary)
                    - Preserve the original spacing around hyphens and commas
                    - Return the results as a list in the same order as the input

                    ## Examples

                    Input:
                    [ \"1 VI\", \"1 VI - 5 VII\", \"1, 2 VI\", \"1 - 5 VI\", \"1 VI (C)\", \"15 VIII\", \"1 I - 31 XII\", \"1, 15, 30 IX\" ]

                    Output:
                    [ \"01.06\", \"01.06 - 05.07\", \"01.06, 02.06\", \"01.06 - 05.06\", \"01.06 (C)\", \"15.08\", \"01.01 - 31.12\", \"01.09, 15.09, 30.09\" ]"""
        )

    def create_content_config(self):
        """Creates configuration for model query"""
        return types.GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
            response_mime_type="text/plain",
            system_instruction=[self.get_system_instruction()],
        )

    @staticmethod
    def create_contents(dates):
        """Creates query content with dates"""
        return [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=f"Convert the following list of dates from formats with Roman numerals to the standardized DD.MM format:\n {dates}"
                    ),
                ],
            )
        ]

    def convert_dates(self, dates=None, stream=True):
        """Converts dates using Gemini model"""
        dates = dates or self.get_dates()
        contents = self.create_contents(dates)
        config = self.create_content_config()

        if stream:
            return self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config
            )
        else:
            return self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config
            )

    def generate(self):
        """Generates and displays converted dates"""
        for chunk in self.convert_dates():
            print(chunk.text, end="")


if __name__ == "__main__":
    converter = DateConverter()
    converter.generate()