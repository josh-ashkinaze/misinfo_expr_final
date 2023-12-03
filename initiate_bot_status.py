import json
from google.cloud import bigquery
from google.oauth2 import service_account
from datetime import datetime
import logging
import os

LOG_FORMAT = '%(asctime)s %(levelname)s: %(message)s'
logging.basicConfig(filename=f'{os.path.basename(__file__)}.log', level=logging.INFO, format=LOG_FORMAT,
                    datefmt='%Y-%m-%d %H:%M:%S', filemode='w')


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


def insert_bots(credentials, bot_usernames):
    """
    Insert bot usernames into the BigQuery table with status 'success'.

    Args:
        credentials (google.oauth2.service_account.Credentials): BigQuery credentials.
        bot_usernames (list): List of bot usernames.
    """
    client = bigquery.Client(credentials=credentials, project=credentials.project_id)

    # Prepare the INSERT query
    table_id = "twitexpr.twit.bots"
    rows_to_insert = [
        {"bot_username": username, "status": "success", "dt": datetime.utcnow().isoformat()}
        for username in bot_usernames
    ]

    # Perform the insert operation
    errors = client.insert_rows_json(table_id, rows_to_insert)
    if errors == []:
        logging.info("Added bot data")
        print("New rows have been added.")
    else:
        print("Errors occurred while inserting rows: {}".format(errors))


def main():
    bg_credentials, twitter_usernames = load_credentials("secrets.json")
    insert_bots(bg_credentials, twitter_usernames)


if __name__ == "__main__":
    main()
