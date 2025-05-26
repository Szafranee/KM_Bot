from convert_pdfs_to_csv import separate_date_annotations_to_new_column


class TestExtractDateAnnotations:

    # Extract annotation when date string contains single bracket annotation
    def test_extract_single_bracket_annotation(self):
        input_row = ["Route 1", "Stop A", "10:00 (Weekend only)"]
        expected = ["Route 1", "Stop A", "10:00", "(Weekend only)"]
        result = separate_date_annotations_to_new_column(input_row)
        assert result == expected

    # Handle empty input row
    def test_empty_input_row(self):
        input_row = []
        result = separate_date_annotations_to_new_column(input_row)
        assert result == []