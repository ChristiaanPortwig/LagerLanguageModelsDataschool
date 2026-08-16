# Lager Language Models submission code explanation

Thank you for taking the time to review our code, we appreciate it. Everything should be intuitive. 
The goal of this document is to give instructions about **run_local.sh**

Usually, backend would run in a docker container. This enables web scraping and document processing 
to happen periodically.

The problem with this is, that gemini API keys are needed. To counter this, run_local.sh downloads 
pre-processes data.

Running this shell script launches our fastapi backend on http://localhost:4000/, but more 
importantly, it launches our frontend on **http://localhost:5173/**. Obviously its not fully 
functional, but you can see everything needed to judge (e.g. report generation won't work),