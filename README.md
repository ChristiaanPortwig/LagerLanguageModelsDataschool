# LagerLanguageModelsDataschool
Repository for Data School Hackathon for team Lager Language Models

## Project Setup
Download the provided csv files and add it to the data directory

The financial-report collector uses Crawl4AI as its browser-rendered fallback.
Install and initialise it in the project environment before running collection:

```bash
.venv/bin/pip install -U crawl4ai
.venv/bin/crawl4ai-setup
```

## Citations
- OpenAI ChatGPT 5.6 for data collection
    - Assiting with the writing of data-collection.py. Especially web crawling.
    - Assisting with generating contant values, especially INVESTOR_URL. This provides us with
    optimal accuracy for web scraping, rather than trying to manually scrape these.

- OpenAI ChatGPT 5.6 for data processing:
    - Assists in researching fields to extract.
    - Writing JSON schemas in gemini_structured_schemas.py from a pre-defined attribute list.
