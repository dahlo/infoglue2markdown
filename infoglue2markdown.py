#!/bin/env python3

import requests
from bs4 import BeautifulSoup
import argparse
import textwrap
import sys
from urllib.parse import urlparse
import urllib.request
from multiprocessing import Pool


import re
import html2text
import pathlib
import os

from IPython.core.debugger import Tracer





def harvest_new_urls(soup, url_memory, url_queue, url_rejected):

    # go throguh all link in the page
    for link in soup.find_all('a', href=True):

        current_scheme, current_host, current_path = urlparse(link.attrs['href'])[:3]

        # make relative links absolute
        if current_scheme == '':
            current_scheme = root_scheme
        if current_host == '':
            current_host = root_host
        if current_path == '':
            current_path = '/'

        # reconstruct the link
        current_link = current_scheme+"://"+current_host+'/'+current_path

        # Tracer()()
        # skip link that have already been seen
        if current_link in url_memory:
            continue
        
        # skip if the url is outside the site's domain
        if current_host != root_host:
            url_rejected[current_link] = [current_url, 'wrong host']
            url_memory[current_link] = current_url
            continue

        # skip if the scheme is not http/https
        if current_scheme not in ['http', 'https']:
            url_rejected[current_link] = [current_url, 'wrong scheme']
            url_memory[current_link] = current_url
            continue

        # skip link that are not absolute (usually unrenderedinfoglue internal links like $templateId=4.....)
        if current_path[0] != '/':
            url_rejected[current_link] = [current_url, 'invalid path']
            url_memory[current_link] = current_url
            continue

        # make sure the url is under the same subfolder as the root url
        if not current_path.startswith(root_path):
            url_rejected[current_link] = [current_url, 'wrong path']
            url_memory[current_link] = current_url
            continue

        # skip links to files with file endings, handle attachments when the conversion takes place
        if re.search('\.\w+$', current_path):
            url_rejected[current_link] = [current_url, 'is an attachment/file']
            url_memory[current_link] = current_url
            continue
        
        # a new link to process, add it to the queue and memory
        url_queue[current_link] = current_url
        url_memory[current_link] = current_url
        

    return url_memory, url_queue, url_rejected









def convert_to_markdown(page_soup, current_url):

    # break down the url again
    current_scheme, current_host, current_path = urlparse(current_url)[:3]
    if current_scheme == '':
        current_scheme = root_scheme
    if current_host == '':
        current_host = root_host
    if current_path == '':
        current_path = '/'
    current_url = current_scheme+"://"+current_host+'/'+current_path

    # save the name of the page
    page_name = current_path.strip('/').split('/')[-1]

    # break out the article contents and convert it to markdown
    try:
        article_html = str(page_soup.find_all('article')[0])
    except IndexError:
        # if the page doesn't have an article section, skip it
        print("WARNING: {} missing article section".format(current_url))
        return None

    article_md = md_maker.handle(article_html)

    # create output dir and download all attachments in the article
    # Tracer()()
    pathlib.Path(os.path.join(*[args.output]+ re.split('/+', current_path)[:-1]+ ['files'])).mkdir(parents=True, exist_ok=True)
    for file in re.findall( '\((\/digitalAssets\S+)\)', article_md):
        file_url = '/'.join([root_url, file])
        file_name = file.split('/')[-1]
        # print('/'.join([root_url, img]))
        urllib.request.urlretrieve(file_url, os.path.join(*[args.output]+ re.split('/+', current_path)[:-1]+ ['files', file_name]))

    # replace all image links to new format
    article_md_attachmentsfix = re.sub(  '\/digitalAssets\/\S+\/(\S+\.\S+)\)', r'files/\1)',   article_md  )


    # TODO: repalce all links within the same domain to new link format

    ### create the jekyll header
    
    # find the first heading
    article_title = ""
    for line in article_md_attachmentsfix.split('\n'):
        if line.startswith('#'):
            # Tracer()()
            try:
                article_title = re.match('^#+(.*$)', line).groups(0)[0].strip().capitalize()
            except AttributeError:
                article_title = ""
            break

    jekyll_header = """---
layout: two_puff
title:  '{}'
---
    """.format(article_title)

    # write md file
    with open(os.path.join(*[args.output]+ re.split('/+', current_path)[:-1]+ [page_name+".md"]), 'w') as article_file:
        article_file.write(jekyll_header)
        article_file.write(article_md_attachmentsfix)

    return 1






# get arguments
parser = argparse.ArgumentParser(description='Covert a whole InfoGlue site (or subtree of) to Markdown.', 
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=textwrap.dedent('''\
         Example usage: 
         {0} -u http://my.url/ -o new_web/
         {0} -u http://my.url/sub/folder -o new_web/ -s -c -r
         '''.format(sys.argv[0])))
parser.add_argument("-u", "--url", dest='url', type=str, help="The base URL to the InfoGlue site to convert.", required=True)
parser.add_argument("-o", "--outputdir", dest='output', type=str, help="Output folder to put the page in.", required=True)
parser.add_argument('-r', '--rejected', dest='rejected', action='store_true', help="Print a list of all rejected urls, along with why they were rejected and where they were first seen.")
parser.add_argument('-s', '--silent', dest='silent', action='store_true', help="Supress the progress reporting while running.")
parser.add_argument('-c', '--converted', dest='converted', action='store_true', help="Print a list of all converted urls and where they were first seen.")
args = parser.parse_args()


# break the url into pieces
root_scheme, root_host, root_path = urlparse(args.url)[:3]
if root_path == '': # empty root path is rewritten as a relative path starting at /
    root_path = '/'

# init
root_url = root_scheme+"://"+root_host+'/'+root_path
url_memory = dict()
url_queue = {root_url:'root'}
url_rejected  = dict()
url_converted  = dict()

# create the markdown converter and set some options (https://github.com/Alir3z4/html2text/blob/master/docs/usage.md)
md_maker = html2text.HTML2Text()
md_maker.body_width = 0 # don't wrap lines by inserting \n everywhere
md_maker.ignore_images = True # keep image links as html to avoid losing the html size properties
md_maker.bypass_tables = True # keep tables as html format

# Tracer()()

# keep going until everything is converted
i = 0
while len(url_queue) > 0:

    # get next page to process
    current_url, current_source = url_queue.popitem()

    # print status if not silent
    if not args.silent:
        print('Done: {}\tRemaining: {}\tProcessing: {}'.format(i, len(url_queue), current_url))

    # process the page
    page = requests.get(current_url)
    page_html = page.content
    page_soup = BeautifulSoup(page_html, 'html.parser')
    url_memory, url_queue, url_rejected = harvest_new_urls(page_soup, url_memory, url_queue, url_rejected)

    # convert the page
    conversion_worked = convert_to_markdown(page_soup, current_url)

    
    if conversion_worked:
        # save to the list of converted urls
        url_converted[current_url] = current_source
    else:
        # add to list of rejected urls
        url_rejected[current_url] = [current_source, 'markdown conversion failed']
    
    i += 1


# print the rejected urls if asked to
if args.rejected:
    print("#rejected_url\t#reason_for_rejection\t#first_seen_on")
    for key in sorted(url_rejected.keys()):
        print(key+'\t'+url_rejected[key][1]+'\t'+url_rejected[key][0])


# print the converted urls if asked to
if args.converted:
    print("#converted_url\t#first_seen_on")
    for key in sorted(url_converted.keys()):
        print(key+'\t'+url_converted[key])




