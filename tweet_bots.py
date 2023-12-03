import argparse
import logging
import os
import random
import requests
import time
from datetime import datetime
from bs4 import BeautifulSoup
import tweepy
import openai
import math
import json

# Set up logging
LOG_FORMAT = '%(asctime)s %(levelname)s: %(message)s'
logging.basicConfig(filename=f'{os.path.basename(__file__)}.log', level=logging.INFO, format=LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S', filemode='w')

# Load secrets
with open('secrets.json') as json_file:
    secrets = json.load(json_file)
os.environ['OPENAI_API_KEY'] = secrets["open_ai_key"]


def log_sleep(lower, upper):
    """
    Logs the sleep duration.

    Args:
        lower (float): The lower bound of the sleep duration.
        upper (float): The upper bound of the sleep duration.
    Returns
        float: The sleep duration.
    """
    amount = random.uniform(lower, upper)
    if amount > 3600:
        logging.info(f"Sleeping for {amount / 3600} hours")
    elif amount > 60:
        logging.info(f"Sleeping for {amount / 60} minutes")
    else:
        logging.info(f"Sleeping for {amount} seconds")
    return amount
def get_chatgpt_tweet(article_abstract):
    """
    Uses ChatGPT 3.5 to generate a tweet about a paper's abstract.

    Args:
        article_abstract (str): The abstract of the article.

    Returns:
        str: A tweet summarizing the article's abstract.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo-16k",
            messages=[
                {"role": "user", "content": "INSTRUCTIONS\nYou are a twitter account that blogs about academic research done by others. When given an abstract, write a 20 word tweet about this paper for a general audience.\nABSTRACT\n{}\nCONSTRAINTS\n-Do not use first person since another research group did the work\n- the entire tweet CANNOT exceed 20 words nor can it contain ANY hashtags \n-be engaging\n-do not use hashtags\n-do not exceed 20 words in your response.".format(article_abstract)}
            ],
            temperature=1,
            max_tokens=256,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        tweet = response.choices[0].message.content.strip("'")
        if len(tweet) <= 280:
            return tweet
    except Exception as e:
        logging.error(f"Error in get_chatgpt_tweet: {e}")
        return None

def parse_arxiv_urls():
    """
    Parses the arXiv page for misinformation preprints.

    Returns:
        list of dict: A list of dictionaries, each containing the `title`, `link`, and `abstract` of a paper.
    """
    article_data = []
    url = 'https://arxiv.org/search/?query=misinformation&searchtype=all&source=header'
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = soup.find_all('li', class_='arxiv-result')
        for article in articles:
            title = article.find('p', class_='title is-5 mathjax').text.strip()
            abstract = article.find('span', class_='abstract-full has-text-grey-dark mathjax').text.strip().replace("△ Less", "")
            link = article.find('p', class_='list-title is-inline-block').find('a')['href']
            article_data.append({'title': title, 'link': link, 'abstract': abstract})
    except Exception as e:
        logging.error(f"Error in parse_arxiv_urls: {e}")
    return article_data

def clean_chatgpt_tweet(chatgpt_tweet):
    """
    Cleans the tweet generated by ChatGPT.

    Args:
        chatgpt_tweet (str): The tweet generated by ChatGPT.

    Returns:
        str: A cleaned version of the tweet.
    """
    cleaned_tweet = ' '.join(chatgpt_tweet.split())
    if (cleaned_tweet.startswith("'") and cleaned_tweet.endswith("'")) or (cleaned_tweet.startswith('"') and cleaned_tweet.endswith('"')):
        cleaned_tweet = cleaned_tweet[1:-1]
    cleaned_tweet = ' '.join(word for word in cleaned_tweet.split() if not word.startswith('#'))
    return cleaned_tweet



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
        return "Successful"

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


def main(args):
    """
    Main function to run the script.

    Args:
        args: Command-line arguments.
    """
    N_PER_DAY = args.n_per_day
    SLEEP_DURATION = math.ceil(86400 / N_PER_DAY)
    twitter_accounts = secrets['twitter_accounts']
    MSGS_ATTEMPTED = 0

    while MSGS_ATTEMPTED < N_PER_DAY:
        try:
            logging.info(f"Starting tweet {MSGS_ATTEMPTED + 1} of {N_PER_DAY}")
            articles = parse_arxiv_urls()
            if not articles:
                raise ValueError("No articles fetched")

            to_tweet = random.choice(articles)
            abstract, title, link = to_tweet['abstract'], to_tweet['title'], to_tweet['link']
            chatgpt_tweet = clean_chatgpt_tweet(get_chatgpt_tweet(abstract))
            if not chatgpt_tweet:
                raise ValueError("ChatGPT tweet generation failed")

            chatgpt_tweet = f"{chatgpt_tweet}\nRead more: {link}"
            for account in twitter_accounts:
                account_info = twitter_accounts[account]
                logging.info(f"Tweeting from {account_info['username']}")
                time.sleep(random.uniform(args.short_sleep_min, args.short_sleep_max))
                post_tweet(account_info, chatgpt_tweet)
                MSGS_ATTEMPTED += 1

            long_sleep = log_sleep(lower=SLEEP_DURATION-args.long_sleep_noise, upper=SLEEP_DURATION + args.long_sleep_noise)
            time.sleep(long_sleep)
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
            time.sleep(60)  # Wait a minute before retrying

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tweet summarizer for academic papers")
    parser.add_argument('--n_per_day', type=int, default=35, help='Number of tweets per day')
    parser.add_argument('--short_sleep_min', type=float, default=60*5, help='Minimum short sleep duration in seconds')
    parser.add_argument('--short_sleep_max', type=float, default=60*10, help='Maximum short sleep duration in seconds')
    parser.add_argument('--long_sleep_noise', type=float, default=60*20, help='Noise for long sleep duration in seconds')
    args = parser.parse_args()
    main(args)