import os
from dotenv import load_dotenv
from google import genai
from backend.config.gemini_structured_schemas import (
    CompanyLevelExtDataResponse,
    SENSEventsResponse,
)
import base64
from pathlib import Path
import logging
import json

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

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

class Gemini_Client:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # TODO: Perhaps model can be changed to an enum
    def call_gemini_ustructured(self, prompt, model = "gemini-3.5-flash-lite"):
        """
        Make a call to gemini, not expecting structured output.

        Return:
            Output text
        """
        interaction = self.client.interactions.create(
            model = model,
            input = prompt
        )

        return interaction.output_text

    def call_gemini_structured_json(self, schema_class, prompt, pdfs_dir: str | None,
                               model = "gemini-3.5-flash-lite"):
        """
        Makes a call to gemini, expecting structured json output
        Params:
            schema_class: Class defining the output schema
            pdfs_dir: A PDF file or directory of PDFs to load into the chat. If
            left as None, no PDFs will be uploaded.

        Return:
            Output as json objects
        """

        #Find pdfs
        model_input = []
        if pdfs_dir:
            pdf_source = Path(pdfs_dir)
            pdf_paths = (
                [pdf_source]
                if pdf_source.is_file() and pdf_source.suffix.lower() == ".pdf"
                else list(pdf_source.glob("*.pdf"))
            )
            pdfs_bytes = []

            LOGGER.info(f"Pdf paths: {pdf_paths}")

            for path in pdf_paths:
                with open(path.resolve(), 'rb') as f:
                    pdfs_bytes.append(f.read())
        
            #Add pdfs to input
            model_input = [
                {
                    "type": "document",
                    "data": base64.b64encode(pdf_byte).decode('utf-8'),
                    "mime_type": "application/pdf"
                }
                for pdf_byte in pdfs_bytes
            ]

        #Add prompt to input
        model_input.append({"type": "text", "text": prompt})
        

        interaction = self.client.interactions.create(
            model=model,
            input=model_input,
            generation_config={"seed": 0},
            response_format={
                "type" : "text",
                "mime_type" : "application/json",
                "schema" : schema_class.model_json_schema()
            },
        )

        response = schema_class.model_validate_json(interaction.output_text)
        return json.loads(response.model_dump_json())


if __name__ == "__main__":
    #NOTE: Main method only tests basic functionality due to very limited API credits.
    my_client = Gemini_Client()
    my_client.call_gemini("This is a test, respond with something cool")
