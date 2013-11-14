# encoding: utf-8

"""
Copyright (c) 2012 Marian Steinbach, Ernesto Ruge, Christian Scholz

Hiermit wird unentgeltlich jeder Person, die eine Kopie der Software und
der zugehörigen Dokumentationen (die "Software") erhält, die Erlaubnis
erteilt, sie uneingeschränkt zu benutzen, inklusive und ohne Ausnahme, dem
Recht, sie zu verwenden, kopieren, ändern, fusionieren, verlegen
verbreiten, unterlizenzieren und/oder zu verkaufen, und Personen, die diese
Software erhalten, diese Rechte zu geben, unter den folgenden Bedingungen:

Der obige Urheberrechtsvermerk und dieser Erlaubnisvermerk sind in allen
Kopien oder Teilkopien der Software beizulegen.

Die Software wird ohne jede ausdrückliche oder implizierte Garantie
bereitgestellt, einschließlich der Garantie zur Benutzung für den
vorgesehenen oder einen bestimmten Zweck sowie jeglicher Rechtsverletzung,
jedoch nicht darauf beschränkt. In keinem Fall sind die Autoren oder
Copyrightinhaber für jeglichen Schaden oder sonstige Ansprüche haftbar zu
machen, ob infolge der Erfüllung eines Vertrages, eines Delikts oder anders
im Zusammenhang mit der Software oder sonstiger Verwendung der Software
entstanden.
"""

import mechanize
import urllib2
import parse
import datetime
import time
import queue
from model.session import Session
from model.attachment import Attachment
from model.submission import Submission
import sys
from lxml import etree, html
from lxml.cssselect import CSSSelector
from StringIO import StringIO
import hashlib
#import pprint
import magic
import os
import logging
import requests
import pytz
import re

class ScraperAllRis(object):
    
    body_re = re.compile("<?xml .*<body[ ]*>(.*)</body>") # find everything inside a body of a subdocument
    TIME_MARKER = datetime.datetime(1903,1,1) # marker for no date being found
    
    #adoption_css = CSSSelector("#rismain table.risdeco tbody tr td table.tk1 tbody tr td table.tk1 tbody tr td table tbody tr.zl12 td.text3")
    #adoption_css = CSSSelector("table.risdeco tr td table.tk1 tr td.ko1 table.tk1 tr td table tr.zl12 td.text3")
    adoption_css = CSSSelector("tr.zl12:nth-child(3) > td:nth-child(5)") # selects the td which holds status information such as "beschlossen"
    top_css = CSSSelector("tr.zl12:nth-child(3) > td:nth-child(7) > form:nth-child(1) > input:nth-child(1)") # selects the td which holds the link to the TOP with transcript
    table_css = CSSSelector(".ko1 > table:nth-child(1)") # table with info block
    attachments_css = CSSSelector('table.risdeco table.tk1 table.tk1 table.tk1')
    #main_css = CSSSelector("#rismain table.risdeco")

    def __init__(self, config, db, options):
        # configuration
        self.config = config
        # command line options and defaults
        self.options = options
        # database object
        self.db = db
        # mechanize user agent
        self.user_agent = mechanize.Browser()
        self.user_agent.set_handle_robots(False)
        self.user_agent.addheaders = [('User-agent', config.USER_AGENT_NAME)]
        # Queues
        #if self.options.workfromqueue:
        self.session_queue = queue.Queue('SCRAPEARIS_SESSIONS', config, db)
        self.submission_queue = queue.Queue('SCRAPEARIS_SUBMISSIONS', config, db)
        # system info (PHP/ASP)
        self.template_system = None
        self.urls = None
        self.xpath = None

    def work_from_queue(self):
        """
        Empty queues if they have values. Queues are emptied in the
        following order:
        1. Sessions
        2. Submissions
        """
        while self.session_queue.has_next():
            job = self.session_queue.get()
            self.get_session(session_id=job['key'])
            self.session_queue.resolve_job(job)
        while self.submission_queue.has_next():
            job = self.submission_queue.get()
            self.get_submission(submission_id=job['key'])
            self.submission_queue.resolve_job(job)
        # when everything is done, we remove DONE jobs
        self.session_queue.garbage_collect()
        self.submission_queue.garbage_collect()

    def guess_system(self):
        """
        Tries to find out which AllRis version we are working with
        and adapts configuration
        TODO: XML Guess
        """
        self.template_system = 'xml'
        logging.info("Nothing to guess until now.")
        if self.options.verbose:
            print "Nothing to guess until now"


    def find_sessions(self, start_date=None, end_date=None):
        """
        Find sessions within a given time frame and add them to the session queue.
        """
        sessions_url = "%ssi010.asp?selfaction=ws&template=xyz&kaldatvon=%s&kaldatbis=%s" % (self.config.BASE_URL, start_date.strftime("%d.%m.%Y"), end_date.strftime("%d.%m.%Y"))
        logging.info("Getting meeting overview from %s", sessions_url)
        print "Getting meeting overview from %s" %(sessions_url)
        
        
        parser = etree.XMLParser(recover=True)
        r = requests.get(sessions_url)
        xml = r.text.encode('ascii','xmlcharrefreplace') 
        root = etree.fromstring(xml, parser=parser)

        for item in root[1].iterchildren():
            raw_meeting = {}
            for e in item.iterchildren():
                raw_meeting[e.tag] = e.text

            meeting = Session(int(raw_meeting['silfdnr']))
            meeting.start_date = self.parse_date(raw_meeting['sisbvcs'])
            meeting.end_date = self.parse_date(raw_meeting['sisevcs'])
            meeting.identifier = raw_meeting['siname']
            meeting.original_url = "%sto010.asp?SILFDNR=%s&options=4" % (self.config.BASE_URL, raw_meeting['silfdnr'])
            meeting.title = raw_meeting['sitext']
            meeting.committee_name = raw_meeting['grname']
            meeting.description = raw_meeting['sitext']
            oid = self.db.save_session(meeting)
            self.session_queue.add(meeting.numeric_id)
    
    
    def get_session(self, session_url=None, session_id=None):
        """
        Load session details = agendaitems for the given detail page URL or numeric ID
        """
        session_url = "%sto010.asp?selfaction=ws&template=xyz&SILFDNR=%s" % (self.config.BASE_URL, session_id)
        
        logging.info("Getting meeting %d from %s", session_id, session_url)
        print "Getting meeting %d from %s" %( session_id, session_url)
        
        r = requests.get(session_url)
        # If r.history has an element in it it's an 302 forward which means access is forbidden
        if len(r.history):
            logging.info("Meeting %d from %s seems to be private", session_id, session_url)
            print "Meeting %d from %s seems to be private" % (session_id, session_url)
            return
        xml = r.text.encode('ascii','xmlcharrefreplace') 
        parser = etree.XMLParser(recover=True)
        root = etree.fromstring(xml, parser=parser)
        
        meeting = Session(session_id)
        record = {'tops' : []}

        special = {}
        for item in root[1].iterchildren():
            special[item.tag] = item.text
        record['special'] = special

        meeting.room = special['raname']
        meeting.address = special['raort']
        
        agendaitems = {}
        for item in root[2].iterchildren():
            elem = {}
            for e in item.iterchildren():
                elem[e.tag] = e.text

            section = [elem['tofnum'], elem['tofunum'], elem['tofuunum']]
            section = [x for x in section if x!="0"]
            elem['section'] = ".".join(section)
            agendaitem = {}
            
            agendaitem['number'] = elem['topnr']
            agendaitem['id'] = int(elem['tolfdnr'])
            if elem['toostLang'] == u'öffentlich':
                agendaitem['public'] = True
            else:
                agendaitem['public'] = False
            agendaitem['subject'] = elem['totext1']
            # get agenda detail page
            agendaitem_url = '%sto020.asp?selfaction=ws&template=xyz&TOLFDNR=%s' % (self.config.BASE_URL, agendaitem['id'])
            logging.info("Getting agendaitem %d from %s", agendaitem['id'], agendaitem_url)
            print "Getting agendaitem %d from %s" % (agendaitem['id'], agendaitem_url)
            agendaitem_r = requests.get(agendaitem_url)
            agendaitem_xml = agendaitem_r.text.encode('ascii','xmlcharrefreplace') 
            agendaitem_parser = etree.XMLParser(recover=True)
            agendaitem_root = etree.fromstring(agendaitem_xml, parser=parser)
            add_agenda_item = {}
            for add_item in agendaitem_root[0].iterchildren():
                if add_item.tag == "rtfWP" and len(add_item) > 0:
                    try:
                        agendaitem["transcript"] = etree.tostring(add_item[0][1][0])
                    except:
                        print etree.tostring(add_item)
                        raise
                else:
                    add_agenda_item[add_item.tag] = add_item.text
            if 'voname' in add_agenda_item:
                # create submission with identifier
                agendaitem['submissions'] = [Submission(numeric_id = int(elem['volfdnr']), identifier=add_agenda_item['voname'], subject=add_agenda_item['vobetr'])]
                if hasattr(self, 'submission_queue'):
                    self.submission_queue.add(int(elem['volfdnr']))
            elif int(elem['volfdnr']) is not 0:
                # create submission without identifier
                agendaitem['submissions'] = [Submission(numeric_id = int(elem['volfdnr']))]
                if hasattr(self, 'submission_queue'):
                    self.submission_queue.add(int(elem['volfdnr']))
            if "nowDate" not in add_agenda_item:
                # something is broken with this so we don't store it
                print "Skipping broken agenda at ", agendaitem_url
            else:
                # dereference result
                if add_agenda_item['totyp'] in self.config.RESULT_STRINGS:
                    agendaitem['result'] = self.config.RESULT_STRINGS[add_agenda_item['totyp']]
                else:
                    logging.warn("String '%s' not found in configured RESULT_STRINGS", add_agenda_item['totyp'])
                    if self.options.verbose:
                        print "WARNING: String '%s' not found in RESULT_STRINGS\n" % add_agenda_item['totyp']
            agendaitems[agendaitem['id']] = agendaitem
        meeting.agendaitems = agendaitems.values()
        oid = self.db.save_session(meeting)
        if self.options.verbose:
            logging.info("Session %d stored with _id %s", session_id, oid)
        

    def get_submission(self, submission_url=None, submission_id=None):
        """
        Load submission (Vorlage) details for the submission given by detail page URL
        or numeric ID
        """
        submission_url = '%svo020.asp?VOLFDNR=%s' % (self.config.BASE_URL, submission_id)
        logging.info("Getting submission %d from %s", submission_id, submission_url)
        print "Getting submission %d from %s" % (submission_id, submission_url)

        response = requests.get(submission_url)
        if "noauth" in response.url:
            print "Submission %s in %s seems to private", submission_id, submission_url
            return
        text = self.preprocess_text(response.text)
        doc = html.fromstring(text)
        data = {}
        
        # Beratungsfolge-Table checken
        table = self.table_css(doc)[0] # lets hope we always have this table
        self.consultation_list_start = False
        last_headline = ''
        for line in table:
            headline = line[0].text
            if headline:
                headline = headline.split(":")[0].lower()
                if headline[-1]==":":
                    headline = headline[:-1]
                if headline == "betreff":
                    value = line[1].text_content().strip()
                    value = value.split("-->")[1]               # there is some html comment with a script tag in front of the text which we remove
                    data[headline] = " ".join(value.split())    # remove all multiple spaces from the string
                elif headline in ['verfasser', u'federführend', 'drucksache-art']:
                    data[headline] = line[1].text.strip()
                elif headline in ['status']:
                    data[headline] = line[1].text.strip()
                    if len(line) > 2:
                        if len(line[3]):
                            # gets identifier. is there something else at this position? (will break)
                            data['identifier'] = line[3][0][0][1][0].text
                elif headline == "beratungsfolge":
                    # the actual list will be in the next row inside a table, so we only set a marker
                    data = self.parse_consultation_list_headline(line, data) # for parser which have the consultation list here
                elif self.consultation_list_start:
                    data = self.parse_consultation_list(line, data) # for parser which have the consultation list in the next tr
                    self.consultation_list_start = False # set the marker to False again as we have read it
            last_headline = headline
            # we simply ignore the rest (there might not be much more actually)

        # the actual text comes after the table in a div but it's not valid XML or HTML this using regex
        data['docs'] = self.body_re.findall(response.text)
        
        submission = Submission(numeric_id = submission_id)
        submission.original_url = submission_url
        submission.title = data['betreff']
        submission.description = data['docs']
        submission.type = data['drucksache-art']
        if 'identifier' in data:
            submission.identifier = data['identifier']
        
        submission.attachments = []
        # get the attachments if possible
        attachments = self.attachments_css(doc)
        if len(attachments) > 0:
            if len(attachments[0]) > 1:
                if attachments[0][1][0].text.strip() == "Anlagen:":
                    for tr in attachments[0][2:]:
                        link = tr[0][0]
                        href = "%s%s" % (self.config.BASE_URL, link.attrib["href"])
                        name = link.text
                        identifier = str(int(link.attrib["href"].split('/')[4]))
                        attachment = Attachment(
                            identifier=identifier,
                            name=link.text)
                        attachment = self.get_attachment_file(attachment, href)
                        submission.attachments.append(attachment)
                        
        oid = self.db.save_submission(submission)
        
    def get_attachment_file(self, attachment, attachment_url):
        """
        Loads the attachment file from the server and stores it into
        the attachment object given as a parameter. The form
        parameter is the mechanize Form to be submitted for downloading
        the attachment.

        The attachment parameter has to be an object of type
        model.attachment.Attachment.
        """
        time.sleep(self.config.WAIT_TIME)
        logging.info("Getting attachment '%s'", attachment.identifier)
        
        #if self.options.verbose:
        print "Getting attachment %s from %s" % (attachment.identifier, attachment_url)
        
        attachment_file = requests.get(attachment_url)
        attachment.content = attachment_file.content
        attachment.mimetype = magic.from_buffer(attachment.content, mime=True)
        attachment.filename = self.make_attachment_filename(attachment.identifier, attachment.mimetype)
        return attachment

    def make_attachment_path(self, identifier):
        """
        Creates a reconstructable foder hierarchy for attachments
        """
        sha1 = hashlib.sha1(identifier).hexdigest()
        firstfolder = sha1[0:1]   # erstes Zeichen von der Checksumme
        secondfolder = sha1[1:2]  # zweites Zeichen von der Checksumme
        ret = (self.config.ATTACHMENT_FOLDER + os.sep + str(firstfolder) + os.sep +
            str(secondfolder))
        return ret

    def make_attachment_filename(self, identifier, mimetype):
        ext = 'dat'
        if mimetype in self.config.FILE_EXTENSIONS:
            ext = self.config.FILE_EXTENSIONS[mimetype]
        if ext == 'dat':
            logging.warn("No entry in config.FILE_EXTENSIONS for '%s'", mimetype)
            sys.stderr.write("WARNING: No entry in config.FILE_EXTENSIONS for '%s'\n" % mimetype)
        # Verhindere Dateinamen > 255 Zeichen
        identifier = identifier[:192]
        return identifier + '.' + ext

    def save_attachment_file(self, content, identifier, mimetype):
        """
        Creates a reconstructable folder hierarchy for attachments
        """
        folder = self.make_attachment_path(identifier)
        if not os.path.exists(folder):
            os.makedirs(folder)
        path = folder + os.sep + self.make_attachment_filename(self, identifier, mimetype)
        with open(path, 'wb') as f:
            f.write(content)
            f.close()
            return path

    def list_in_string(self, stringlist, string):
        """
        Tests if one of the strings in stringlist in contained in string.
        """
        for lstring in stringlist:
            if lstring in string:
                return True
        return False

    # mrtopf
    def parse_date(self, s):
        """parse dates like 20121219T160000Z"""
        year = int(s[0:4])
        month = int(s[4:6])
        day = int(s[6:8])
        hour = int(s[9:11])
        minute = int(s[11:13])
        second = int(s[13:15])
        return datetime.datetime(year, month, day, hour, minute, second, 0)

    # mrtopf
    def parse_consultation_list_headline(self, line, data):
        """parse the consultation list in case it is in the td next to the headline. This is the case
        for alsdorf and thus the alsdorf parser has to implement this method.
    
        @param line: the tr element which contains the consultation list
        @param data: the data so far
        @return data: the updated data element
        """
        self.consultation_list_start = True # mark that we found the headline, the table will be in the next line
        return data
    
    # mrtopf
    def parse_consultation_list(self, line, data):
        """parse the consultation list like it is for aachen. Here it is in the next line (tr) inside the first td.
        The list itself is a table which is parsed by process_consultation_list
    
        @param line: the tr element which contains the consultation list
        @param data: the data so far
        @return data: the updated data element
        """
        data['consultation'] = self.process_consultation_list(line[0]) # line is the tr, line[0] the td with the table inside
        dates = [m['date'] for m in data['consultation']]
        self.consultation_list_start = False
        return data
    
    # mrtopf
    def process_consultation_list(self, elem):
        """process the "Beratungsfolge" table in elem"""
        elem = elem[0]
        # the first line is pixel images, so skip it, then we need to jump in steps of two
        amount = (len(elem)-1)/2
        result = []
        i = 0
        item = None
        for line in elem:
            if i == 0:
                i=i+1
                continue
            """
            here we need to parse the actual list which can have different forms. A complex example
            can be found at http://ratsinfo.aachen.de/bi/vo020.asp?VOLFDNR=10822
            The first line is some sort of headline with the committee in question and the type of consultation.
            After that 0-n lines of detailed information of meetings with a date, transscript and decision.
            The first line has 3 columns (thanks to colspan) and the others have 7.
    
            Here we make every meeting a separate entry, we can group them together later again if we want to.
            """
            # now we need to parse the actual list
            # those lists
            if len(line) == 3:
                # the order is "color/status", name of committee / link to TOP, more info
                status = line[0].attrib['title'].lower()
                # we define a head dict here which can be shared for the other lines
                # once we find another head line we will create a new one here
                item = {
                    'status'    : status,               # color coded status, like "Bereit", "Erledigt"
                    'committee' : line[1].text.strip(), # name of committee, e.g. "Finanzausschuss", unfort. without id
                    'action'    : line[2].text.strip(), # e.g. "Kenntnisnahme", "Entscheidung"
                }
            else:
                # this is about line 2 with lots of more stuff to process
                # date can be text or a link with that text
                if len(line[1]) == 1: # we have a link (and ignore it)
                    item['date'] = datetime.datetime.strptime(line[1][0].text.strip(), "%d.%m.%Y")
                else:
                    item['date'] = datetime.datetime.strptime(line[1].text.strip(), "%d.%m.%Y")
                if len(line[2]):
                    form = line[2][0] # form with silfdnr and toplfdnr but only in link (action="to010.asp?topSelected=57023")
                    item['silfdnr'] = form[0].attrib['value']
                    item['meeting'] = line[3][0].text.strip()       # full name of meeting, e.g. "A/31/WP.16 öffentliche/nichtöffentliche Sitzung des Finanzausschusses"
                else:
                    item['silfdnr'] = None # no link to TOP. should not be possible but happens (TODO: Bugreport?)
                    item['meeting'] = line[3].text.strip()   # here we have no link but the text is in the TD directly
                    item['PYALLRIS_WARNING'] = "the agenda item in the consultation list on the web page does not contain a link to the actual meeting"
                    print "WARNING:", item['PYALLRIS_WARNING']
                item['decision'] = line[4].text.strip()         # e.g. "ungeändert beschlossen"
                toplfdnr = None
                if len(line[6]) > 0:
                    form = line[6][0]
                    toplfdnr = form[0].attrib['value']
                item['toplfdnr'] = toplfdnr                     # actually the id of the transcript 
                result.append(item)
            i=i+1
        return result

    # mrtopf
    def preprocess_text(self, text):
        """preprocess the incoming text, e.g. do some encoding etc."""
        return text

class TemplateError(Exception):
    def __init__(self, message):
        Exception.__init__(self, message)
