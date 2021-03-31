import json
import copy
import logging
import re
from urllib.parse import urljoin, urlparse, urlunparse

# create logger
logger = logging.getLogger('linkto_report')


def list_diff(l1, l2):
    # using deepcopy to avoid modifying the original list
    l1 = copy.deepcopy(l1)

    for i in l2:
        if i in l1:
            l1.remove(i)
    return l1


def normalize_url(params):
    """this function takes a tuple with start_url and url
        and removes the start_url if found inside of url
        otherwise return original url

    :return:string with url or path portion of url
    """
    (start_url, url) = params

    if url is None:
        return url

    # if the start_url shows up inside of url,
    # then we remove start_url from the url
    url = re.sub(start_url, "", url)

    return url


class LinkToReport:

    def __init__(self, history_golden, history_new):

        # These are incoming file names
        self.history_golden_fn = history_golden
        self.history_new_fn = history_new

        # read a json file
        with open(self.history_golden_fn) as f:
            data = json.load(f)
            self.history_golden_start_url = data["start_url"]
            self.history_golden = data["history"]

        with open(self.history_new_fn) as f:
            data = json.load(f)
            self.history_new_start_url = data["start_url"]
            self.history_new = data["history"]

        # variable used to determine if we have error to report back
        self.error_flag = False

        # this is the text of the report
        self.report = ""

        # report counts
        self.counts = {}

    def report_connection_errors(self, ignored_connection_error_patterns=[]):
        """
        Look for URL's that we could not connect to that would have a response code of 0
        Often times these are SSL certificate errors, etc
        :return: self
        """

        self.report += "CONNECTION ERRORS:\n\n"
        self.counts['connection_errors'] = 0

        for k, v in self.history_new.items():
            if v["response_code"] == 0:
                logger.debug(f"processing connection error for: {k}")

                # check if this record has an error that we should be ignoring
                skip_record = False
                for pattern in ignored_connection_error_patterns:
                    match = re.search(pattern, v['error_text'])
                    if match is not None:
                        # found an error we want to ignore, skip the record
                        logger.debug(f"ignoring connection error matching '{pattern}': {k} -> '{v['error_text']}'")
                        skip_record = True
                        break
                if skip_record is True:
                    continue

                self.error_flag = True
                self.report += f"\turl: {k}\n"
                self.report += f"\terror: {v['error_text']}\n"
                self.report += f"\tlinked to from: {v['visited_from'][0]}\n"
                self.report += f"\n"

                self.counts['connection_errors'] += 1

        self.report += '\n\n'

        return self

    def report_status_errors(self, ignored_status_error_patterns=[]):
        """
        Look for URL's that resulted in status code > 400
        :return: self
        """

        self.report += "STATUS ERRORS:\n\n"
        self.counts['status_errors'] = 0

        for k, v in self.history_new.items():
            # check if this record has a status code that we should be ignoring
            skip_record = False
            for ignore_grouping in ignored_status_error_patterns:
                for site_pattern,status_codes in ignore_grouping.items():
                    # check if we have a matching site
                    match = re.search(site_pattern, k)
                    if match is not None:
                        # check if there is a matching status code
                        if v["response_code"] in status_codes:
                            # found an error we want to ignore, skip the record
                            logger.debug(f"ignoring status error: '{k}', {v['response_code']}  matched  '{site_pattern}', {v['response_code']}")
                            skip_record = True
                        break
                if skip_record is True:
                    break
            if skip_record is True:
                continue

            if v["response_code"] >= 400:
                logger.debug(f"processing status error for: {k} status code: {v['response_code']}")
                self.error_flag = True
                self.report += f"\turl: {k}\n"
                self.report += f"\tstatus_code: {v['response_code']}\n"
                self.report += f"\tlinked to from: {v['visited_from'][0]}\n"
                self.report += "\n"

                self.counts['status_errors'] += 1

        self.report += '\n\n'

        return self

    def report_url_visit_differences(self):
        """
        Compare the current run with previous run to see if there were new URL's visited and any old URL's not visited
        These are comparing keys of the json dictionary
        :return: self
        """

        logger.debug(f"processing report_url_visit_differences")

        # parse the url for scheme and netloc
        # generate the list of url's from golden file
        # and normalize url's that match golden file start_url
        o = urlparse(self.history_golden_start_url)
        s = urlunparse([o.scheme, o.netloc, '', '', '', ''])
        t = [(s, x) for x in self.history_golden.keys()]
        history_golden_keys = set(map(normalize_url, t))

        # parse the url for scheme and netloc
        # generate the list of url's from history_new file
        # and normalize url's that match history_new file start_url
        o = urlparse(self.history_new_start_url)
        s = urlunparse([o.scheme, o.netloc, '', '', '', ''])
        t = [(s, x) for x in self.history_new.keys()]
        history_new_keys = set(map(normalize_url, t))

        new_urls_visited = history_new_keys.difference(history_golden_keys)
        urls_not_visited = history_golden_keys.difference(history_new_keys)

        self.report += "URL VISIT DIFFERENCES:\n\n"
        self.counts['url_visit_differences_old'] = len(urls_not_visited)
        self.counts['url_visit_differences_new'] = len(new_urls_visited)

        if len(new_urls_visited) == 0 and len(urls_not_visited) == 0:
            self.report += '\n\n'
            return self

        self.error_flag = True

        self.report += "These are url's in the golden file that were not visited:\n"
        self.report += '\n'.join('{}: {}'.format(*k) for k in enumerate(sorted(urls_not_visited)))
        self.report += '\n\n'

        self.report += "These are new url's that were visited:\n"
        self.report += '\n'.join('{}: {}'.format(*k) for k in enumerate(sorted(new_urls_visited)))
        self.report += '\n\n'

        return self

    def report_link_differences(self):
        """
        Compare the current run with previous run to see if any links were added, changed or removed in visited_from
        These are comparing the visited_from array within each key of the json dictionary
        :return: self
        """

        logger.debug(f"processing report_link_differences")

        self.report += "LINK DIFFERENCES:\n\n"
        self.counts['link_differences_not_in_old'] = 0
        self.counts['link_differences_not_in_new'] = 0

        for k, v_new in self.history_new.items():

            norm_k = normalize_url((self.history_new_start_url, k))
            if norm_k != k:

                # convert to full link
                k = urljoin(self.history_golden_start_url, norm_k)

            # if some key value does not exist in golden file
            if k not in self.history_golden:

                logger.debug(f"Skipping url since it was not found in history_golden: {k}")
                continue

            v_golden = self.history_golden[k]

            # parse the url for scheme and netloc
            # generate the list of url's from golden file
            # and normalize url's that match golden file start_url
            o = urlparse(self.history_golden_start_url)
            s = urlunparse([o.scheme, o.netloc, '', '', '', ''])
            t = [(s, x) for x in v_golden["visited_from"]]
            history_golden_visited_from = list(map(normalize_url, t))

            # parse the url for scheme and netloc
            # generate the list of url's from history_new file
            # and normalize url's that match history_new file start_url
            o = urlparse(self.history_new_start_url)
            s = urlunparse([o.scheme, o.netloc, '', '', '', ''])
            t = [(s, x) for x in v_new["visited_from"]]
            history_new_visited_from = list(map(normalize_url, t))

            links_not_in_new = list_diff(history_golden_visited_from, history_new_visited_from)
            links_not_in_golden = list_diff(history_new_visited_from, history_golden_visited_from)

            if len(links_not_in_new) == 0 and len(links_not_in_golden) == 0:
                continue

            self.error_flag = True
            self.report += f"page: {k}\n"

            self.report += f"\n\tlinks that are not in new:\n\t"
            self.report += '\n\t'.join('{}: {}'.format(*k) for k in enumerate(links_not_in_new))
            self.report += '\n'
            self.report += f"\n\tlinks that are not in golden:\n\t"
            self.report += '\n\t'.join('{}: {}'.format(*k) for k in enumerate(links_not_in_golden))
            self.report += '\n'

            self.counts['link_differences_not_in_old'] += len(links_not_in_golden)
            self.counts['link_differences_not_in_new'] += len(links_not_in_new)

        self.report += '\n\n'

        return self

    def summary(self):
        """
        Summarize error and link counts
        :return: self
        """

        s = ""
        for k, v in self.counts.items():
            s += f"{k}: {v}\n"
        return s
