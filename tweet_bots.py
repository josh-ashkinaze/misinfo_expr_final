import argparse
import logging
import os
import random
import time
from datetime import datetime
import tweepy
from google.cloud import bigquery
import math
import json

from helpers import log_sleep, get_chatgpt_tweet, parse_arxiv_urls, clean_chatgpt_tweet, load_credentials

# Set up logging
current_time = datetime.now().strftime('%Y_%m_%d__%H.%M.%S')
log_filename = f"{os.path.basename(__file__)}_{current_time}.log"
LOG_FORMAT = '%(asctime)s %(levelname)s: %(message)s'
logging.basicConfig(filename=log_filename, level=logging.INFO, format=LOG_FORMAT,
                    datefmt='%Y-%m-%d %H:%M:%S', filemode='w')

# Load secrets
with open('secrets.json') as json_file:
    secrets = json.load(json_file)

# Load credentials
BG_CREDS, TWITTER_USERNAMES = load_credentials("secrets.json")
BIGQUERY_CLIENT = bigquery.Client(credentials=BG_CREDS, project=BG_CREDS.project_id)
BOT_TABLE_ID = 'twitexpr.twit.bots'


def post_tweet(account_info, post_text):
    """
    Posts a tweet using the Twitter API.

    Args:
        account_info (dict): A dictionary containing the Twitter account's API keys and tokens.
        post_text (str): The text to be tweeted.

    Returns:
        str: Status message indicating the result of the tweet operation.
    """
    try:
        client = tweepy.Client(
            consumer_key=account_info["api_key"],
            consumer_secret=account_info["api_key_secret"],
            access_token=account_info["access_token"],
            access_token_secret=account_info["access_token_secret"]
        )

        client.create_tweet(text=post_text)
        logging.info("Tweet posted successfully.")
        return "success"

    except tweepy.Forbidden as e:
        logging.error(f"Forbidden error: {e}")
        return "Error: Forbidden (403)"

    except tweepy.Unauthorized as e:
        logging.error(f"Unauthorized error: {e}")
        return "Error: Unauthorized (401)"

    except tweepy.TooManyRequests as e:
        logging.error(f"Rate limit exceeded: {e}")
        return "Error: Rate limit exceeded (429)"

    except tweepy.BadRequest as e:
        logging.error(f"Bad request: {e}")
        return "Error: Bad Request (400)"

    except tweepy.NotFound as e:
        logging.error(f"Not found error: {e}")
        return "Error: Not Found (404)"

    except tweepy.TwitterServerError as e:
        logging.error(f"Twitter server error: {e}")
        return "Error: Server Error (5xx)"

    except tweepy.TweepyException as e:
        logging.error(f"Tweepy exception: {e}")
        return "Error: TweepyException"

    except Exception as e:
        logging.error(f"General error: {e}")
        return "Error: Other"


def log_bot_status(username, status):
    """
    Insert bot username and status into the BigQuery table.

    Args:
        username (str): The bot's Twitter username.
        status (str): The status of the bot.

    Logs:
        str: Status message indicating the result of the insert operation.
    """
    rows_to_insert = [
        {"bot_username": username, "status": status, "dt": datetime.utcnow().isoformat()}
    ]
    errors = BIGQUERY_CLIENT.insert_rows_json(BOT_TABLE_ID, rows_to_insert)
    if errors == []:
        logging.info("Added bot data")
    else:
        logging.info("Errors occurred while inserting rows: {}".format(errors))


def get_bot_statuses():
    """
    Fetches the last status of each bot

    Args
        None

    Returns
        dict: Dictionary of bot statuses with keys 'username', 'dt', and 'status'
    """
    query = f"""
        SELECT b.bot_username, b.status, b.dt
        FROM {BOT_TABLE_ID} b
        INNER JOIN (
            SELECT bot_username, MAX(dt) as latest_dt
            FROM {BOT_TABLE_ID}
            GROUP BY bot_username
        ) latest ON b.bot_username = latest.bot_username AND b.dt = latest.latest_dt
    """
    query_job = BIGQUERY_CLIENT.query(query)
    results = query_job.result()
    bots_status = {}
    for row in results:
        bots_status[row.bot_username] = {"username": row.bot_username, "dt": row.dt, "status": row.status}
    return bots_status


def parse_bot_statuses(bot_statuses, check_again_after=60 * 60 * 24):
    """
    Parse the bot statuses to determine which bots are alive.

    The logic is that if a bot status was last logged as successful, then it is alive.
    If a bot status was last logged as dead, then it is alive if it was last tried more than `check_again_after` seconds ago.

    Args:
        bot_statuses (dict): Dictionary of bot statuses.
        check_again_after (int, default=24h): Number of seconds after which to check a bot again if it was last logged as dead.

    Returns
        list: List of bot usernames that are alive.
    """
    alive_bots = []
    for bot in bot_statuses:
        info = bot_statuses[bot]

        # Alive if last action logged as successful
        if info['status'] == 'success':
            logging.info(f"Bot {info['username']} is alive")
            alive_bots.append(info['username'])

        # If last action was not succesful, let's see
        # if last unsuccessful action was a long time ago...we will try again
        else:
            logging.info(f"Bot {info['username']} was logged as dead with error code {info['status']} on {info['dt']}")
            if (datetime.utcnow() - info['dt']).total_seconds() > check_again_after:
                logging.info(
                    f"Bot {info['username']} was last tried more than {check_again_after / (60 * 60)} hours ago. Checking again.")
                alive_bots.append(info['username'])
            else:
                logging.info(f"Bot death of {info['username']} was too recent. Not checking again.")
    return alive_bots


def main(args):
    """
    Main function to run the script.

    Args:
        args: Command-line arguments.
    """
    logging.info(f"Starting up with args {args}")
    N_PER_DAY = args.n_per_day
    LONG_SLEEP_DURATION = math.ceil(86400 / N_PER_DAY)
    twitter_accounts = secrets['twitter_accounts']
    MSGS_ATTEMPTED = 0

    while MSGS_ATTEMPTED <= 2:

        # Get bot statuses
        bot_statuses = get_bot_statuses()
        alive_bot_usernames = parse_bot_statuses(bot_statuses)
        logging.info(f"Alive bots: {alive_bot_usernames}")
        alive_bot_info = {username: twitter_accounts[username] for username in alive_bot_usernames}

        try:
            # Scrape arxiv preprints for misinfo and post tweet
            logging.info(f"Starting tweet {MSGS_ATTEMPTED + 1} of {N_PER_DAY}")
            articles = parse_arxiv_urls()
            to_tweet = random.choice(articles)
            abstract, title, link = to_tweet['abstract'], to_tweet['title'], to_tweet['link']
            chatgpt_tweet = clean_chatgpt_tweet(get_chatgpt_tweet(abstract))
            chatgpt_tweet = f"{chatgpt_tweet}\nRead more: {link}"
            if not chatgpt_tweet:
                raise ValueError("ChatGPT tweet generation failed")

            for account in alive_bot_info:
                account_info = alive_bot_info[account]
                logging.info(f"Tweeting from {account_info['username']}")
                log_sleep(msg="Short sleep before this bot ChatGPT tweets.", lower=args.short_sleep_min,
                          upper=args.short_sleep_max)
                status = post_tweet(account_info, chatgpt_tweet)
                log_bot_status(account_info['username'], status)

            MSGS_ATTEMPTED += 1
            log_sleep(msg="Long sleep after all bots ChatGPT tweeted.",
                      lower=LONG_SLEEP_DURATION - args.long_sleep_noise,
                      upper=LONG_SLEEP_DURATION + args.long_sleep_noise)
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
            time.sleep(60)  # Wait a minute before retrying


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tweet summarizer for academic papers")
    parser.add_argument('--n_per_day', type=int, default=2, help='Number of tweets per day')
    parser.add_argument('--short_sleep_min', type=float, default=60 * 5, help='Minimum short sleep duration in seconds')
    parser.add_argument('--short_sleep_max', type=float, default=60 * 10,
                        help='Maximum short sleep duration in seconds')
    parser.add_argument('--long_sleep_noise', type=float, default=60 * 20,
                        help='Noise for long sleep duration in seconds')
    args = parser.parse_args()
    main(args)
