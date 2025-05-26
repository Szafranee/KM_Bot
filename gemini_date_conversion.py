import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

import dates_extraction


class DateConverter:
    def __init__(self, api_key=None, model="gemini-2.0-flash"):
        load_dotenv()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model
        self.client = genai.Client(api_key=self.api_key)

    @staticmethod
    def __get_dates():
        """Retrieves dates for conversion"""
        return dates_extraction.extract_unique_dates_from_csv()

    def __generate(self, dates):
        load_dotenv()

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=dates),
                ],
            ),
        ]
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
            system_instruction=[
                types.Part.from_text(text="""
                    # Date Conversion Prompt System
        
                    ## System Prompt
                    
                    You are a specialized date conversion assistant. Your task is to convert dates from various formats containing Roman numerals into standardized date formats with Arabic numerals. You will receive a list of dates in different formats, and you must return the converted list maintaining the same order.
                    
                    ## Input Format Rules
                    
                    The input may contain dates in the following formats:
                    - Single dates with Roman numerals for months: \"1 VI\" (June 1)
                    - Date ranges with Roman numerals: \"1 VI - 5 VII\" (June 1 - July 5)
                    - Multiple dates with the same Roman numeral month: \"1, 2 VI\" (June 1, June 2)
                    - Date ranges within the same month: \"1 - 5 VI\" (June 1 - June 5)
                    
                    ## Output Format Requirements
                    
                    Convert all dates to the following format:
                    - Single dates: \"DD.MM\" (e.g., \"01.06\")
                    - Date ranges: \"DD.MM - DD.MM\" (e.g., \"01.06 - 05.07\")
                    - Multiple dates: \"DD.MM, DD.MM\" (e.g., \"01.06, 02.06\")
                    
                    
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
                    - Do not add anything to the output that is not specified in the output format requirements - so only a list of dates in the specified format
                    - Always use two digits for both day and month (add leading zeros if necessary)
                    - Preserve the original spacing around hyphens and commas
                    - Return the results as a list in the same order as the input
                    
                    ## Examples
                    
                    Input:
                    [ \"1 VI\", \"1 VI - 5 VII\", \"1, 2 VI\", \"1 - 5 VI\", \"15 VIII\", \"1 I - 31 XII\", \"1, 15, 30 IX\", \"31 V - 14 VI\" ]
                    
                    Output:
                    [ \"01.06\", \"01.06 - 05.07\", \"01.06, 02.06\", \"01.06 - 05.06\", \"15.08\", \"01.01 - 31.12\", \"01.09, 15.09, 30.09\", \"31.05 - 14.06\" ]"""),
            ],
        )

        output = ''

        for chunk in self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
        ):
            output += chunk.text

        output = output.strip()
        return output

    def get_converted_dates(self, dates: str = None) -> list[str]:
        """Converts dates using Gemini model"""

        if dates is None:
            dates = self.__get_dates()

        if not dates:
            print("No dates to convert.")
            return []

        try:
            raw_dates = self.__generate(str(dates))
            if not raw_dates:
                print("No dates were returned from the model.")
                return []

            # Split the output into a list of dates
            raw_dates = raw_dates.strip().strip('`')
            raw_dates = raw_dates.strip().strip('[]')

            converted_dates = []

            for date in raw_dates.split('\', '):
                date = date.strip().strip('\'')
                if date:
                    converted_dates.append(date)

            return converted_dates
        except Exception as e:
            print(f"An error occurred during date conversion: {e}")
            return []


if __name__ == "__main__":
    converter = DateConverter()
    converted_dates = converter.get_converted_dates()
    for date in converted_dates:
        print(date)
