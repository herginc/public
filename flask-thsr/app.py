#
# Flask THSR Parser
#

import os
import sys
from argparse import ArgumentParser

from flask import Flask, request, abort

from linebot.v3 import (
     WebhookHandler
)

from linebot.v3.exceptions import (
    InvalidSignatureError
)

from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)

from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)

app = Flask(__name__)

# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)

if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

count = 0

@app.errorhandler(404)
def page_not_found(error):
    global count
    count = count + 1
    print(f"[{error}] page not found or undefined route")
    return 'page not found', 404


@app.route("/", methods=["GET"])
def home():
    global count
    count = count + 1
    return "LINE Bot Webhook is running ..."


@app.route("/echo", methods=['POST'])
def cb_echo():
    global count
    count = count + 1
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    print(f"({count}) Body={body}")
    sys.stdout.flush()
    return 'OK', 200


@app.route("/callback", methods=['POST'])
def line_webhook():
    print("receive a POST messages via a callback route")

    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    print(f"Request body: {body}")
    sys.stdout.flush()

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK', 200


@handler.add(MessageEvent, message=TextMessageContent)
def message_text(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=event.message.text)]
            )
        )


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', default=10000, help='port')
    arg_parser.add_argument('-d', '--debug', default=True, help='debug')
    options = arg_parser.parse_args()

    app.run(debug=options.debug, port=options.port)