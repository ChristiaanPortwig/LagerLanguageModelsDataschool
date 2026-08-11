import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from backend.scripts.data_collection import (
    DataCollector,
    RequestDeadlineExceeded,
)


class DataCollectorTimeoutTests(unittest.TestCase):
    @staticmethod
    def html_response(body, url="https://example.com/reports"):
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response.headers["Content-Type"] = "text/html"
        response.encoding = "utf-8"
        response._content = body.encode("utf-8")
        return response

    @patch(
        "backend.scripts.data_collection.requests.get",
        side_effect=requests.ReadTimeout("source did not respond"),
    )
    def test_get_does_not_retry_a_timed_out_request(self, mocked_get):
        collector = DataCollector()

        with self.assertRaises(requests.ReadTimeout):
            collector._DataCollector__get(
                "https://www.glencore.com/publications", timeout=15
            )

        mocked_get.assert_called_once()
        self.assertEqual(mocked_get.call_args.kwargs["timeout"], (5, 15))

    def test_unreachable_source_is_not_retried_in_browser(self):
        collector = DataCollector()
        source = "https://www.glencore.com/publications"

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                collector,
                "_DataCollector__find_relevant_documents",
                side_effect=RequestDeadlineExceeded("deadline reached"),
            ), patch.object(
                collector, "_DataCollector__crawl4ai_documents"
            ) as browser_crawl:
                missing = collector._scrape_investor_documents(
                    "Glencore", [source], Path(directory)
                )

        self.assertEqual(missing, set(collector.KEYWORDS))
        browser_crawl.assert_not_called()

    def test_many_javascript_titles_without_file_links_finish_parsing(self):
        collector = DataCollector()
        body = "\n".join(
            f'{{"title": "Navigation card {number}"}}'
            for number in range(2_000)
        )

        with patch.object(
            collector,
            "_DataCollector__get",
            return_value=self.html_response(body),
        ):
            documents = collector._DataCollector__find_relevant_documents(
                "https://example.com/reports"
            )

        self.assertEqual(documents, [])

    def test_javascript_report_title_is_paired_with_its_file(self):
        collector = DataCollector()
        body = """
            {"title": "2025 Annual Report", "file_link": "/2025-report.pdf"},
            {"title": "Unrelated navigation card"}
        """

        with patch.object(
            collector,
            "_DataCollector__get",
            return_value=self.html_response(body),
        ):
            documents = collector._DataCollector__find_relevant_documents(
                "https://example.com/reports"
            )

        annual_reports = [
            document
            for document in documents
            if document["type"] == "annual_report"
        ]
        self.assertEqual(len(annual_reports), 1)
        self.assertEqual(
            annual_reports[0]["url"], "https://example.com/2025-report.pdf"
        )
        self.assertEqual(annual_reports[0]["link_text"], "2025 Annual Report")


class FilenameValidationTests(unittest.TestCase):
    def run_validation(self, filename, response=None, error=None):
        collector = DataCollector()
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "Glencore" / filename
            report.parent.mkdir()
            report.write_bytes(b"%PDF-test")

            with patch(
                "backend.scripts.data_collection.Gemini_Client"
            ) as validator:
                call = validator.return_value.call_gemini_structured_json
                if error is not None:
                    call.side_effect = error
                else:
                    call.return_value = response

                flagged = (
                    collector._DataCollector__validate_downloaded_filenames(
                        Path(directory)
                    )
                )
            retained = report.exists()

        return flagged, retained

    def test_explicitly_incorrect_filename_is_flagged_but_not_deleted(self):
        filename = "annual_report__2020__Other_Company_Transcript.pdf"
        flagged, retained = self.run_validation(
            filename,
            response={
                "documents": [{
                    "company": "Glencore",
                    "filename": filename,
                    "is_explicitly_incorrect": True,
                    "possibly_incorrect": False,
                    "reason": "The filename explicitly says 2020 and transcript.",
                }]
            },
        )

        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["document_name"], filename)
        self.assertEqual(Path(flagged[0]["location"]).name, "Glencore")
        self.assertTrue(flagged[0]["is_explicitly_incorrect"])
        self.assertFalse(flagged[0]["possibly_incorrect"])
        self.assertFalse(flagged[0]["missing_data"])
        self.assertTrue(retained)

    def test_possibly_incorrect_filename_returns_its_path(self):
        filename = "annual_report__2025__Acme_Group_Report.pdf"
        flagged, retained = self.run_validation(
            filename,
            response={
                "documents": [{
                    "company": "Glencore",
                    "filename": filename,
                    "is_explicitly_incorrect": False,
                    "possibly_incorrect": True,
                    "reason": "Acme may be another company or a subsidiary.",
                }]
            },
        )

        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["document_name"], filename)
        self.assertEqual(Path(flagged[0]["location"]).name, "Glencore")
        self.assertFalse(flagged[0]["is_explicitly_incorrect"])
        self.assertTrue(flagged[0]["possibly_incorrect"])
        self.assertFalse(flagged[0]["missing_data"])
        self.assertTrue(retained)

    def test_generic_filename_is_not_flagged_or_deleted(self):
        filename = "document.pdf"
        flagged, retained = self.run_validation(
            filename,
            response={
                "documents": [{
                    "company": "Glencore",
                    "filename": filename,
                    "is_explicitly_incorrect": False,
                    "possibly_incorrect": False,
                    "reason": "The filename is generic and inconclusive.",
                }]
            },
        )

        self.assertEqual(flagged, [])
        self.assertTrue(retained)

    def test_validator_failure_does_not_flag_or_delete(self):
        flagged, retained = self.run_validation(
            "unknown.pdf", error=RuntimeError("validator unavailable")
        )

        self.assertEqual(flagged, [])
        self.assertTrue(retained)

    def test_missing_ai_review_does_not_flag_or_delete(self):
        flagged, retained = self.run_validation(
            "generic.pdf", response={"documents": []}
        )

        self.assertEqual(flagged, [])
        self.assertTrue(retained)

    def test_public_collector_returns_flagged_document_records(self):
        collector = DataCollector()
        collector.INVESTOR_URLS = {}
        expected = [{
            "location": "/downloads/Glencore",
            "document_name": "questionable.pdf",
            "is_explicitly_incorrect": False,
            "possibly_incorrect": True,
            "missing_data": False,
            "reason": "Suspicious company name.",
        }]

        with patch.object(
            collector,
            "_DataCollector__validate_downloaded_filenames",
            return_value=expected,
        ):
            result = collector.scrape_and_save_reports("/unused")

        self.assertEqual(result, expected)

    def test_missing_document_types_are_flagged_without_gemini(self):
        collector = DataCollector()
        collector.INVESTOR_URLS = {"Glencore": ["https://example.com"]}

        with tempfile.TemporaryDirectory() as directory, patch.object(
            collector,
            "_scrape_investor_documents",
            return_value={"annual_report", "interim_results"},
        ), patch.object(
            collector, "get_sens_data", return_value=[]
        ), patch.object(
            collector,
            "_DataCollector__validate_downloaded_filenames",
            return_value=[],
        ) as gemini_validation:
            result = collector.scrape_and_save_reports(directory)

        self.assertEqual(
            [item["document_name"] for item in result],
            ["annual_report", "interim_results"],
        )
        self.assertTrue(all(item["missing_data"] for item in result))
        self.assertTrue(all(
            not item["is_explicitly_incorrect"]
            and not item["possibly_incorrect"]
            for item in result
        ))
        gemini_validation.assert_called_once_with(directory)


if __name__ == "__main__":
    unittest.main()
