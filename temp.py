# import yfinance as yf

# # Example: Pull financial statements for FirstRand on the JSE
# ticker = yf.Ticker("FSR.JO")

# # Financial statements as Pandas DataFrames
# income_statement = ticker.financials
# balance_sheet = ticker.balance_sheet
# cash_flow = ticker.cashflow

# print(income_statement)

from backend.scripts.data_collection import DataCollector

my_collector = DataCollector(["NOOO"])

my_collector.scrape_and_save_pdfs()