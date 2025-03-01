from convert_pdfs_to_csv import extract_date_annotations


class TestExtractDateAnnotations:

    # Extract annotation when date string contains single bracket annotation
    def test_extract_single_bracket_annotation(self):
        input_row = ["Route 1", "Stop A", "10:00 (Weekend only)"]
        expected = ["Route 1", "Stop A", "10:00", "(Weekend only)"]
        result = extract_date_annotations(input_row)
        assert result == expected

    # Handle empty input row
    def test_empty_input_row(self):
        input_row = []
        result = extract_date_annotations(input_row)
        assert result == []