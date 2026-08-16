# Lager Language Models submission code explanation

Thank you for taking the time to review our code, we appreciate it. Everything should be intuitive. 
The goal of this document is to give instructions about **run_local.sh**

Usually, backend would run in a docker container. This enables web scraping and document processing 
to happen periodically.

The problem with this is that Gemini API keys are needed. To counter this, run_local.sh downloads
pre-processed data and the three pre-generated reports for the highest-scoring companies.

Running this shell script launches our fastapi backend on http://localhost:4000/, but more 
importantly, it launches our frontend on **http://localhost:5173/**. Live report generation still
requires a Gemini API key, but some reports can be downloaded(might not be the correct file).
