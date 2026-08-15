from pathlib import Path
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
import html
import json
import logging
import re
import requests
import signal
import sys
import threading
from bs4 import BeautifulSoup

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts.gemini_client import Gemini_Client
from backend.config.gemini_structured_schemas import (
    DocumentFilenameValidationResponse,
)
from backend.config.prompts import DOCUMENT_FILENAME_VALIDATION_PROMPT

LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


class RequestDeadlineExceeded(requests.Timeout):
    """Raised when an HTTP request exceeds its wall-clock deadline."""


@contextmanager
def request_deadline(seconds, url):
    """Enforce a real deadline around requests on Unix's main thread.

    ``requests`` timeouts cover connecting and gaps between received bytes;
    they do not guarantee that the entire call returns within that period.
    SIGALRM also interrupts DNS resolution and trickle-fed responses. In
    worker threads or on platforms without ``setitimer``, requests' own
    connect/read timeout remains the fallback.
    """
    can_alarm = (
        threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
    )
    if not can_alarm:
        yield
        return

    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer[0] > 0:
        # Do not interfere with a deadline owned by a notebook or caller.
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def deadline_reached(_signum, _frame):
        raise RequestDeadlineExceeded(
            f"Requesting {url} exceeded the {seconds}s deadline"
        )

    signal.signal(signal.SIGALRM, deadline_reached)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

JSE_SENS_URL = (
    "https://clientportal.jse.co.za/communication/sens-announcements"
)

# JSE alpha codes are identifiers, not document locations, and remain separate
# from the investor-site configuration.
JSE_COMPANY_CODES = {
    "OUTsurance Group": "OUT",
    "Bid Corporation": "BID",
    "MTN Group": "MTN",
    "Aspen Pharmacare": "APN",
    "NEPI Rockcastle": "NRP",
    "Pepkor Holdings": "PPH",
    "Naspers": "NPN",
    "The Bidvest Group": "BVT",
    "Sanlam": "SLM",
    "Gold Fields": "GFI",
    "Clicks Group": "CLS",
    "Anglo American": "AGL",
    "AngloGold Ashanti": "ANG",
    "BHP Group": "BHG",
    "Shoprite Holdings": "SHP",
    "Valterra Platinum": "VAL",
    "Vodacom Group": "VOD",
    "Shaftesbury Capital plc": "SHC",
    "Glencore": "GLN",
    "Prosus": "PRX",
}


class DataCollector:
    """Class used for collecting data from external sources"""

    #NOTE: Some of these keywords were optimized for the clients of Syn bank. This might need to be
    # updated for new clients
    KEYWORDS = {
            "annual_report": [
            "annual report",
            "integrated report",
            "annual integrated report",
        ],
        "financial_statements": [
            "annual financial statements",
            "financial statements",
            "annual report",
            "afs",
            "form 20-f",
        ],
        "interim_results": [
            "interim results",
            "half year results",
            "half-year results",
            "interim financial statements",
            "earnings release",
        ],
        "results_presentation": [
            "results presentation",
            "annual results presentation",
            "interim results presentation",
            "earnings release presentation",
        ],
    }

    # Each company can expose reports across multiple stable landing pages.
    INVESTOR_URLS = {
        "OUTsurance Group": ["https://group.outsurance.co.za/results-and-reports/"],
        "Bid Corporation": ["https://www.bidcorpgroup.com/assets/js/archive-data.js"],
        "MTN Group": [
            "https://www.mtn.com/financial-results/",
            "https://www.mtn.com/annual-reports/",
            "https://www.mtn.com/investors-shareholders?tablink=presentations-and-transcripts",
            "https://www.mtn.com/wp-json/wp/v2/media?search=results%20presentation&per_page=50",
            "https://www.sharedata.co.za/v2/Scripts/Glossies.aspx?c=MTN&x=JSE",
        ],
        "Aspen Pharmacare": ["https://www.aspenpharma.com/investor-relations/"],
        "NEPI Rockcastle": ["https://nepirockcastle.com/investors/financial-information/"],
        "Pepkor Holdings": ["https://pepkor.co.za/latest-financial-results/"],
        "Naspers": ["https://www.naspers.com/investors/results-reports-events"],
        "The Bidvest Group": ["https://bidvest.co.za/investor-relations"],
        "Sanlam": ["https://www.sanlam.com/financial-reporting.php"],
        "Gold Fields": ["https://www.goldfields.com/investor-overview.php"],
        "Clicks Group": ["https://www.clicksgroup.co.za/results/"],
        "Anglo American": [
            "https://www.angloamerican.com/investors/results-centre-and-presentations",
            "https://www.angloamerican.com/investors/annual-reporting",
        ],
        "AngloGold Ashanti": [
            "https://www.anglogoldashanti.com/investors/reporting/financial-results/",
            "https://www.anglogoldashanti.com/investors/reporting/annual-reports/",
        ],
        "BHP Group": [
            "https://www.bhp.com/investor-hub/reports-and-presentations/annual-report",
            "https://www.sharedata.co.za/v2/Scripts/Glossies.aspx?c=BHG&x=JSE",
        ],
        "Shoprite Holdings": ["https://www.shopriteholdings.co.za/shareholders-investors/reports-documents.html"],
        "Valterra Platinum": ["https://www.valterraplatinum.com/investor-centre/company-results-reports-presentations/"],
        "Vodacom Group": ["https://www.vodacom.com/annual-results.php"],
        "Shaftesbury Capital plc": [
            "https://www.shaftesburycapital.com/en/investors/results-reports-presentations.html",
            "https://www.sharedata.co.za/v2/Scripts/Glossies.aspx?c=SHC&x=JSE",
        ],
        "Glencore": ["https://www.glencore.com/publications"],
        "Prosus": ["https://www.prosus.com/investors/financial-information/results"],
    }

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    DEFAULT_DOWNLOAD_DIR = (
        Path(__file__).resolve().parents[2] / "data" / "downloads"
    )

    def collect_data(self, *, scrape_scope="all", save_location=None):
        """Scrape disclosures without performing any data extraction.

        ``scrape_scope`` must be ``"all"`` or ``"sens"``. The returned value
        is the underlying scraper result: document issues for an all-source
        scrape, or SENS announcement metadata for a SENS-only scrape.
        """
        if scrape_scope not in {"all", "sens"}:
            raise ValueError("scrape_scope must be either 'all' or 'sens'")

        downloads_dir = Path(save_location or self.DEFAULT_DOWNLOAD_DIR)
        downloads_dir.mkdir(parents=True, exist_ok=True)
        if scrape_scope == "sens":
            return self.get_sens_data(base_dir=downloads_dir)
        return self.scrape_and_save_reports(downloads_dir)
    def __get(self, url, timeout):
        LOGGER.info("Requesting %s (timeout=%ss)", url, timeout)
        try:
            with request_deadline(timeout, url):
                return requests.get(
                    url,
                    headers=self.HEADERS,
                    timeout=(min(5, timeout), timeout),
                )
        except requests.Timeout as error:
            LOGGER.warning(
                "Request timed out after %ss; skipping %s (%s)",
                timeout,
                url,
                error,
            )
            raise
        except requests.exceptions.SSLError:
            if urlparse(url).hostname not in {"goldfields.com", "www.goldfields.com"}:
                raise
            # Gold Fields currently serves an incomplete certificate chain.
            LOGGER.warning(
                "TLS verification failed for %s; retrying without verification",
                url,
            )
            with request_deadline(timeout, url):
                return requests.get(
                    url,
                    headers=self.HEADERS,
                    timeout=(min(5, timeout), timeout),
                    verify=False,
                )

    def scrape_and_save_reports(self, save_location = Path(__file__).resolve().parents[2] / 'data' / 'downloads'):
        """Save reports and return document issues requiring attention.

        A complete set contains every type in ``KEYWORDS``, including an
        interim result, from the current or previous calendar year. Gemini
        supplies the incorrect-file flags; missing document types are detected
        directly from scraper results and never inferred by Gemini.
        """
        document_issues = []
        missing_by_company = {}
        for company, urls in self.INVESTOR_URLS.items():
            LOGGER.info("Scraping %s", company)
            try:
                missing_types = self._scrape_investor_documents(
                    company, urls, save_location
                )
                if missing_types:
                    missing_by_company[company] = set(missing_types)
            except Exception as e:
                LOGGER.exception("Couldn't scrape %s: %s", company, e)
                missing_by_company[company] = set(self.KEYWORDS)
            try:
                self.get_sens_data(company, save_location)
            except Exception as error:
                LOGGER.exception(
                    "Couldn't get SENS data for %s: %s", company, error
                )

        for company, missing_types in missing_by_company.items():
            company_folder = (
                Path(save_location) / self.__clean_filename(company)
            ).resolve()
            for document_type in sorted(missing_types):
                document_issues.append({
                    "location": str(company_folder),
                    "document_name": document_type,
                    "is_explicitly_incorrect": False,
                    "possibly_incorrect": False,
                    "missing_data": True,
                    "reason": f"No recent {document_type} document was found.",
                })

        if missing_by_company:
            LOGGER.warning(
                "Companies with incomplete report sets: %s",
                ", ".join(missing_by_company),
            )
        document_issues.extend(
            self.__validate_downloaded_filenames(save_location)
        )
        return sorted(
            document_issues,
            key=lambda item: (item["location"], item["document_name"]),
        )

    def __validate_downloaded_filenames(self, save_location):
        """Return questionable non-SENS file records without deleting files.

        A generic or inconclusive filename is not evidence that a document is
        wrong. Validator failures and missing decisions are therefore logged
        for visibility but do not flag a document.
        """
        base_dir = Path(save_location)
        inputs = []
        paths_by_key = {}
        company_names_by_folder = {
            self.__clean_filename(company): company
            for company in self.INVESTOR_URLS
        }

        for company_folder in base_dir.iterdir() if base_dir.exists() else []:
            if not company_folder.is_dir():
                continue
            company = company_names_by_folder.get(
                company_folder.name, company_folder.name.replace("_", " ")
            )
            for path in sorted(company_folder.glob("*.pdf")):
                item = {"company": company, "filename": path.name}
                inputs.append(item)
                paths_by_key[(company, path.name)] = path

        if not inputs:
            return []

        prompt = DOCUMENT_FILENAME_VALIDATION_PROMPT.format(
            current_year=datetime.now().year,
            previous_year=datetime.now().year - 1,
            documents_json=json.dumps(inputs, ensure_ascii=False, indent=2),
        )
        try:
            response = Gemini_Client().call_gemini_structured_json(
                DocumentFilenameValidationResponse,
                prompt,
                pdfs_dir=None,
            )
        except Exception as error:
            LOGGER.exception("Gemini filename validation failed: %s", error)
            return []

        reviewed_keys = set()
        flagged_documents = []
        for decision in response.get("documents", []):
            key = (decision.get("company"), decision.get("filename"))
            path = paths_by_key.get(key)
            if path is None or key in reviewed_keys:
                LOGGER.warning("Gemini returned an unknown or duplicate file: %s", key)
                continue
            reviewed_keys.add(key)
            is_explicit = decision.get("is_explicitly_incorrect") is True
            is_possible = decision.get("possibly_incorrect") is True
            if is_explicit or is_possible:
                flagged_documents.append({
                    "location": str(path.parent.resolve()),
                    "document_name": path.name,
                    "is_explicitly_incorrect": is_explicit,
                    "possibly_incorrect": is_possible,
                    "missing_data": False,
                    "reason": decision.get("reason", "no reason supplied"),
                })
                flag_type = "explicitly" if is_explicit else "possibly"
                LOGGER.warning(
                    "%s: flagged %s incorrect report %s (%s); "
                    "file was retained",
                    key[0],
                    flag_type,
                    key[1],
                    decision.get("reason", "no reason supplied"),
                )

        missing_reviews = set(paths_by_key) - reviewed_keys
        for company, filename in sorted(missing_reviews):
            LOGGER.warning(
                "%s: Gemini did not review %s; file was retained and was not "
                "flagged",
                company,
                filename,
            )
        return sorted(
            flagged_documents,
            key=lambda item: (item["location"], item["document_name"]),
        )

    def get_sens_data(
            self,
            company_name=None,
            base_dir=Path(__file__).resolve().parents[2] / "data" / "downloads",
    ):
        """Incrementally scrape SENS PDFs from the last saved record to now."""
        if company_name is None:
            return [
                self.get_sens_data(company, base_dir)
                for company in self.INVESTOR_URLS
            ]

        sens_folder = (
            Path(base_dir) / self.__clean_filename(company_name) / "SENS"
        )
        sens_folder.mkdir(parents=True, exist_ok=True)

        issuer_ids = self.__find_jse_issuer_ids(company_name)
        if not issuer_ids:
            LOGGER.warning("%s: could not find a matching JSE issuer", company_name)
            return []

        records_path = sens_folder / "announcements.json"
        saved_records = self.__load_sens_records(records_path, company_name)

        current_year = datetime.now().year
        saved_timestamps = [
            self.__sens_timestamp(record.get("AcknowledgeDateTime", ""))
            for record in saved_records
        ]
        saved_timestamps = [timestamp for timestamp in saved_timestamps if timestamp]
        if saved_timestamps:
            # Query the last saved day inclusively. The JSE endpoint accepts
            # dates rather than an announcement cursor, and inclusion avoids
            # missing another announcement published later on the same day.
            last_saved_date = datetime.fromtimestamp(
                max(saved_timestamps)
            ).date()
            start_date = min(last_saved_date, datetime.now().date()).isoformat()
        else:
            start_date = f"{current_year - 1}-01-01"
        end_date = datetime.now().date().isoformat()
        LOGGER.info(
            "%s: scraping JSE SENS announcements for %s to %s",
            company_name,
            start_date,
            end_date,
        )
        new_records = []
        for issuer_id in issuer_ids:
            payload = {
                "from": f"{start_date}T00:00:00.000Z",
                "to": f"{end_date}T23:59:59.999Z",
                "issuerMasterId": issuer_id,
            }
            response = self.__post_jse(
                "/_vti_bin/JSE/SENSService.svc/GetSensAnnouncementForDates",
                payload,
            )
            data = response.json()
            new_records.extend(
                data.get("GetSensAnnouncementForDatesResult") or []
            )

        records = saved_records + new_records
        records = list({
            record.get("AnnouncementId")
            or record.get("AnnouncementReferenceNumber")
            or record.get("PDFPath"): record
            for record in records
        }.values())
        records.sort(
            key=lambda record: self.__sens_timestamp(
                record.get("AcknowledgeDateTime", "")
            ),
            reverse=True,
        )

        records_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        downloaded = 0
        for record in records:
            pdf_url = record.get("PDFPath")
            if not pdf_url:
                continue
            date = datetime.fromtimestamp(
                self.__sens_timestamp(record.get("AcknowledgeDateTime", ""))
            ).strftime("%Y-%m-%d")
            reference = record.get("AnnouncementReferenceNumber", "SENS")
            headline = self.__clean_filename(
                record.get("FlashHeadline", "")
            )[:150].rstrip("_.-")
            filename = self.__clean_filename(
                f"{date}__{reference}__{headline or 'announcement'}.pdf"
            )
            output_path = sens_folder / filename
            if output_path.exists():
                downloaded += 1
                continue
            try:
                self.__download_file(pdf_url, output_path)
                downloaded += 1
            except requests.RequestException as error:
                LOGGER.warning(
                    "%s: failed SENS announcement %s: %s",
                    company_name,
                    reference,
                    error,
                )

        LOGGER.info(
            "%s: saved %d of %d SENS announcements to %s",
            company_name,
            downloaded,
            len(records),
            sens_folder,
        )
        return records

    def __load_sens_records(self, records_path, company_name):
        """Load previously saved SENS metadata, falling back to a full window."""
        if not records_path.exists():
            return []
        try:
            records = json.loads(records_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            LOGGER.warning(
                "%s: could not read saved SENS metadata; using the default "
                "date window: %s",
                company_name,
                error,
            )
            return []
        if not isinstance(records, list):
            LOGGER.warning(
                "%s: saved SENS metadata is not a list; using the default "
                "date window",
                company_name,
            )
            return []
        return [record for record in records if isinstance(record, dict)]

    def __post_jse(self, path, payload=None):
        headers = dict(self.HEADERS)
        headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Referer": JSE_SENS_URL,
        })
        endpoint = urljoin(JSE_SENS_URL, path)
        try:
            response = requests.post(
                endpoint, headers=headers, json=payload, timeout=60
            )
        except requests.exceptions.ReadTimeout:
            LOGGER.warning("JSE request timed out; retrying once")
            response = requests.post(
                endpoint, headers=headers, json=payload, timeout=120
            )
        response.raise_for_status()
        return response

    def __find_jse_issuer_ids(self, company_name):
        if not hasattr(self, "_jse_issuers"):
            response = self.__post_jse(
                "/_vti_bin/JSE/CustomerRoleService.svc/GetAllIssuersNoFilter"
            )
            self._jse_issuers = (
                response.json().get("GetAllIssuersNoFilterResult") or []
            )

        current_issuers = [
            issuer for issuer in self._jse_issuers
            if issuer.get("ExchangeCode") == "JSE"
            and issuer.get("Status") == "Current"
        ]
        ticker = JSE_COMPANY_CODES.get(company_name)
        ticker_matches = [
            issuer for issuer in current_issuers
            if ticker and ticker in {
                issuer.get("AlphaCode"), issuer.get("CustomerAlphaCode")
            }
        ]
        if ticker_matches:
            return sorted({issuer["MasterID"] for issuer in ticker_matches})

        company_words = self.__issuer_words(company_name)
        name_matches = [
            issuer for issuer in current_issuers
            if company_words == self.__issuer_words(issuer.get("LongName", ""))
        ]
        return sorted({issuer["MasterID"] for issuer in name_matches})

    def __issuer_words(self, name):
        ignored = {
            "limited", "ltd", "plc", "n", "nv", "proprietary", "pty"
        }
        return {
            word for word in re.findall(r"[a-z0-9]+", name.lower())
            if word not in ignored
        }

    def __sens_timestamp(self, value):
        match = re.search(r"Date\((\d+)", value)
        return int(match.group(1)) / 1000 if match else 0




    def __clean_filename(self, name: str) -> str:
        name = re.sub(r"[^\w\-_. ]", "", name)
        return name.strip().replace(" ", "_")

    def __find_relevant_documents(self, url: str, _visited=None, _depth=0) -> list[dict]:
        """
        Scrapes a url to find links to the relevant pdf files

        Params:
            url
        
        Returns:
            list[dict]: Relevant PDF links and their document classifications
        """
        if _visited is None:
            _visited = set()
        if url in _visited:
            return []
        _visited.add(url)

        res = self.__get(url, timeout=15)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")
        is_json = "application/json" in res.headers.get("Content-Type", "")

        matches = []
        pages_to_follow = []

        def add_matches(href, text):
            parsed_href = urlparse(href)

            # Viewer links return HTML. Use their underlying PDF directly.
            if parsed_href.path.lower().endswith("pdf-viewer.aspx"):
                source = parse_qs(parsed_href.query).get("src", [])
                if source:
                    href = urljoin(href, source[0])
                    parsed_href = urlparse(href)

            # Transcripts, scripts and Q&A packs are supporting material, not
            # the result/report documents this collector is intended to save.
            path = parsed_href.path.lower()
            if any(part in path for part in (
                "q-and-a", "q&a", "transcript", "results-script",
                "acquisition", "pro-forma",
            )):
                return

            combined = f"{text} {href}".lower()

            for document_type, keywords in self.KEYWORDS.items():
                if (document_type == "interim_results"
                        and "presentation" in combined):
                    continue
                score = self.__score_document(combined, keywords)

                if score > 0:
                    matches.append({
                        "type": document_type,
                        "url": href,
                        "link_text": text,
                        "score": score,
                    })

            if re.search(r"(?:^|[-_/])(?:iar|ir)(?:[-_.])", path):
                matches.append({
                    "type": "annual_report",
                    "url": href,
                    "link_text": text,
                    "score": 1,
                })

        for link in ([] if is_json else soup.find_all("a", href=True)):
            href = urljoin(url, link["href"])
            text = link.get_text(" ", strip=True)
            combined = f"{text} {href}".lower()

            # Some sites use extensionless download endpoints.
            if (".pdf" in combined or re.search(r"\bpdf\b", text.lower())
                    or "/download/" in urlparse(href).path):
                add_matches(href, text)
            elif _depth == 0 and self.__score_document(
                    combined, sum(self.KEYWORDS.values(), [])) > 0:
                pages_to_follow.append(href)

        # WordPress media APIs provide structured titles and source URLs. Use
        # those pairs directly so neighbouring JSON records cannot contaminate
        # one another's classification.
        if is_json:
            try:
                records = res.json()
            except requests.exceptions.JSONDecodeError:
                records = []
            if isinstance(records, list):
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    source_url = record.get("source_url")
                    title = record.get("title", {})
                    if isinstance(title, dict):
                        title = title.get("rendered", "")
                    if source_url and ".pdf" in source_url.lower():
                        add_matches(source_url, BeautifulSoup(
                            str(title), "html.parser"
                        ).get_text(" ", strip=True))

        # ShareData renders downloads as JavaScript-powered spans instead of
        # anchors. The first GlossyDownload argument is the document URL.
        for link in soup.find_all(attrs={"onclick": re.compile(r"GlossyDownload\(")}):
            onclick = link.get("onclick", "")
            target = re.search(r'''GlossyDownload\(\s*["']([^"']+)["']''', onclick)
            if target:
                add_matches(
                    urljoin(res.url, html.unescape(target.group(1))),
                    link.get_text(" ", strip=True),
                )

        # A few investor sites keep their document feed in an iframe.
        if _depth == 0:
            pages_to_follow.extend(
                urljoin(res.url, frame["src"])
                for frame in soup.find_all("iframe", src=True)
            )

        # Valterra and similar WordPress templates render report records as
        # JavaScript objects. Pair each file with its own title; using a fixed
        # slice around the URL can pick up the shared image's upload year and
        # mislabel old Anglo American Platinum reports as current reports.
        structured_pdf_urls = set()
        javascript_title = re.compile(
            r'''(?is)["']title["']\s*:\s*(?:'''
            r'''"(?P<double>(?:\\.|[^"\\])*)"|'''
            r''''(?P<single>(?:\\.|[^'\\])*)')'''
        )
        javascript_file_link = re.compile(
            r'''(?is)["']file_link["']\s*:\s*(?:'''
            r'''"(?P<double>(?:\\.|[^"\\])*)"|'''
            r''''(?P<single>(?:\\.|[^'\\])*)')'''
        )
        if not is_json:
            # Scan each title-delimited section once. The previous expression
            # searched from every `title` to a later `file_link`, causing
            # catastrophic backtracking on pages such as Glencore's, which
            # contain many title fields but no file_link records.
            title_records = list(javascript_title.finditer(res.text))
            for index, record in enumerate(title_records):
                section_end = (
                    title_records[index + 1].start()
                    if index + 1 < len(title_records)
                    else len(res.text)
                )
                file_link = javascript_file_link.search(
                    res.text, record.end(), section_end
                )
                if file_link is None:
                    continue
                raw_title = record.group("double") or record.group("single")
                raw_href = (
                    file_link.group("double") or file_link.group("single")
                )
                title = BeautifulSoup(
                    html.unescape(raw_title), "html.parser"
                ).get_text(" ", strip=True)
                href = urljoin(
                    res.url, html.unescape(raw_href).replace(r"\/", "/")
                )
                if ".pdf" not in urlparse(href).path.lower():
                    continue
                structured_pdf_urls.add(href)
                add_matches(href, title)

        # WordPress/AEM pages often put file links in JSON or component data
        # rather than in an anchor element.
        embedded_pdf = re.compile(
            r'''(?i)(?:https?:)?//[^\s"'<>\\]+\.pdf[^\s"'<>\\]*'''
            r'''|(?:/|[\w.~-]+/)[^\s"'<>\\]+\.pdf[^\s"'<>\\]*'''
        )
        if not is_json:
            for found in embedded_pdf.finditer(res.text):
                raw_href = html.unescape(found.group()).replace(r"\/", "/")
                base_url = (
                    urljoin(res.url, "/")
                    if urlparse(res.url).path.endswith(".js")
                    else res.url
                )
                href = urljoin(base_url, raw_href)
                if href in structured_pdf_urls:
                    continue
                start = max(0, found.start() - 150)
                context = BeautifulSoup(
                    res.text[start:found.end() + 50], "html.parser"
                ).get_text(" ", strip=True)
                add_matches(href, context)

        found_types = {match["type"] for match in matches}
        missing_types = set(self.KEYWORDS) - found_types

        # Follow landing pages only when direct/embedded links did not already
        # cover every requested type. Without this guard, pages such as Sanlam's
        # cause hundreds of unnecessary sequential requests.
        if (_depth == 0 and missing_types
                and "sharedata.co.za" not in (urlparse(url).hostname or "")):
            page_extensions = {"", ".html", ".htm", ".php", ".aspx"}
            ignored_hosts = {
                "facebook.com", "www.facebook.com",
                "linkedin.com", "www.linkedin.com",
                "twitter.com", "www.twitter.com",
                "googletagmanager.com", "www.googletagmanager.com",
            }
            unique_pages = list(dict.fromkeys(
                urldefrag(page_url).url
                for page_url in pages_to_follow
                if Path(urlparse(page_url).path).suffix.lower() in page_extensions
                and urlparse(page_url).hostname not in ignored_hosts
            ))[:10]
            LOGGER.info(
                "Found %d candidates on %s; following %d pages for missing types: %s",
                len(matches),
                url,
                len(unique_pages),
                ", ".join(sorted(missing_types)),
            )
            for page_url in unique_pages:
                if page_url.startswith(("http://", "https://")):
                    try:
                        matches.extend(self.__find_relevant_documents(
                            page_url, _visited, _depth + 1
                        ))
                    except requests.RequestException as error:
                        LOGGER.warning("Could not inspect %s: %s", page_url, error)
                        continue

        def sort_key(match):
            years = self.__document_years(match)
            return max(years, default=0), match["score"]

        unique = { (match["type"], match["url"]): match for match in matches }
        documents = sorted(unique.values(), key=sort_key, reverse=True)
        if _depth == 0:
            LOGGER.info(
                "Discovery complete for %s: %d candidates across %s",
                url,
                len(documents),
                ", ".join(sorted({doc["type"] for doc in documents})) or "no types",
            )
        return documents

    def __download_file(self, url: str, output_path: Path):
        current_url = url

        # WordPress Download Manager and AspenShare return HTML landing pages
        # whose real download URL is stored in a data attribute.
        for _ in range(3):
            res = self.__get(current_url, timeout=60)
            res.raise_for_status()

            if res.content.startswith(b"%PDF-"):
                output_path.write_bytes(res.content)
                return

            soup = BeautifulSoup(res.text, "html.parser")
            download = soup.find(attrs={"data-downloadurl": True})
            attribute = "data-downloadurl"
            if download is None:
                download = soup.select_one("a.download[data-link]")
                attribute = "data-link"

            if download is None:
                break

            current_url = urljoin(
                res.url,
                html.unescape(download[attribute]),
            )
            LOGGER.info("Resolved document landing page to %s", current_url)

        raise requests.RequestException(
            f"Expected a PDF, got {res.headers.get('Content-Type', 'unknown content')}"
        )

    def __score_document(self, text, keywords):
        """
        Scores how well a document matches the keywords
        """

        text = text.lower()
        score = 0

        for keyword in keywords:
            if keyword in text:
                score += len(keyword.split())

        return score

    def __document_years(self, document):
        title_years = {
            int(year) for year in re.findall(
                r"(?<!\d)(?:19|20)\d{2}(?!\d)",
                document.get("link_text", ""),
            )
        }
        if title_years:
            return title_years

        # WordPress upload folders describe when a file was migrated/uploaded,
        # not its reporting period (for example /uploads/2026/05/iar-2021.pdf).
        url = re.sub(
            r"/uploads/(?:19|20)\d{2}/\d{2}/", "/uploads/", document["url"]
        )
        return {
            int(year) for year in re.findall(
                r"(?<!\d)(?:19|20)\d{2}(?!\d)", url
            )
        }

    def __recent_saved_types(self, company_folder):
        """Return report types whose filenames prove that they are recent."""
        accepted_years = {datetime.now().year, datetime.now().year - 1}
        recent_types = set()
        for path in company_folder.glob("*.pdf"):
            parts = path.name.split("__", 2)
            if len(parts) != 3:
                continue
            document_type, labelled_year, original_name = parts
            try:
                labelled_year = int(labelled_year)
            except ValueError:
                continue
            source_years = {
                int(year)
                for year in re.findall(
                    r"(?<!\d)(?:19|20)\d{2}(?!\d)", original_name
                )
            }
            # A conflicting source year exposes files previously mislabeled
            # from a WordPress upload-directory year. Do not let those files
            # block discovery of the real recent report.
            if source_years and labelled_year not in source_years:
                continue
            if (document_type in self.KEYWORDS
                    and labelled_year in accepted_years):
                recent_types.add(document_type)
        return recent_types

    def __crawl4ai_documents(self, urls, wanted_types):
        """Use a rendered browser crawl to discover otherwise hidden PDFs."""
        if not urls or not wanted_types:
            return []

        async def crawl():
            browser_config = BrowserConfig(headless=True, verbose=False)
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=60000,
                scan_full_page=True,
            )
            documents = []
            queued = list(dict.fromkeys(urls))
            visited = set()
            async with AsyncWebCrawler(config=browser_config) as crawler:
                while queued and len(visited) < 20:
                    page_url = queued.pop(0)
                    if page_url in visited:
                        continue
                    visited.add(page_url)
                    result = await crawler.arun(url=page_url, config=run_config)
                    if not result.success:
                        LOGGER.warning(
                            "Crawl4AI could not render %s: %s",
                            page_url,
                            getattr(result, "error_message", "unknown error"),
                        )
                        continue

                    page_links = []
                    for group in (getattr(result, "links", {}) or {}).values():
                        if isinstance(group, list):
                            page_links.extend(group)
                    for link in page_links:
                        if not isinstance(link, dict):
                            continue
                        href = urljoin(page_url, link.get("href", ""))
                        text = " ".join(filter(None, (
                            link.get("text", ""), link.get("title", "")
                        )))
                        combined = f"{text} {href}".lower()
                        if ".pdf" in combined or "/download/" in urlparse(href).path:
                            for document_type in wanted_types:
                                score = self.__score_document(
                                    combined, self.KEYWORDS[document_type]
                                )
                                if score:
                                    documents.append({
                                        "type": document_type,
                                        "url": href,
                                        "link_text": text,
                                        "score": score,
                                    })
                        elif (urlparse(href).hostname == urlparse(page_url).hostname
                              and self.__score_document(
                                  combined,
                                  sum((self.KEYWORDS[k] for k in wanted_types), []),
                              ) > 0):
                            queued.append(urldefrag(href).url)
            return documents

        # This method is also called from notebooks, where an asyncio loop is
        # already running. A dedicated thread keeps the synchronous public API
        # safe in both scripts and notebooks.
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(crawl())).result()

    def _scrape_investor_documents(self, company_name: str, investor_urls,
                                   base_dir = Path(__file__).resolve().parents[2]/"data"/"downloads"):
        """
        Scrape documents for a specific company.

        Saves files to base_dir/<company> and scrapes from investor_url
        """

        company_folder = Path(base_dir) / self.__clean_filename(company_name)
        company_folder.mkdir(parents=True, exist_ok=True)

        if isinstance(investor_urls, str):
            investor_urls = [investor_urls]

        def sort_key(document):
            years = self.__document_years(document)
            return max(years, default=0), document["score"]

        complete_types = self.__recent_saved_types(company_folder)
        # Discovery still checks every type that is already complete. That is
        # how a newly published report supersedes a valid prior-year file.
        # ``handled_types`` prevents lower-ranked candidates of the same type
        # from being downloaded once the newest candidate is present.
        handled_types = set()
        accepted_years = {datetime.now().year, datetime.now().year - 1}
        responsive_urls = set()

        def discover(urls):
            discovered = []
            for investor_url in urls:
                try:
                    discovered.extend(self.__find_relevant_documents(investor_url))
                    responsive_urls.add(investor_url)
                except requests.RequestException as error:
                    LOGGER.warning(
                        "%s: could not scrape source %s: %s",
                        company_name,
                        investor_url,
                        error,
                    )
            return sorted(
                {
                    (document["type"], document["url"]): document
                    for document in discovered
                }.values(),
                key=sort_key,
                reverse=True,
            )

        def download_candidates(documents):
            LOGGER.info(
                "%s: evaluating %d document candidates",
                company_name,
                len(documents),
            )
            for doc in documents:
                if doc["type"] in handled_types:
                    continue

                document_years = self.__document_years(doc)
                if not document_years.intersection(accepted_years):
                    LOGGER.info(
                        "%s: skipping stale or undated %s candidate%s",
                        company_name,
                        doc["type"],
                        f" from {max(document_years)}" if document_years else "",
                    )
                    continue

                original_name = Path(urlparse(doc["url"]).path).name
                if not original_name.lower().endswith(".pdf"):
                    original_name = f"{doc['type']}.pdf"

                report_year = max(document_years & accepted_years)
                filename = (
                    f"{doc['type']}__{report_year}__"
                    f"{self.__clean_filename(original_name)}"
                )
                output_path = company_folder / filename

                if output_path.exists():
                    LOGGER.info(
                        "%s: newest %s candidate is already saved as %s",
                        company_name,
                        doc["type"],
                        output_path,
                    )
                    handled_types.add(doc["type"])
                    complete_types.add(doc["type"])
                    continue

                try:
                    LOGGER.info(
                        "%s: trying %s candidate %s",
                        company_name,
                        doc["type"],
                        doc["url"],
                    )
                    self.__download_file(doc["url"], output_path)
                    LOGGER.info(
                        "%s: downloaded %s to %s",
                        company_name,
                        doc["type"],
                        output_path,
                    )
                    handled_types.add(doc["type"])
                    complete_types.add(doc["type"])
                except requests.RequestException as error:
                    LOGGER.warning(
                        "%s: failed %s candidate %s: %s",
                        company_name,
                        doc["type"],
                        doc["url"],
                        error,
                    )

        primary_urls = [
            url for url in investor_urls
            if "sharedata.co.za" not in (urlparse(url).hostname or "")
        ]
        fallback_urls = [
            url for url in investor_urls
            if "sharedata.co.za" in (urlparse(url).hostname or "")
        ]

        primary_docs = discover(primary_urls)
        download_candidates(primary_docs)

        if set(self.KEYWORDS) - complete_types and fallback_urls:
            LOGGER.info(
                "%s: primary sources incomplete; trying ShareData fallback",
                company_name,
            )
            fallback_docs = discover(fallback_urls)
            download_candidates(fallback_docs)

        missing_types = set(self.KEYWORDS) - complete_types
        if missing_types:
            if responsive_urls:
                LOGGER.info(
                    "%s: standard discovery incomplete; trying Crawl4AI for: %s",
                    company_name,
                    ", ".join(sorted(missing_types)),
                )
                crawl4ai_docs = self.__crawl4ai_documents(
                    sorted(responsive_urls), missing_types
                )
                download_candidates(sorted(
                    {
                        (document["type"], document["url"]): document
                        for document in crawl4ai_docs
                    }.values(),
                    key=sort_key,
                    reverse=True,
                ))
            else:
                LOGGER.warning(
                    "%s: all investor sources were unreachable; skipping "
                    "rendered-browser fallback",
                    company_name,
                )

        missing_types = set(self.KEYWORDS) - complete_types
        if missing_types:
            LOGGER.warning(
                "%s: finished with missing document types: %s",
                company_name,
                ", ".join(sorted(missing_types)),
            )
        else:
            LOGGER.info("%s: finished successfully", company_name)

        return missing_types

if __name__ == "__main__":
    my_collector = DataCollector()
    LOGGER.setLevel(logging.INFO)
    print(my_collector.scrape_and_save_reports())
