import time
import datetime
import requests
from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import alpaca_trade_api as tradeapi
import logging
import os

# === CONFIG ===
TICKERS = {
    "AAPL": "Apple",
    "JNJ": "Johnson & Johnson",
    "XOM": "Exxon Mobil",
    "JPM": "JPMorgan Chase",
    "PG": "Procter & Gamble",
    "BA": "Boeing",
    "NVDA": "NVIDIA",
    "HD": "Home Depot",
    "KO": "Coca-Cola",
    "PFE": "Pfizer",
    "CVX": "Chevron",
    "V": "Visa",
    "TSLA": "Tesla",
    "META": "Meta Platforms",
    "MSFT": "Microsoft",
    "UNH": "UnitedHealth Group",
    "CAT": "Caterpillar",
    "WMT": "Walmart",
    "T": "AT&T"
}

ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
MAX_POSITION_PCT = 0.1       # Max 10% of portfolio in any single stock
MAX_TOTAL_INVESTMENT_PCT = 0.8  # Only invest up to 80% of total cash
BUY_THRESHOLDS = [(0.35, 10), (0.25, 5), (0.175, 2)]  # (sentiment score, shares)
SELL_THRESHOLDS = -0.175  # Add at top


# === SETUP ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
analyzer = SentimentIntensityAnalyzer()
alpaca = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, base_url=ALPACA_BASE_URL)

# === HELPER FUNCTIONS ===
def get_google_news_headlines(company_name, num_articles=15):
    query = company_name.replace(" ", "+")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    response = requests.get(rss_url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch news for {company_name}: HTTP {response.status_code}")
    soup = BeautifulSoup(response.content, features="xml")
    items = soup.find_all("item")
    return [item.title.text for item in items[:num_articles]]

def analyze_sentiment(headlines):
    if not headlines:
        return 0
    scores = [analyzer.polarity_scores(h)['compound'] for h in headlines]
    return sum(scores) / len(scores)

def decide_quantity(score):
    for threshold, qty in BUY_THRESHOLDS:
        if score >= threshold:
            return qty
    return 0

def get_position_value(ticker, current_price):
    try:
        position = alpaca.get_position(ticker)
        return float(position.qty) * current_price
    except:
        return 0  # No position

def get_current_price(ticker):
    barset = alpaca.get_latest_trade(ticker)
    return float(barset.price)

def get_available_cash():
    account = alpaca.get_account()
    return float(account.cash), float(account.portfolio_value)

def place_order(ticker, qty):
    try:
        alpaca.submit_order(symbol=ticker, qty=qty, side='buy', type='market', time_in_force='gtc')
        logging.info(f"Placed BUY order: {qty} shares of {ticker}")
    except Exception as e:
        logging.error(f"Order failed for {ticker}: {e}")

# === MAIN LOOP ===
def run_sentiment_trader():
    cash_available, portfolio_value = get_available_cash()
    max_total_to_invest = portfolio_value * MAX_TOTAL_INVESTMENT_PCT
    total_invested = 0

    logging.info(f"Portfolio Value: ${portfolio_value:.2f}, Cash: ${cash_available:.2f}")

    for ticker, name in TICKERS.items():
        try:
            headlines = get_google_news_headlines(name)
            sentiment_score = analyze_sentiment(headlines)
            logging.info(f"{ticker} Sentiment Score: {sentiment_score:.3f}")

            price = get_current_price(ticker)
            try:
                position = alpaca.get_position(ticker)
                current_qty = int(float(position.qty))
            except:
                current_qty = 0  # No current position

            # === SELL if sentiment is very negative and position exists ===
            if sentiment_score <= SELL_THRESHOLDS and current_qty > 0:
                try:
                    alpaca.submit_order(
                        symbol=ticker,
                        qty=current_qty,
                        side='sell',
                        type='market',
                        time_in_force='gtc'
                    )
                    logging.info(f"Placed SELL order: {current_qty} shares of {ticker} due to negative sentiment.")
                except Exception as e:
                    logging.error(f"Sell failed for {ticker}: {e}")
                continue  # Skip to next stock after selling

            # === BUY if sentiment is strong ===
            qty = decide_quantity(sentiment_score)
            if qty == 0:
                logging.info(f"{ticker} sentiment not strong enough to buy. Skipping.")
                continue

            position_value = current_qty * price
            proposed_value = qty * price

            if position_value + proposed_value > portfolio_value * MAX_POSITION_PCT:
                logging.info(f"{ticker} position exceeds max allocation. Skipping.")
                continue

            if total_invested + proposed_value > max_total_to_invest:
                logging.info("Total portfolio investment limit reached.")
                break

            place_order(ticker, qty)
            total_invested += proposed_value

            time.sleep(2)  # Short pause between orders

        except Exception as e:
            logging.error(f"Error with {ticker}: {e}")

if __name__ == "__main__":
    try:
        run_sentiment_trader()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
