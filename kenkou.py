#!/usr/bin/env python

""" HTTP resource check

    Check that a web site or HTTP resource is alive

    :copyright: (c) 2012-2013 by Mike Taylor
    :license: BSD 2-Clause

    Assumes Python v2.7+

    Authors:
        bear    Mike Taylor <bear@bear.im>
"""

import os, sys
import json
import time
import uuid
import email
import types
import logging
import datetime
import urlparse
import argparse

from bs4 import BeautifulSoup, SoupStrainer
import requests
import dns.resolver
import dns.message
import dns.query


_version_   = u'0.4.6'
_copyright_ = u'Copyright (c) 2012-2014 Mike Taylor'
_license_   = u'BSD 2-Clause'

_ourPath = os.getcwd()
_ourName = os.path.splitext(os.path.basename(sys.argv[0]))[0]
_usage   = """
Usage
    -c --config  Configuration file (json format)
"""

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(_ourName)


def normalizeFilename(filename):
    result = os.path.expanduser(filename)
    result = os.path.abspath(result)
    return result

def loadConfig(cfgFilename):
    result = {}
    if not os.path.exists(cfgFilename):
        for cfgpath in configPaths:
            possibleFile = normalizeFilename(os.path.join(cfgpath, configName))
            if os.path.exists(possibleFile):
                result = json.load(open(possibleFile, 'r'))
                break
    else:
        possibleFile = normalizeFilename(cfgFilename)
        if os.path.exists(possibleFile):
            result = json.load(open(possibleFile, 'r'))
    return result

def flatten(source):
    result     = {}
    namespaces = []
    for ns in source:
        namespaces.append(ns)
        for site in source[ns]:
            key = '%s.%s' % (ns, site)
            result[key] = source[ns][site]
    return result, namespaces

def pagerDuty(event):
    if 'method' in config['pagerduty']:
        method = config['pagerduty']['method']
    else:
        method = 'POST'
    if 'params' in config['pagerduty']:
        params = config['pagerduty']['params']

    log.info('sending trigger request')

    try:
        if '%s' in params['incident_key']:
            params['incident_key'] = params['incident_key'] % event['sitename']

        params['description'] = event['subject'][:1000]
 
        resp = requests.post(config['pagerduty']['url'], data=json.dumps(params))

        if resp.status_code == requests.codes.ok:
            log.info('trigger successfully sent')
        else:
            log.error('trigger failed: %s %s' % (resp.status_code, resp.text))
    except:
        log.exception('Error during failure reporting, exiting')

def postageApp(subject, body):
    payload = { "api_key":   config['postageapp']['api_key'],
                "uid":       str(uuid.uuid4()),
                "arguments": { "recipients": config['postageapp']['recipients'],
                               "headers":    { "subject": subject,
                                               "from":    "kenkou <ops@andyet.net>",
                                             },
                               "content":    { "text/plain": body }
                             }
              }

    s = json.dumps(payload)
    r = requests.post('https://api.postageapp.com/v.1.0/send_message.json', data=s, headers={'Content-Type': 'application/json'})

    return r.status_code

_exception = """Kenkou has discovered an issue with the site %(url)s
The result from the attempt to reach the site is:
%(message)s
"""
_error    =  """Kenkou has discovered an issue with the site %(url)s
The result from the attempt to reach the site is: %(status)s
The body of the request is:
%(message)s
"""
_IPerror =  """Kenkou has discovered an issue with the DNS for %(sitename)s.
The IP address should be %(ip)s but the DNS Query returned %(found)s
"""
_NSerror =  """Kenkou has discovered an issue with the DNS for %(sitename)s.
The nameserver list should be:
%(nameservers)s
but the DNS lookup returned
%(found)s
"""

def handleEvent(sitename, sitedata, status, message):
    log.error('Check event for %s (%s) %s: %s' % (sitename, sitedata['url'], status, message))

    subject = "Kenkou Site Check Failed for %s" % sitename
    data    = { 'sitename': sitename,
                'url':      sitedata['url'],
                'status':   status,
                'message':  message,
                'subject':  subject
              }
    if status is None:
        body = _exception % data
    else:
        body = _error % data

    for item in config['onevent']:
        if item == 'postageapp':
            log.debug('event sent to PostageApp: %s' % postageApp(subject, body))
        elif item == 'pagerduty':
            log.debug('event sent to pagerDuty: %s' % pagerDuty(data))

def handleDNSEvent(sitename, ip, nameservers, found):
    log.error('Check event for %s' % sitename)

    subject = "Kenkou DNS Check Failed for %s" % sitename
    data    = { 'sitename':    sitename,
                'ip':          ip,
                'nameservers': nameservers,
                'found':       found
                'subject':     subject
              }
    if ip is None:
        body = _NSerror % data
    else:
        body = _IPerror % data

    for item in config['onevent']:
        if item == 'postageapp':
            log.debug('event sent to PostageApp: %s' % postageApp(subject, body))
        elif item == 'pagerduty':
            log.debug('event sent to pagerDuty: %s' % pagerDuty(data))

def hasURL(tag):
    for item in ('href', 'cite', 'background', 'action', 'profile', 'src', 
                 'longdesc', 'data', 'usemap', 'codebase', 'classid',
                 'formaction', 'icon', 'manifest', 'poster'):
        if tag.has_attr(item):
            return True, item
    return False, None

def checkMixedContent(response):
    """Search the html content for a URL for all URLs that would trigger
       a mixed content warning. 

       All anchor tags and link tags with rel="alternate" are skipped.

        HTML4:
            <applet codebase=url>
            <area href=url>
            <base href=url>
            <blockquote cite=url>
            <body background=url>
            <del cite=url>
            <form action=url>
            <frame longdesc=url> and <frame src=url>
            <head profile=url>
            <iframe longdesc=url> and <iframe src=url>
            <img longdesc=url> and <img src=url> and <img usemap=url>
            <input src=url> and <input usemap=url>
            <ins cite=url>
            <link href=url>
            <object classid=url> and <object codebase=url> and <object data=url> and <object usemap=url>
            <q cite=url>
            <script src=url>

        HTML5:
            <audio src=url>
            <button formaction=url>
            <command icon=url>
            <embed src=url>
            <html manifest=url>
            <input formaction=url>
            <source src=url>
            <video poster=url> and <video src=url>
    """
    mixed   = []
    urlData = urlparse.urlparse(response.url)
    scheme  = urlData.scheme.lower()

    if scheme == 'https':
        bsoup = BeautifulSoup(response.text, 'html5lib')
        for tag in bsoup.find_all(True):
            f, item = hasURL(tag)

            if f:
                tagUrl  = tag.attrs[item]
                urlData = urlparse.urlparse(tagUrl)

                if tag.name == 'a':
                    continue
                if (tag.name == 'link') and ('rel' in tag.attrs) and ('alternate' in tag.attrs['rel']):
                    log.debug('skipping link tag with url %s' % tagUrl)
                    continue
                if len(urlData.scheme) == 0:
                    tagScheme = scheme
                else:
                    tagScheme = urlData.scheme.lower()
                if tagScheme.startswith('http') and (tagScheme != scheme):
                    mixed.append(tagUrl)
    return mixed

def checkURLS(sitename, sitedata):
    log.debug('checking %s' % sitename)
    if 'url' in sitedata:
        url = sitedata['url']

        try:
            r = requests.get(url, verify=False)
            if url != r.url:
                log.debug('URL was redirected, processing last URL handled')
            log.debug('%s responded with %s' % (r.url, r.status_code))

            if r.status_code != 200:
                handleEvent(sitename, sitedata, r.status_code, r.text)
            else:
                mixed = checkMixedContent(r)
                if len(mixed) > 0:
                    s = 'Mixed Content URLs found within the site\n'
                    for url in mixed:
                        s += '    %s\n' % url
                    handleEvent(sitename, sitedata, r.status_code, s)

        except (requests.exceptions.RequestException, 
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,
                requests.exceptions.URLRequired,
                requests.exceptions.TooManyRedirects) as e:
            handleEvent(sitename, sitedata, None, e.message)

def checkDNS(sitename, sitedata):
    log.debug('checking %s' % sitename)
    if 'dns' in sitedata:
        domain, ip, nameservers = sitedata['dns']

        ips = []
        ns  = []

        for a in dns.resolver.query(domain):
            ips.append(a.to_text())

        q = dns.message.make_query(domain, dns.rdatatype.NS)
        m = dns.query.udp(q, '8.8.8.8')

        k = m.index.keys()[0]
        for i in m.index[k]:
            ns.append(i.to_text())

        if ip not in ips:
            handleEvent(sitename, ip, None, ips)

        for s in nameservers:
            for t in ns:
                if t.startswith(s):
                    ns.remove(t)

        if len(ns) > 0:
            handleDNSEvent(sitename, None, nameservers, ns)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', default='%s.cfg' % _ourName)

    args   = parser.parse_args()
    config = loadConfig(args.config)

    if config['debug']:
        log.setLevel(logging.DEBUG)

    log.info('Starting')

    if config['urls'] is None:
        log.error('URLs configuration item is required, exiting')
        sys.exit(2)

    urls       = {}
    namespaces = []
    for k in config['urls']:
        if k == 'file':
            try:
                fUrls = json.loads(' '.join(open(config['urls'][k], 'r').readlines()))
                for key in fUrls:
                    urls[key] = fUrls[key]
            except:
                log.exception('unable to load url list from %s' % config['urls'][k])
        elif k == 'redis':
            log.warning('redis is not handled currently')
        else:
            log.error('Unknown URL entry [%s]' % k)

    urls, namespaces = flatten(urls)

    for key in urls.keys():
        checkURLS(key, urls[key])

    dnsitems   = {}
    namespaces = []
    for k in config['dns']:
        if k == 'file':
            try:
                fDNS = json.loads(' '.join(open(config['dns'][k], 'r').readlines()))
                for key in fDNS:
                    dnsitems[key] = fDNS[key]
            except:
                log.exception('unable to load dns list from %s' % config['dns'][k])
        else:
            log.error('Unknown URL entry [%s]' % k)

    dnsitems, namespaces = flatten(dnsitems)

    for key in dnsitems.keys():
        checkDNS(key, dnsitems[key])