import bs4 as bs
import logging
import re
import requests
import time

from collections import deque
from requests.adapters import HTTPAdapter
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

# create logger
logger = logging.getLogger('linkto_bot')

DEFAULT_TIMEOUT = 5 # seconds

class TimeoutHTTPAdapter(HTTPAdapter):
    """
    https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/
    """
    def __init__(self, *args, **kwargs):
        self.timeout = DEFAULT_TIMEOUT
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


def bot(start_url, depth=None, crawl_delay=1, exclude_external_urls=True, exclude_url_patterns=[]):

    # setup a requests session with a user agent
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'checkrs_linkto (+https://github.com/rstudio/checkRS-linkto)'
    })

    # setup the request timeout adapter
    timeout_adapter = TimeoutHTTPAdapter()
    s.mount("https://", timeout_adapter)
    s.mount("http://", timeout_adapter)

    to_be_visited = deque()
    history = dict()
    robots_txts = dict()
    compiled_exclude_url_patterns = list()

    # compile all of the exclude_url_patterns
    for p in exclude_url_patterns:
        compiled_exclude_url_patterns.append(re.compile(p))

    start_url_p = urlparse(start_url)

    logger.debug(f"adding start URL to history and to_be_visited: {start_url}")

    history[start_url] = dict(
        response_code=None,
        visited_from=[None],
        error_text=None,
        depth=0
    )

    # adding beginning url to the to_be_visited
    to_be_visited.append(start_url)

    while len(to_be_visited) > 0:

        # get the URL(next item in the queue) of the top item in the to_be_visited
        url = to_be_visited.popleft()
        logger.info(f"processing: '{url}'")
        logger.debug(f"url's left to be processed: {len(to_be_visited)}")

        url_p = urlparse(url)

        # check if this url has an external netloc
        if url_p.netloc != start_url_p.netloc:
            if exclude_external_urls is True:
                msg = "Matched URL exclude external netloc"
                logger.debug(msg)
                history[url]["error_text"] = msg
                history[url]["response_code"] = -1
                continue

        # check if the user asked to skip visiting this url
        skip_for_matching_pattern = False
        for exclude_url_pattern in compiled_exclude_url_patterns:
            if exclude_url_pattern.search(url) is not None:
                # the user has asked us not to crawl this url
                # log that we are skipping the url
                # move on to the next url
                msg = f"Matched URL exclude pattern '{exclude_url_pattern.pattern}'"
                logger.debug(msg)
                history[url]["error_text"] = msg
                history[url]["response_code"] = -1
                skip_for_matching_pattern = True
                break

        # check if we found a matching exclude pattern
        if skip_for_matching_pattern is True:
            continue

        # retrieve and parse the robot.txt for the site
        if url_p.netloc not in robots_txts:
            robots_txt_url = urlunparse((url_p.scheme, url_p.netloc,"robots.txt",None,None,None))
            robots_txts[url_p.netloc] = RobotFileParser()
            # robots_txts[url_p.netloc].set_url(robots_txt_url)
            try:
                r = s.get(robots_txt_url)
                robots_txts[url_p.netloc].parse(r.text.splitlines())
            except Exception as err:
                # site probably doesnt exist
                # remove the robot file parser
                # save the exception details
                # move on to the next url
                logger.error(f"while connecting: {err}")
                del robots_txts[url_p.netloc]
                history[url]["error_text"] = str(err)
                history[url]["response_code"] = 0
                continue

        # check if our robot is allowed to visit this url
        can_fetch = robots_txts[url_p.netloc].can_fetch(s.headers['User-Agent'], url)
        if can_fetch is False:
            # we are not allowed to crawl this url
            # due to a rule in robots.txt
            msg = "Matched robots.txt exclude rule."
            history[url]["error_text"] = msg
            history[url]["response_code"] = -1
            logger.debug(msg)
            continue

        # crude, temporary implementation of crawl delay
        time.sleep(crawl_delay)

        try:
            # Make a HEAD request to fetch the resource's headers
            # we'll use this later to check if the resource is HTML
            logger.info(f"visiting: '{url}'")
            response = s.head(url, allow_redirects=True)

        except Exception as err:
            # making the HEAD request failed
            # the failed request won't have a status code
            # save connection error details continue to the next url
            history[url]["error_text"] = str(err)
            history[url]["response_code"] = 0
            logger.error(f"while connecting: {err}")
            continue

        # Update history with the response's status code
        history[url]["response_code"] = response.status_code

        # Determine if we should look for more links on this resource.

        # Filter out resources that have no Content-Type header
        # we can't tell if they are HTML content
        if 'Content-Type' not in response.headers:
            logger.debug(f"filtered out content with missing Content-Type header: {response.headers}")
            continue

        # Filter out resources that are not HTML text
        if 'text/html' not in response.headers['Content-Type'].lower():
            logger.debug(f"filtered out non-HTML content: {response.headers['Content-Type']}")
            continue

        # Filter out urls with status_code greater than 400
        if int(response.status_code) >= 400:
            logger.debug(f"filtered out error status code: {response.status_code}")
            continue

        # Filter out if the url netloc value is not same as start url netloc
        if url_p.netloc != start_url_p.netloc:
            logger.debug(f"filtered out external url: {url_p.netloc}")
            continue

        # Don't traverse any urls that are more than # of depth clicks away from the start page
        # With the way we are calculating depth there may be a way
        # to get to the page in fewer clicks and we don't take that into account currently
        # it would involve updating the history dictionary
        if depth is not None and depth <= history[url]["depth"]:
            logger.debug(
                f"ignoring links for url with depth {history[url]['depth']}: {url}"
            )
            continue

        # Make a GET request to fetch the raw HTML content
        try:
            response = s.get(url)
        except Exception as err:
            # very unexpected to get an error here because
            # our previous HEAD request should have been successful.
            # log the error and continue to the next url
            history[url]["error_text"] = f"While retrieving HTML content for {url}: {str(err)}"
            logger.error(f"while connecting: {err}")
            continue

        # Parse the html content
        soup = bs.BeautifulSoup(response.text, 'lxml')

        # grab all the “<a>" tags on the page
        atags = soup.find_all('a')
        for atag in atags:
            href = atag.get('href')

            logger.debug(f"found url: {href}")

            # filter out anchor tags without an href attribute
            if href is None:
                continue

            # remove leading and trailing spaces from the href
            # https://www.w3.org/TR/2014/REC-html5-20141028/infrastructure.html#valid-non-empty-url-potentially-surrounded-by-spaces
            href = href.strip()

            # filter out repeating url with # and email
            if href.startswith("mailto:"):
                continue

            # convert to full link
            full_href = urljoin(response.url, href)

            # if href starts with # look through the HTML for an element with the same id
            # if we find the element then add an entry to the history dictionary saying that we visited the page
            # if we don't find the element add an entry to the history dictionary with error text that the element did not exist
            if href.startswith("#"):
                id_text = href[1:]
                element = soup.find(id=id_text)
                if element is not None:
                    logger.debug(f"adding URL fragment to history as exists: {href}")

                    error_text = None
                else:
                    logger.debug(f"adding URL fragment to history as does not exist: {href}")

                    # note that the element does not exist in the error_text
                    error_text = f"Element with id '{id_text}' not found in HTML DOM"

                # handle cases where full_href does and does not exist in history dictionary
                if full_href not in history:

                    # add url, visited_from and error_text to the history
                    # we are using the same status code and depth as the parent page
                    history[full_href] = dict(
                        response_code=response.status_code,
                        visited_from=[url],
                        error_text=error_text,
                        depth=history[url]["depth"]
                    )
                else:
                    # add visited_from with the url
                    history[full_href]["visited_from"].append(url)
                    history[full_href]["error_text"] = error_text

                continue

            # check if link exists in history dictionary
            if full_href not in history:

                logger.debug(f"adding URL to history and to_be_visited: {full_href}")

                # add url, visited_from and error_text to the history
                history[full_href] = dict(
                    response_code=None,
                    visited_from=[url],
                    error_text=None,
                    depth=history[url]["depth"]+1
                )

                # append url to to_be_visited list
                to_be_visited.append(full_href)

            else:

                logger.debug(f"marking '{full_href}' as visited from '{url}'")

                # add visited_from with the url
                history[full_href]["visited_from"].append(url)

    return history
