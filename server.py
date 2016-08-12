import os, random, string, requests, json
from flask import Flask, render_template, redirect, request, jsonify, session
from flask_debugtoolbar import DebugToolbarExtension
from urllib import urlencode, urlopen
import re
# from channel import Channel
from time import time


app = Flask(__name__)

app.secret_key = "a_very_dumb_secret"

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
MYEMAIL = os.environ["MYEMAIL"]
state = None
# channel_tuple_list = []


@app.route("/")
def index():
    """Initial landing page"""

    return render_template("index.html")

@app.route("/get_team")
def get_team():
    """OAuth route"""

    global state
    state = randomWord()

    params = {"client_id": CLIENT_ID,
                "redirect_uri": "http://127.0.0.1:5000/slacked",
                "scope": "channels:history channels:read team:read",
                "state": state}
    oauth_url = "https://slack.com/oauth/authorize?" + urlencode(params)

    return redirect(oauth_url)


@app.route("/slacked")
def slacked():
    """Landing page for authorized slack users, completes OAuth danceand saves user token"""

    state_returned = request.args.get("state")
    client_code = request.args.get("code")

    if check_state(state_returned) is False:
        return "Slack did not return the expected state variable! You've been h4x0r3d."
    else:
        # OAuth parameters
        params = {"client_id": CLIENT_ID.strip(),
                    "client_secret": CLIENT_SECRET.strip(), # was having issue with a \r
                    "code": client_code}

        oauth_url = "https://slack.com/api/oauth.access?" + urlencode(params)       

        json_response = requests.get(oauth_url)
        # parse json response
        response = json_response.json()
        
        # identify user
        print response
        user_token = response["access_token"]

        session["user_token"] = user_token

    return redirect("/bubble")


@app.route("/bubble")
def bubble():
    """Display d3"""

    return render_template("bubble.html")


@app.route("/channel_data.json")
def make_channel_data():
    """Parses list of channel tups into json for d3 bubble chart"""

    # blank out all lists, etc to clear graph
    channel_tuple_list = []

    # get list of channels and authorized team name for user
    channel_list = get_channel_list()
    team_name = get_team_name()

    channel_data = {"name": team_name,
                "children": []
                }

    for channel in channel_list:
        channel_name = channel[0]
        channel_history = get_channel_history(channel) #returns list of messages for a channel
        msg_dictionary = make_history_dictionary(channel_history) #Makes into s140 api dictionary
        sentiment_dict = get_sentiment(msg_dictionary) #gets sentiment back
        sentiment_list = make_sentiment_list(sentiment_dict) #parses sentiment into list of values

        channel_dict = process_sentiment_list(channel_name, sentiment_list)

        channel_data["children"].append(channel_dict)

    return jsonify(channel_data)


##################### Helper functions


def randomWord():
    """Generates a random 10 character string, to use as an API verification"""

    return ''.join(random.choice(string.lowercase) for i in range(10))


def check_state(state_returned):
    """Checks that state sent to Slack is correctly returned."""

    if state_returned != state:
        raise Exception("Slack did not return the expected state variable! You've been h4x0r3d.")
        return False
    else:
        return True


def get_team_name():
    """Given a user token, returns the name of the authorized team"""

    token = session["user_token"]
    team_params = {"token": token}
    team_url = "https://slack.com/api/team.info?" + urlencode(team_params)
    json_team = requests.get(team_url)
    team_response = json_team.json()
    team_name = team_response["team"]["name"]
    
    return team_name


def get_channel_list():
    """Give a user token, returns a list of tuples with active channel names and ids"""

    token = session["user_token"]
    channel_params = {"token": token, "exclude_archived": 1}
    channel_url = "https://slack.com/api/channels.list?" + urlencode(channel_params)
    json_channel = requests.get(channel_url)
    channel_response = json_channel.json()

    channel_list = []

    # print "\n", channel_response
    
    for channel in channel_response["channels"]:
        channel_tuple = (channel["name"], channel["id"])
        channel_list.append(channel_tuple)

    return channel_list


def get_channel_history(channel_tuple):
    """Returns history of the channel"""

    token = session["user_token"]
    ONE_WEEK_SEC = 604800
    epoch_time = time()
    one_week_ago = epoch_time - ONE_WEEK_SEC

    history_params = {"token": token, 
                        "channel": channel_tuple[1],
                        "inclusive": 1,
                        "oldest": one_week_ago
                        }
    history_url = "https://slack.com/api/channels.history?" + urlencode(history_params)
    json_history = requests.get(history_url)
    history_response = json_history.json()

    msg_list = []

    for msg in history_response["messages"]:
        msg_list.append(msg["text"])

    return msg_list


def make_history_dictionary(msg_list):
    """Converts a message list into a dictionary for sentiment analysis"""

    msg_dictionary = {}
    msg_text_list = []
    skip_msg_list = [" has joined the channel", " has left the channel"]

    for msg in msg_list:
        msg_dict = {}
        msg = clean_msg(msg)

        if msg in skip_msg_list:
            continue
        else:
            msg_dict["text"] = msg
            msg_text_list.append(msg_dict)

    msg_dictionary["data"] = msg_text_list

    return msg_dictionary


def clean_msg(msg):
    """Takes single message, removes user tags and links, returns stripped message"""

    # things to remove: <usernames> <links...> emoticons?!

    stripped_msg = re.sub("[<].*?[>]", "", msg)
    cleaned_msg = stripped_msg

    return cleaned_msg


def get_sentiment(msg_dictionary):
    """Given a message dictionary, makes an API call to Sentiment140 to get sentiments"""

    # add my email to the call, as requested by Sentiment140
    msg_dictionary["appid"] = MYEMAIL
    sentiment_data = json.dumps(msg_dictionary)

    sentiment_api_call = urlopen('http://www.sentiment140.com/api/bulkClassifyJson', sentiment_data)
    sentiment_response = sentiment_api_call.read()
    # ignores character like emoticons which were throwing unicode errors
    sentiment_response_dict = json.loads(sentiment_response.decode("utf-8","ignore"))

    return sentiment_response_dict


def make_sentiment_list(sentiment_dict):
    """Given the sentiment response dictionary, makes list of just the sentiment values"""

    sentiment_list = []

    for sentiment in sentiment_dict["data"]:
        sentiment_list.append(sentiment["polarity"])

    return sentiment_list


def process_sentiment_list(channel_name, sentiment_list):
    """Given a channel name and sentiment list, returns a dict of name, length/value, avg sentiment"""

    channel_dict = {}
    if sentiment_list:
        channel_dict["name"] = channel_name
        channel_dict["value"] = max(len(sentiment_list), 0)
        channel_dict["sentiment"] = max((float(sum(sentiment_list)) / len(sentiment_list)), 0.0)

    return channel_dict


if __name__ == '__main__':
    app.run(debug=True)
