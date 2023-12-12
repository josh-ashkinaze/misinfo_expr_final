"""
Author: Joshua Ashkinaze
Date: 2023-12-03

Description: Helper functions for unfollowing project
"""
import json
import logging
import random
import requests
import time
from google.oauth2 import service_account
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime, timedelta
import yaml

with open('secrets.json') as json_file:
    secrets = json.load(json_file)

client = OpenAI(api_key=secrets["open_ai_key"])


# MISC FUNCTIONS
######################################
######################################
def log_sleep(msg, lower, upper):
    """
    Logs the sleep duration and the expected resume time.

    Args:
        msg (str): The message to be logged
        lower (float): The lower bound of the sleep duration.
        upper (float): The upper bound of the sleep duration.
    Returns
        float: The sleep duration.
    """
    if lower <= 0:
        logging.info("Alert! Lower bound is less than or equal to zero. Changing (lower, upper) to (60, 120)")
        lower, upper = 60, 120

    amount = random.uniform(lower, upper)

    # Calculate and format the resume time
    resume_time = datetime.now() + timedelta(seconds=amount)
    formatted_resume_time = resume_time.strftime('%Y-%m-%d %H:%M:%S')

    # Log the sleep duration and resume time
    if amount > 3600:
        logging.info(f"{msg}. Sleeping for {amount / 3600:.3f} hours. Will resume at {formatted_resume_time}")
    elif amount > 60:
        logging.info(f"{msg}. Sleeping for {amount / 60:.3f} minutes. Will resume at {formatted_resume_time}")
    else:
        logging.info(f"{msg}. Sleeping for {amount:.3f} seconds. Will resume at {formatted_resume_time}")

    time.sleep(amount)
    return amount


def read_config(file_path):
    with open(file_path, 'r') as file:
        yaml_file = yaml.safe_load(file)
        if yaml_file['is_test'] is False:
            raise ValueError("This script is not ready for production yet.")
        yaml_file['gpt_mod'] = int(1/yaml_file['gpt_percent'])
        yaml_file['short_sleep_seconds'] = yaml_file['short_sleep']*60
        yaml_file['short_sleep_noise_seconds'] = yaml_file['short_sleep_noise']*60
        yaml_file['long_sleep_noise_seconds'] = yaml_file['long_sleep_noise']*60
        return yaml_file
######################################
######################################


# DATABASE FUNCTIONS
######################################
######################################
def load_credentials(file_path):
    """
    Load credentials and Twitter account usernames from a JSON file.

    Args:
        file_path (str): Path to the JSON file.

    Returns:
        tuple: (BigQuery credentials, list of Twitter bot usernames)
    """
    with open(file_path, "r") as file:
        data = json.load(file)
        bg_credentials_info = data["bq_creds"]
        twitter_accounts = [data['twitter_accounts'][account]['username'] for account in data["twitter_accounts"]]
        bg_credentials = service_account.Credentials.from_service_account_info(bg_credentials_info)
        return bg_credentials, twitter_accounts
######################################
######################################




# CHATGPT FUNCTIONS
######################################
######################################
def get_chatgpt_tweet(article_abstract):
    """
    Uses ChatGPT 3.5 to generate a tweet about a paper's abstract.

    Args:
        article_abstract (str): The abstract of the article.

    Returns:
        str: A tweet summarizing the article's abstract.
    """
    try:
        response = client.chat.completions.create(model="gpt-3.5-turbo-16k",
        messages=[
            {"role": "user", "content": "INSTRUCTIONS\nYou are a twitter account that blogs about academic research done by others. When given an abstract, write a 20 word tweet about this paper for a general audience.\nABSTRACT\n{}\nCONSTRAINTS\n-Do not use first person since another research group did the work\n- the entire tweet CANNOT exceed 20 words nor can it contain ANY hashtags \n-be engaging\n-do not use hashtags\n-do not exceed 20 words in your response.".format(article_abstract)}
        ],
        temperature=1,
        max_tokens=256,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0)
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
######################################
######################################
