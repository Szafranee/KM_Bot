import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

import dates_extraction

dates = dates_extraction.extract_unique_dates()
load_dotenv()

def generate():
    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY")
    )

    model = "gemini-2.0-flash-lite"
    contents = [types.Content(
        role="user",
        parts=[types.Part.from_text(
        text=f"Convert the following list of dates from formats with Roman numerals to the standardized DD.MM format:\n {dates}"), ], ), ]
    generate_content_config = types.GenerateContentConfig(
        temperature=1,
        top_p=0.95,
        top_k=40,
        max_output_tokens=8192,
        response_mime_type="text/plain",
        system_instruction=[types.Part.from_text(
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
            ),
        ],
    )

    for chunk in client.models.generate_content_stream(model=model, contents=contents,
            config=generate_content_config, ):
        print(chunk.text, end="")


generate()
