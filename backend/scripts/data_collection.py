from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from datetime import datetime
import html
import logging
import re
import requests
from bs4 import BeautifulSoup

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


class DataCollector:
    """Class used for collecting data from external sources"""

    KEYWORDS = {
            "annual_report": [
            "annual report",
            "integrated report",
            "annual integrated report",
            "annual results"
        ],
        "financial_statements": [
            "annual financial statements",
            "financial statements",
            "afs",
            "form 20-f",
        ],
        "interim_results": [
            "interim results",
            "half year results",
            "half-year results",
            "interim financial statements",
            "earnings release",
            "results"
        ],
        "results_presentation": [
            "results presentation",
            "annual results presentation",
            "interim results presentation",
            "earnings release presentation",
        ],
    }

    #TODO: This needs to be semi automated... search for each keyword and then get URL that's matched most. Remember year
    INVESTOR_URLS = {
     "OUTsurance Group": "https://group.outsurance.co.za/results-and-reports/",
     "Bid Corporation": "https://www.bidcorpgroup.com/assets/js/archive-data.js",
     "MTN Group": "https://mtn-investor.com/fy-2025-reporting-suite/index.php",
     "Aspen Pharmacare": "https://www.aspenpharma.com/investor-relations/",
     "NEPI Rockcastle": "https://nepirockcastle.com/investors/financial-information/",
     "Pepkor Holdings": "https://pepkor.co.za/latest-financial-results/",
     "Naspers": "https://www.naspers.com/investors/results-reports-events",
     "The Bidvest Group": "https://bidvest.co.za/investor-relations",
     "Sanlam": "https://www.sanlam.com/financial-reporting.php",
     "Gold Fields": "https://www.goldfields.com/investor-overview.php",
     "Clicks Group": "https://www.clicksgroup.co.za/results/",
     "Anglo American": "https://www.angloamerican.com/investors/results-centre-and-presentations",
     "AngloGold Ashanti": "https://www.anglogoldashanti.com/investors/reporting/",
     "BHP Group": "https://www.bhp.com/investor-hub/reports-and-presentations/annual-report",
     "Shoprite Holdings": "https://www.shopriteholdings.co.za/shareholders-investors/reports-documents.html",
     "Valterra Platinum": "https://www.valterraplatinum.com/investor-centre/company-results-reports-presentations/",
     "Vodacom Group": "https://www.vodacom.com/annual-results.php",
     "Shaftesbury Capital plc": "https://www.shaftesburycapital.com/en/investors/results-reports-presentations.html",
     "Glencore": "https://www.glencore.com/publications",
     "Prosus": "https://www.prosus.com/investors/financial-information/results",
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

    # Shaftesbury's investor page is currently protected by a JavaScript proof-
    # of-work challenge. These are the same first-party files exposed by it.
    STATIC_DOCUMENTS = {
        INVESTOR_URLS["BHP Group"]: [
            (
                "Annual Report 2025 annual financial statements",
                "https://www.bhp.com/-/media/documents/investors/annual-reports/"
                "2025/250819_bhpannualreport2025.pdf",
            ),
            (
                "Interim Results 2026",
                "https://www.bhp.com/-/media/documents/media/"
                "reports-and-presentations/2026/"
                "260217_bhpresultsforthehalfyearended31dec2025_exchangerelease.pdf",
            ),
            (
                "Interim Results Presentation 2026",
                "https://www.bhp.com/-/media/documents/media/"
                "reports-and-presentations/2026/"
                "260217_bhpresultsforthehalfyearended31dec2025_presentation.pdf",
            ),
        ],
        INVESTOR_URLS["Shaftesbury Capital plc"]: [
            (
                "Annual Report 2025 annual financial statements",
                "https://www.shaftesburycapital.com/content/dam/shaftesbury/"
                "corporate/new-build/doucments/investor/annual-reports/"
                "annual-report-2025.pdf",
            ),
            (
                "Interim Results 2025",
                "https://www.shaftesburycapital.com/content/dam/shaftesbury/"
                "corporate/new-build/doucments/investor/results---reports/"
                "2025/interim-results-2025.pdf",
            ),
            (
                "Interim Results Presentation 2025",
                "https://www.shaftesburycapital.com/content/dam/shaftesbury/"
                "corporate/new-build/doucments/investor/results---reports/"
                "2025/interim-results-2025-presentation.pdf.downloadasset.pdf",
            ),
        ],
    }

    EXTRA_DOCUMENTS = {
        INVESTOR_URLS["Anglo American"]: [
            (
                "Integrated Annual Report 2025 annual financial statements",
                "https://www.angloamerican.com/~/media/Files/A/"
                "Anglo-American-Group-v9/PLC/investors/annual-reporting/"
                "2025/aa-annual-report-full-2025.pdf",
            ),
        ],
    }

    def __init__(self, companies_list):
        self.companies_list = companies_list

    def __get(self, url, timeout):
        LOGGER.info("Requesting %s (timeout=%ss)", url, timeout)
        try:
            return requests.get(url, headers=self.HEADERS, timeout=timeout)
        except requests.exceptions.ReadTimeout:
            LOGGER.warning(
                "Timed out reading %s; retrying with a %ss timeout",
                url,
                timeout * 2,
            )
            return requests.get(
                url, headers=self.HEADERS, timeout=timeout * 2
            )
        except requests.exceptions.SSLError:
            if urlparse(url).hostname not in {"goldfields.com", "www.goldfields.com"}:
                raise
            # Gold Fields currently serves an incomplete certificate chain.
            LOGGER.warning(
                "TLS verification failed for %s; retrying without verification",
                url,
            )
            return requests.get(
                url, headers=self.HEADERS, timeout=timeout, verify=False
            )

    def scrape_and_save_pdfs(self, save_location = Path(__file__).resolve().parents[2] / 'data' / 'downloads'):
        for company, URL in self.INVESTOR_URLS.items():
            LOGGER.info("Scraping %s", company)
            try:
                self._scrape_investor_documents(company, URL, save_location)
            except Exception as e:
                LOGGER.exception("Couldn't scrape %s: %s", company, e)
                continue




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

        if url in self.STATIC_DOCUMENTS:
            matches = []
            for text, href in self.STATIC_DOCUMENTS[url]:
                combined = f"{text} {href}".lower()
                for document_type, keywords in self.KEYWORDS.items():
                    score = self.__score_document(combined, keywords)
                    if score > 0:
                        matches.append({
                            "type": document_type,
                            "url": href,
                            "link_text": text,
                            "score": score,
                        })

            LOGGER.info(
                "Using %d direct first-party documents for %s",
                len(self.STATIC_DOCUMENTS[url]),
                url,
            )
            return sorted(
                matches,
                key=lambda match: match["score"],
                reverse=True,
            )

        res = self.__get(url, timeout=30)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")

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
            )):
                return

            combined = f"{text} {href}".lower()

            for document_type, keywords in self.KEYWORDS.items():
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

        for link in soup.find_all("a", href=True):
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

        # A few investor sites keep their document feed in an iframe.
        if _depth == 0:
            pages_to_follow.extend(
                urljoin(res.url, frame["src"])
                for frame in soup.find_all("iframe", src=True)
            )

        # WordPress/AEM pages often put file links in JSON or component data
        # rather than in an anchor element.
        embedded_pdf = re.compile(
            r'''(?i)(?:https?:)?//[^\s"'<>\\]+\.pdf[^\s"'<>\\]*'''
            r'''|(?:/|[\w.~-]+/)[^\s"'<>\\]+\.pdf[^\s"'<>\\]*'''
        )
        for found in embedded_pdf.finditer(res.text):
            raw_href = html.unescape(found.group()).replace(r"\/", "/")
            base_url = (
                urljoin(res.url, "/")
                if urlparse(res.url).path.endswith(".js")
                else res.url
            )
            href = urljoin(base_url, raw_href)
            start = max(0, found.start() - 400)
            context = BeautifulSoup(
                res.text[start:found.end() + 50], "html.parser"
            ).get_text(" ", strip=True)
            add_matches(href, context)

        for text, href in self.EXTRA_DOCUMENTS.get(url, []):
            add_matches(href, text)

        found_types = {match["type"] for match in matches}
        missing_types = set(self.KEYWORDS) - found_types

        # Follow landing pages only when direct/embedded links did not already
        # cover every requested type. Without this guard, pages such as Sanlam's
        # cause hundreds of unnecessary sequential requests.
        if _depth == 0 and missing_types:
            page_extensions = {"", ".html", ".htm", ".php", ".aspx"}
            unique_pages = [
                page_url
                for page_url in dict.fromkeys(pages_to_follow)
                if Path(urlparse(page_url).path).suffix.lower() in page_extensions
            ][:10]
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
            years = re.findall(r"\b(?:19|20)\d{2}\b", match["link_text"] + match["url"])
            return max(map(int, years), default=0), match["score"]

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

    def _scrape_investor_documents(self, company_name: str, investor_url: str, 
                                   base_dir = Path(__file__).resolve().parents[2]/"data"/"downloads"):
        """
        Scrape documents for a specific company.

        Saves files to base_dir/<company> and scrapes from investor_url
        """

        company_folder = Path(base_dir) / self.__clean_filename(company_name)
        company_folder.mkdir(parents=True, exist_ok=True)

        docs = self.__find_relevant_documents(investor_url)
        LOGGER.info("%s: evaluating %d document candidates", company_name, len(docs))

        downloaded_types = set()
        accepted_years = {datetime.now().year, datetime.now().year - 1}

        for doc in docs:
            #Download hightest score
            if doc["type"] in downloaded_types:
                continue

            document_years = {
                int(year)
                for year in re.findall(
                    r"\b(?:19|20)\d{2}\b",
                    doc["link_text"] + " " + doc["url"],
                )
            }
            if document_years and not document_years.intersection(accepted_years):
                LOGGER.info(
                    "%s: skipping stale %s candidate from %s",
                    company_name,
                    doc["type"],
                    max(document_years),
                )
                continue

            parsed = urlparse(doc["url"]) 

            original_name = Path(parsed.path).name

            if not original_name.lower().endswith(".pdf"):
                original_name = f"{doc['type']}.pdf"

            filename = f"{doc['type']}__{self.__clean_filename(original_name)}"
            output_path = company_folder / filename

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

                downloaded_types.add(doc["type"])

            except requests.RequestException as e:
                LOGGER.warning(
                    "%s: failed %s candidate %s: %s",
                    company_name,
                    doc["type"],
                    doc["url"],
                    e,
                )

        missing_types = set(self.KEYWORDS) - downloaded_types
        if missing_types:
            LOGGER.warning(
                "%s: finished with missing document types: %s",
                company_name,
                ", ".join(sorted(missing_types)),
            )
        else:
            LOGGER.info("%s: finished successfully", company_name)

        return docs

if __name__ == "__main__":
    my_collector = DataCollector(["NOOO"])
    LOGGER.setLevel(logging.INFO)
    my_collector.scrape_and_save_pdfs()
