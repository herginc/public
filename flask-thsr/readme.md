# Flask THSR

Use [Flask](http://flask.pocoo.org/) + PostgreSQL to parse HTTP POST messages from websites or line-bot (webhook) and process them.

Keywords: [Flask](http://flask.pocoo.org/), [Flask Source](https://github.com/pallets/flask)

## Getting started

```
$ export LINE_CHANNEL_SECRET=YOUR_LINE_CHANNEL_SECRET
$ export LINE_CHANNEL_ACCESS_TOKEN=YOUR_LINE_CHANNEL_ACCESS_TOKEN

$ pip install -r requirements.txt
```

Run Flask application - flask-thsr

```
$ python app.py
```

## Appendix

We may use Microsoft teams webhook to trigger an thsr-inquiry immediately

```
<Teams @ Home> -- <Teams @ Office> -- <Python@Office> -- inquiry -- <Flask-THSR>
```
