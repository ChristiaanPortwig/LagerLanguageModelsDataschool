import os
from dotenv import load_dotenv
from google import genai
from ..config.gemini_structured_schemas import (CompanyLevelExtDataResponse, SENSEventsResponse)
import base64
from pathlib import Path
import logging

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

load_dotenv()

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

    def call_gemini_structured(self, schema_class, prompt, pdfs_dir: str | None, 
                               model = "gemini-3.5-flash-lite",
                               response_format_type = "text", 
                               response_format_mime_type = "application/json"):
        """
        Makes a call to gemini, expecting structured output, defaults to json
        Params:
            schema_class: Class defining the output schema
            pdfs_dir: The directory in which pdfs are to load into chat, if left none, no pdfs
            will be uploaded

        Return:
            Structured output in defined format
        """

        #Find pdfs
        model_input = []
        if pdfs_dir:
            directory = Path(pdfs_dir)
            pdf_paths = list(directory.glob("*.pdf"))
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
            response_format={
                "type" : response_format_type,
                "mime_type" : response_format_mime_type,
                "schema" : schema_class.model_json_schema()
            },
        )

        response = schema_class.model_validate_json(interaction.output_text)
        return response


if __name__ == "__main__":
    #NOTE: Main method only tests basic functionality due to very limited API credits.
    my_client = Gemini_Client()
    my_client.call_gemini("This is a test, respond with something cool")
