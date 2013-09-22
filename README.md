kenkou
======

A python tool to check that an http resource is alive.

Designed to be run from a cronjob as often as you want to check the sites.

Usage
-----

```
python kenkou.py [-c|--config FILENAME] [-d|--debug] [-l|--logpath LOGFILE]

Where:
    -c --config         Configuration file (json format)
    -d --debug          Turn on debug logging
                        default: False
    -l --logpath        Path where the log file output is written
                        default: None

Configuration
-------------
Example kenkou.json file:

```
{ "debug": true,
  "echo": true,
  "pagerduty": {
    "url": "https://events.pagerduty.com/generic/2010-04-15/create_event.json",
    "method": "POST",
    "params": { "service_key": "secrets",
                "incident_key": "incident_secret",
                "event_type": "trigger",
                "description": "FAILURE for production/HTTP"
    }
  },
  "postageapp": {
    "api_key": "secrets",
    "recipients": ["email@example.com"]
  },
  "onfail": [ "postageapp" ],
  "urls": {
    "file": "urls_to_check.json",
    "redis": { "host": "127.0.0.1",
               "port": 6379,
               "namespace": "kenkou"
    }
  }
}
```

The namespace for the Redis option is used to build both the key used to retrieve the
list of urls and also the keys used to store the last results.

  kenkou:urls_to_check = []
  kenkou:result.URL    = 200

The file option allows for multiple sites to be grouped, for example:

```
{
  "production": [
    "http://127.0.0.1",
    "http://example.com"
  ]
}
```

TODO
----
  * copy some parsing code from parsedatetime so the period value can be more free form, e.g.
    5m, 5 min, 5 minutes, 3 days 2 min and so on
  * make the success determination more data driven such that it could be any result code or
    even a regex compare with something in the response body