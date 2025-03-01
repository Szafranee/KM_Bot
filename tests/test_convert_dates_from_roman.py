from convert_pdfs_to_csv import convert_dates_from_roman


class TestConvertDatesFromRoman:

    # Convert single Roman numeral month to Arabic numeral in date string
    def test_convert_roman_month_to_arabic(self):
        # Arrange
        input_row = ["some", "data", "3 XII"]
    
        # Act
        result = convert_dates_from_roman(input_row)
    
        # Assert
        assert result[-1] == "03.12"

    # Correctly converts a date range with Roman numeral month (e.g. '1-5 VI' to '1.06-5.06')
    def test_convert_date_range_with_roman_month(self):
        # Arrange
        row = ["some", "data", "1-5 VI"]

        # Act
        result = convert_dates_from_roman(row)

        # Assert
        assert result[-1] == "01.06-05.06"

    def test_convert_multiple_days_same_month(self):
        # Arrange
        row = ["some", "data", "1,2 VI"]

        # Act
        result = convert_dates_from_roman(row)

        # Assert
        assert result[-1] == "01.06,02.06"

    # Handle empty date string in the last row element
    def test_empty_date_string(self):
        # Arrange
        input_row = ["some", "data", ""]
    
        # Act
        result = convert_dates_from_roman(input_row)
    
        # Assert
        assert result[-1] == ""