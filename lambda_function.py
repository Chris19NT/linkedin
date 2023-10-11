import json
import requests
import feedparser
from bs4 import BeautifulSoup
import openai
from datetime import datetime, timedelta
import time
import os



# VARIABLES
openai.api_key = os.environ.get('openai_key', 'Default Value') # OPENAI
linkedin_token = os.environ.get('lin_access_token', 'Default Value') # LINKEDIN

time_period=24 # Maximum age in hours of articles to include

bucket_name = "19nt-news" # S3 target bucket for json files. Each story is written to a timestamped file

keywords_tech = [
    'generative ai',
    'genai',
    'llm',
    'chatgpt',
    'inflexion',
    'adept',
    'anthropic',
    'bard',
    'hugging face',
    'Nvidia'
]

# industry keywords currently not used
keywords_industry = [
    'enterprise',
    'hack',
    'security',
    'cyber',
    'warfare',
    'china',
    'chinese',
    'supply chain',
    'climate',
    'disease',
    'copyright',
    'privacy',
    'regulat',
    'framework',
    'SEC',
    'FCA',
    'ruling',
    'court',
    'sue',
    'adoption',
    'finance',
    'J.P. Morgan',
    'Morgan Stanley',
    'Citi',
    'Goldman',
    'stock exchange',
    'LSEG',
    'NYSE',
    'Nasdaq',
    'bank',
    'insurance',
    'investment',
    'funding',
    'PWC',
    'KPMG',
    'BAIN',
    'McKinsey',
    'Deloitte',
    'BCG'
]

rss_feed_urls = [
    {"source": "TechCrunch", "url": "https://techcrunch.com/feed/"},
    {"source": "CNBC", "url": "https://www.cnbc.com/id/100727362/device/rss/rss.html"},
    {"source": "Wired", "url": "https://www.wired.com/feed/rss"},
    {"source": "Forbes", "url": "https://www.forbes.com/innovation/feed2"},
    {"source": "VentureBeat", "url": "http://feeds.feedburner.com/venturebeat/SZYF"},
    {"source": "CNET", "url": "https://www.cnet.com/rss/news/"},
    {"source": "ZDNet", "url": "https://www.zdnet.com/news/rss.xml"},
    {"source": "InfoWorld", "url": "https://www.infoworld.com/uk/index.rss"},
    {"source": "Mashable", "url": "https://mashable.com/feeds/rss/all"},
    {"source": "BBC Business", "url": "http://feeds.bbci.co.uk/news/business/rss.xml"},
    {"source": "BBC World", "url": "http://feeds.bbci.co.uk/news/world/rss.xml"},
    {"source": "Yahoo", "url": "https://finance.yahoo.com/rss/topstories"},
    {"source": "CNN US", "url": "http://rss.cnn.com/rss/cnn_us.rss"},
    {"source": "CNN World", "url": "http://rss.cnn.com/rss/cnn_world.rss"},
    {"source": "Dow Jones", "url": "https://feeds.a.dj.com/rss/RSSWSJD.xml"},
    {"source": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"source": "CoinTelegraph", "url": "https://cointelegraph.com/rss"},
    {"source": "Daily AI", "url": "https://dailyai.com/feed/"}
]



# FUNCTIONS

print('Loading function')

#POST TO LINKEDIN
def linkedin_post(post_summary):
    # Prepare headers for the request
    headers = {
        'Authorization': f'Bearer {linkedin_token}',
        'Content-Type': 'application/json',
        'X-Restli-Protocol-Version': '2.0.0'
    }

    # Data payload for the new post
    post_data = {
    # HA
    "author": "urn:li:person:Ps7RkNIAvC",

    # CA
    #  "author": "urn:li:person:pESfU3PUs1",
    "lifecycleState": "PUBLISHED",
    "specificContent": {
        "com.linkedin.ugc.ShareContent": {
            "shareCommentary": {
                "text": post_summary
            },
            "shareMediaCategory": "NONE",
        }
    },
    "visibility": {
        "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
    }
}

    # Make the API request
    response = requests.post(
        'https://api.linkedin.com/v2/ugcPosts',
        headers=headers,
        json=post_data
    )

    # Check if the request was successful and print the response
    if response.status_code == 201:
        print('Successfully posted to LinkedIn!')
    else:
        print(f'Failed to post to LinkedIn: {response.content}')
    return None

# Save each story to a JSON file on AWS S3 storage
def write_json_to_s3(bucket_name, file_name, data):
    import boto3
    import json
    from datetime import datetime

    # Initialize a session using Amazon S3
    s3 = boto3.client('s3')
    
    # Serialize the JSON data
    json_data = json.dumps(data)
    
    # Write the JSON data to S3
    s3.put_object(Bucket=bucket_name, Key=file_name, Body=json_data, ContentType='application/json')

# Handle different date formats from different news feeds
def parse_date(published_date_str):
    # Manual conversion of some known timezones to their UTC offsets.
    timezone_mappings = {
        'EDT': '-0400',
        'EST': '-0500',
        'CST': '-0600',
        'PST': '-0800'
        # Add more mappings as needed
    }
    
    for tz, offset in timezone_mappings.items():
        published_date_str = published_date_str.replace(tz, offset)

    formats = ["%a, %d %b %Y %H:%M:%S %z","%a, %d %b %Y %H:%M:%S %Z"]
    
    for fmt in formats:
        try:
            return datetime.strptime(published_date_str, fmt)
        except ValueError:
            continue

    return None

# Check if a story is not too old
def is_old(published_date_str):
    published_date = parse_date(published_date_str)
                    
    if published_date is not None:
        # Get the current time and date
        current_date = datetime.now(published_date.tzinfo)
        # Calculate the time difference
        time_difference = current_date - published_date
        # Check if it's more than 24 hours old
        if time_difference < timedelta(hours=time_period):
            return False
        else:
            return True

# Write an intro for our LinkedIn post. GPT does this based on a list of story titles
def ai_intro(titles_in):
    response = openai.ChatCompletion.create(
#        model="gpt-3.5-turbo",
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You will be provided with a list of one or more news headlines about Generative AI from different online sources. Your task is to write a single short introduction for a daily LinkedIn post which contains these stories. Your style should be professional and matter of fact, avoid superlatives and don't use words like 'exciting' or 'excited'. Include relevant hashtags after the summary"},
            {"role": "user", "content": titles_in}
        ],
        temperature=0,
        max_tokens=200,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0
    )
    return response.choices[0].message['content'].strip()

# Search each RSS feed for relevant stories
def search_feeds(feed_urls, first_list=None, second_list=None):   
    counter = 0
    body = "Latest AI News: "
    titles = ""
    stories = ""
    
    for feed_url in feed_urls:
        if counter == 10: # LinkedIn post will fail >3000 characters;
            break
        else:
            feed = feedparser.parse(feed_url['url'])           
            if feed.status == 200:
                for entry in feed.entries:
                    if counter == 10: # LinkedIn post will fail >3000 characters;
                        break
                    else:
                        if hasattr(entry,'published'):
                            if not is_old(entry.published):
            #                       if (any(item.lower() in entry.title.lower() for item in first_list)) and (any(item2.lower() in entry.title.lower() for item2 in second_list)):
                                if any(item.lower() in entry.title.lower() for item in first_list):
                                    counter += 1                    
                                    titles += str(counter) + ": " + entry.title + "\n"
                                    stories += str(counter) + ": " + entry.title + "\n" + feed_url['source'] + ": " + entry.link + "\n\n"


    if counter > 0:
        the_intro = ai_intro(titles)
        body = the_intro + "\n\n" + stories + "This newsletter is fully automated using OpenAI and LinkedIn APIs\n\n"
        print(body)
    else:
        print("No matches")
              
    print("End")
    return body, counter


def lambda_handler(event, context):
    storycount = 0
    my_summary, storycount = search_feeds(rss_feed_urls, keywords_tech, keywords_industry)
    print("_" * 20)
    print("Count: ", storycount)
    if storycount > 0: #If we have found stories .. post them to LinkedIn
        linkedin_post(my_summary)
    else:
        print("no stories")
    return
