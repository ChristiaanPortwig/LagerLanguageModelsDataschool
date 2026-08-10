import logging
import time
import pandas as pd
from pathlib import Path

from .gemini_client import Gemini_Client
from ..config.gemini_structured_schemas import (SENSEventsResponse, CompanyLevelExtDataResponse)
from ..config.prompts import (SENS_PROMPT, COMPANY_LEVEL_PROMPT)


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

class Data_Processor:
    """
    Processes data
    """

    def __init__(self):
        self.gemini_client = Gemini_Client()

    def extract_external_data_from_pdfs(self, source_dir = Path(__file__).resolve().parents[2] / 'data' / 'downloads') -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Extracts external data from the pdfs in each company directory in the source directory.

        Params:
            source_dir: str - The root source directory. Assumes structure from data_collection.py,
            where there is a SENS subdirectory in ever company's directory. This is set to
            data/downloads by default

        Returns:
            (curr_company_lvl_df, cur_sens_df)
        """

        company_dirs = [path for path in Path(source_dir).iterdir() if path.is_dir()]
        curr_company_df = pd.DataFrame()
        curr_sens_df = pd.DataFrame()

        for index, company_dir in enumerate(company_dirs):
            curr_company_lvl_json = self.gemini_client.call_gemini_structured_json(
                CompanyLevelExtDataResponse,
                COMPANY_LEVEL_PROMPT,
                company_dir,
            )

            curr_sens_json = self.gemini_client.call_gemini_structured_json(
                SENSEventsResponse,
                SENS_PROMPT,
                company_dir / "SENS",
            )

            company_df = pd.DataFrame(curr_company_lvl_json["records"])
            sens_df = pd.DataFrame(curr_sens_json["events"])
            curr_company_df = pd.concat([curr_company_df, company_df], ignore_index=True)
            curr_sens_df = pd.concat([curr_sens_df, sens_df], ignore_index=True)

            if index < len(company_dirs) - 1:
                time.sleep(60)

        return curr_company_df, curr_sens_df
            
