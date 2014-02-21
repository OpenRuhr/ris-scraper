# encoding: utf-8

"""
Copyright (c) 2012 Marian Steinbach, Ernesto Ruge

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
import sys
from lxml import etree
from StringIO import StringIO
import hashlib
#import pprint
import magic
import os
import logging

from model.agendaitem import Agendaitem
from model.body import Body
from model.committee import Committee
from model.document import Document
from model.meeting import Meeting
from model.paper import Paper
from model.person import Person

class ScraperSessionNet(object):

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
    if self.options.workfromqueue:
      self.person_queue = queue.Queue('SESSIONNET_PERSON', config, db)
      self.meeting_queue = queue.Queue('SESSIONNET_MEETING', config, db)
      self.paper_queue = queue.Queue('SESSIONNET_PAPER', config, db)
    # system info (PHP/ASP)
    self.template_system = None
    self.urls = None
    self.xpath = None

  def work_from_queue(self):
    """
    Empty queues if they have values. Queues are emptied in the
    following order:
    1. Persons
    2. Meetings
    3. Papers
    """
    while self.person_queue.has_next():
      job = self.person_queue.get()
      #self.get_person(committee_id=job['key'])
      self.get_person_committee(person_id=job['key'])
      self.person_queue.resolve_job(job)
    while self.meeting_queue.has_next():
      job = self.meeting_queue.get()
      self.get_meeting(meeting_id=job['key'])
      self.meeting_queue.resolve_job(job)
    while self.paper_queue.has_next():
      job = self.paper_queue.get()
      self.get_paper(paper_id=job['key'])
      self.paper_queue.resolve_job(job)
    
    # when everything is done, we remove DONE jobs
    self.person_queue.garbage_collect()
    self.meeting_queue.garbage_collect()
    self.paper_queue.garbage_collect()

  def guess_system(self):
    """
    Tries to find out which SessionNet version we are working with
    and adapts configuration
    """
    time.sleep(self.config.WAIT_TIME)
    # requesting the base URL. This is usually redirected
    try:
      response = self.user_agent.open(self.config.BASE_URL)
    except urllib2.HTTPError, e:
      if e.code == 404:
        sys.stderr.write("URL not found (HTTP 404) error caught: %s\n" % self.config.BASE_URL)
        sys.stderr.write("Please check BASE_URL in your configuration.\n")
        sys.exit(1)
    url = response.geturl()
    assert (url != self.config.BASE_URL), "No redirect"
    if url.endswith('.php'):
      self.template_system = 'PHP'
    elif url.endswith('.asp'):
      self.template_system = 'ASP'
    else:
      logging.critical("Cannot guess template system from URL '%s'", url)
      sys.stderr.write("CRITICAL ERROR: Cannot guess template system from URL '%s'\n" % url)
      # there is no point in going on here.
      sys.exit(1)
    self.urls = self.config.URLS[self.template_system]
    self.xpath = self.config.XPATH[self.template_system]
    logging.info("Found %s template system.", self.template_system)
    if self.options.verbose:
      print "Found %s template system" % self.template_system


  def find_person(self):
    """
    Load committee details for the given detail page URL or numeric ID
    """
    # Read either person_id or committee_url from the opposite
    user_overview_url = self.urls['PERSON_OVERVIEW_PRINT_PATTERN']
    logging.info("Getting user overview from %s", user_overview_url)
    if self.options.verbose:
      print ("Getting user overview from %s" % user_overview_url)
    
    time.sleep(self.config.WAIT_TIME)
    response = self.get_url(user_overview_url)
    if not response:
      return
    
    # seek(0) is necessary to reset response pointer.
    response.seek(0)
    html = response.read()
    html = html.replace('&nbsp;', ' ')
    parser = etree.HTMLParser()
    dom = etree.parse(StringIO(html), parser)
    
    trs = dom.xpath(self.xpath['PERSONLIST_LINES'])
    for tr in trs:
      current_person = None
      link = tr.xpath('.//a')
      if len(link):
        parsed = parse.search(self.urls['PERSON_DETAIL_PARSE_PATTERN'], link[0].get('href'))
        if parsed:
          person_id = parsed['person_id']
          current_person = Person(numeric_id=person_id)
      if current_person:
        tds = tr.xpath('.//td')
        if len(tds):
          if len(tds[0]):
            person_name = tds[0][0].text.strip()
            if person_name:
              current_person.title = person_name
        if len(tds) > 1:
          person_party = tds[1].text.strip()
          if person_party:
            if person_party in self.config.PARTY_ALIAS:
              person_party = self.config.PARTY_ALIAS[person_party]
            current_person.committee = [{'committee': Committee(identifier=person_party, title=person_party, type='party')}]
        if current_person:
          if hasattr(self, 'person_queue'):
            self.person_queue.add(current_person.numeric_id)
          self.db.save_person(current_person)
    return

  def find_meeting(self, start_date=None, end_date=None):
    """
    Find meetings (sessions) within a given time frame and add them to the session queue.
    """
    # list of (year, month) tuples to work from
    start_month = start_date.month
    end_months = (end_date.year - start_date.year) * 12 + end_date.month + 1
    monthlist = [(yr, mn) for (yr, mn) in (
      ((m - 1) / 12 + start_date.year, (m - 1) % 12 + 1) for m in range(start_month, end_months)
    )]
  
    for (year, month) in monthlist:
      url = self.urls['CALENDAR_MONTH_PRINT_PATTERN'] % (year, month)
      logging.info("Looking for meetings (sessions) in %04d-%02d at %s", year, month, url)
      time.sleep(self.config.WAIT_TIME)
      response = self.user_agent.open(url)
      html = response.read()
      html = html.replace('&nbsp;', ' ')
      parser = etree.HTMLParser()
      dom = etree.parse(StringIO(html), parser)
      found = 0
      for link in dom.xpath('//a'):
        href = link.get('href')
        if href is None:
          continue
        parsed = parse.search(self.urls['SESSION_DETAIL_PARSE_PATTERN'], href)
        if hasattr(self, 'meeting_queue') and parsed is not None:
          self.meeting_queue.add(int(parsed['meeting_id']))
          found += 1
      if found == 0:
        logging.info("No meetings(sessions) found for month %04d-%02d", year, month)
        if self.options.verbose:
          print "No meetings (sessions) found for month %04d-%02d\n" % (year, month)
  
  def get_person(self, person_url=None, person_id=None):
    """
    Load committee details for the given detail page URL or numeric ID
    """
    # Read either person_id or committee_url from the opposite
    if person_id is not None:
      person_url = self.urls['COMMITTEE_DETAIL_PRINT_PATTERN_FULL'] % person_id
    elif person_url is not None:
      parsed = parse.search(self.urls['COMMITTEE_DETAIL_PARSE_PATTERN_FULL'], person_url)
      person_id = parsed['person_id']
  
    logging.info("Getting meeting (committee) %d from %s", person_id, person_url)
    if self.options.verbose:
      print ("Getting meeting (committee) %d from %s" % (person_id, person_url))
    
    committee = Committee(numeric_id=person_id)
    
    time.sleep(self.config.WAIT_TIME)
    response = self.get_url(person_url)
    if not response:
      return
    
    # seek(0) is necessary to reset response pointer.
    response.seek(0)
    html = response.read()
    html = html.replace('&nbsp;', ' ')
    parser = etree.HTMLParser()
    dom = etree.parse(StringIO(html), parser)
    
    trs = dom.xpath(self.xpath['COMMITTEE_LINES'])
    for tr in trs:
      tds = tr.xpath('.//td')
      print tds
      if tr.get('class') == 'smcrowh':
        print tds[0].text
      else:
        for td in tds:
          print td[0].text
    return
  
  def get_person_committee(self, person_committee_url=None, person_id=None):
    """
    Load committee details for the given detail page URL or numeric ID
    """
    # Read either committee_id or committee_url from the opposite
    if person_id is not None:
      person_committee_url = self.urls['PERSON_COMMITTEE_PRINT_PATTERN'] % person_id
    elif person_committee_url is not None:
      parsed = parse.search(self.urls['PERSON_COMMITTEE_PRINT_PATTERN'], person_committee_url)
      person_id = parsed['person_id']
  
    logging.info("Getting meeting (committee) %d from %s", person_id, person_committee_url)
    if self.options.verbose:
      print ("Getting person committee detail page %d from %s" % (person_id, person_committee_url))
    
    person = Person(numeric_id=person_id)
    
    time.sleep(self.config.WAIT_TIME)
    response = self.get_url(person_committee_url)
    if not response:
      return
    
    # seek(0) is necessary to reset response pointer.
    response.seek(0)
    html = response.read()
    html = html.replace('&nbsp;', ' ')
    parser = etree.HTMLParser()
    dom = etree.parse(StringIO(html), parser)
    
    trs = dom.xpath(self.xpath['PERSON_COMMITTEE_LINES'])
    committees = []
    for tr in trs:
      new_committee = None
      tds = tr.xpath('.//td')
      if len(tds) == 5:
        if tds[0].xpath('.//a'):
          href = tds[0][0].get('href')
          parsed = parse.search(self.urls['COMMITTEE_DETAIL_PARSE_PATTERN'], href)
          if not parsed:
            parsed = parse.search(self.urls['COMMITTEE_DETAIL_PARSE_PATTERN_FULL'], href)
          if parsed is not None:
            new_committee = { 'committee': Committee(numeric_id=int(parsed['committee_id']))}
            new_committee['committee'].identifier = tds[0][0].text
            new_committee['committee'].title = tds[0][0].text
        else:
          new_committee = {'committee': Committee(identifier=tds[0].text)}
        if new_committee:
          new_committee['position'] = tds[2].text
          if tds[3].text:
            new_committee['start'] = tds[3].text
          if tds[4].text:
            new_committee['end'] = tds[4].text
        else:
          logging.error("Bad Table Structure in %s", person_committee_url)
          if self.options.verbose:
            print ("Bad Table Structure in %s" % person_committee_url)
      if new_committee:
        committees.append(new_committee)
    if committees:
      person.committee = committees
    return
  
  def get_meeting(self, meeting_url=None, meeting_id=None):
    """
    Load meeting details for the given detail page URL or numeric ID
    """
    # Read either meeting_id or meeting_url from the opposite
    if meeting_id is not None:
      meeting_url = self.urls['SESSION_DETAIL_PRINT_PATTERN'] % meeting_id
    elif meeting_url is not None:
      parsed = parse.search(self.urls['SESSION_DETAIL_PARSE_PATTERN'], meeting_url)
      meeting_id = parsed['meeting_id']
  
    logging.info("Getting meeting (session) %d from %s", meeting_id, meeting_url)
    if self.options.verbose:
      print ("Getting meeting (session) %d from %s" % (meeting_id, meeting_url))
  
    meeting = Meeting(numeric_id=meeting_id)
    
    time.sleep(self.config.WAIT_TIME)
    response = self.get_url(meeting_url)
    if not response:
      return
    
    # forms for later document download
    mechanize_forms = mechanize.ParseResponse(response, backwards_compat=False)
    # seek(0) is necessary to reset response pointer.
    response.seek(0)
    html = response.read()
    html = html.replace('&nbsp;', ' ')
    parser = etree.HTMLParser()
    dom = etree.parse(StringIO(html), parser)
    # check for page errors
    try:
      page_title = dom.xpath('//h1')[0].text
      if 'Fehlermeldung' in page_title:
        logging.info("Page %s cannot be accessed due to server error", meeting_url)
        if self.options.verbose:
          print "Page %s cannot be accessed due to server error" % meeting_url
        return
      if 'Berechtigungsfehler' in page_title:
        logging.info("Page %s cannot be accessed due to permissions", meeting_url)
        if self.options.verbose:
          print "Page %s cannot be accessed due to permissions" % meeting_url
        return
    except:
      pass
    try:
      error_h3 = dom.xpath('//h3[@class="smc_h3"]')[0].text.strip()
      if 'Keine Daten gefunden' in error_h3:
        logging.info("Page %s does not contain any agenda items", meeting_url)
        if self.options.verbose:
          print "Page %s does not contain agenda items" % meeting_url
        return
      if 'Fehlercode: 1104' in error_h3:
        logging.info("Page %s cannot be accessed due to permissions", meeting_url)
        if self.options.verbose:
          print "Page %s cannot be accessed due to permissions" % meeting_url
        return
    except:
      pass
  
    meeting.original_url = meeting_url
    # Session title
    try:
      meeting.title = dom.xpath(self.xpath['SESSION_DETAIL_TITLE'])[0].text
    except:
      logging.critical('Cannot find session title element using XPath SESSION_DETAIL_TITLE')
      raise TemplateError('Cannot find session title element using XPath SESSION_DETAIL_TITLE')
  
    # Committe link
    try:
      links = dom.xpath(self.xpath['SESSION_DETAIL_COMMITTEE_LINK'])
      for link in links:
        href = link.get('href')
        parsed = parse.search(self.urls['COMMITTEE_DETAIL_PARSE_PATTERN'], href)
        if parsed is not None:
          meeting.committees = [Commitee(numeric_id=int(parsed['committee_id']))]
          if hasattr(self, 'committee_queue'):
            self.committee_queue.add(int(parsed['committee_id']))
    except:
      logging.critical('Cannot find link to committee detail page using SESSION_DETAIL_COMMITTEE_LINK_XPATH')
      raise TemplateError('Cannot find link to committee detail page using SESSION_DETAIL_COMMITTEE_LINK_XPATH')
  
    # Meeting identifier, date, address etc
    tds = dom.xpath(self.xpath['SESSION_DETAIL_IDENTIFIER_TD'])
    if len(tds) == 0:
      logging.critical('Cannot find table fields using SESSION_DETAIL_IDENTIFIER_TD_XPATH at session ' + meeting_url)
      raise TemplateError('Cannot find table fields using SESSION_DETAIL_IDENTIFIER_TD_XPATH at session ' + meeting_url)
    else:
      for n in range(0, len(tds)):
        try:
          tdcontent = tds[n].text.strip()
          nextcontent = tds[n + 1].text.strip()
        except:
          continue
        if tdcontent == 'Sitzung:':
          meeting.identifier = nextcontent
        # We don't need this any more because it's scraped in committee detail page(?)
        #elif tdcontent == 'Gremium:':
        #  meeting.committee_name = nextcontent
        elif tdcontent == 'Datum:':
          start = nextcontent
          end = nextcontent
          if tds[n + 2].text == 'Zeit:':
            if tds[n + 3].text is not None:
              times = tds[n + 3].text.replace(' Uhr', '').split('-')
              start = start + ' ' + times[0]
              if len(times) > 1:
                end = end + ' ' + times[1]
              else:
                end = start
            meeting.start = start
            meeting.end = end
        elif tdcontent == 'Raum:':
          meeting.address = " ".join(tds[n + 1].xpath('./text()'))
        elif tdcontent == 'Bezeichnung:':
          meeting.description = nextcontent
        if not hasattr(meeting, 'identifier'):
          logging.critical('Cannot find session identifier using XPath SESSION_DETAIL_IDENTIFIER_TD')
          raise TemplateError('Cannot find session identifier using XPath SESSION_DETAIL_IDENTIFIER_TD')
  
    # Agendaitems
    found_documents = []
    rows = dom.xpath(self.xpath['SESSION_DETAIL_AGENDA_ROWS'])
    if len(rows) == 0:
      logging.critical('Cannot find agenda using XPath SESSION_DETAIL_AGENDA_ROWS')
      raise TemplateError('Cannot find agenda using XPath SESSION_DETAIL_AGENDA_ROWS')
      meeting.agendaitem = []
    else:
      agendaitems = []
      agendaitem_id = None
      public = True
      agendaitem = None
      for row in rows:
        row_id = row.get('id')
        row_classes = row.get('class').split(' ')
        fields = row.xpath('td')
        number = fields[0].xpath('./text()')
        if len(number) > 0:
          number = number[0]
        else:
          # when theres a updated notice theres an additional spam
          number = fields[0].xpath('.//span/text()')
          if len(number) > 0:
            number = number[0]
        if number == []:
          number = None
        if row_id is not None:
          # Agendaitem main row
          # first: save agendaitem from before
          if agendaitem:
            agendaitems.append(agendaitem)
          # create new agendaitem
          agendaitem = Agendaitem(numeric_id=int(row_id.rsplit('_', 1)[1]))
          if number is not None:
            agendaitem.sequence_number = number
          # in some ris this is a link, sometimes not. test both.
          if len(fields[1].xpath('./a/text()')):
            agendaitem.title = "; ".join(fields[1].xpath('./a/text()'))
          elif len(fields[1].xpath('./text()')):
            agendaitem.title = "; ".join(fields[1].xpath('./text()'))
          # ignore no agendaitem information
          if agendaitem.title == 'keine Tagesordnungspunkte':
            agendaitem = None
            continue
          agendaitem.public = public
          # paper links
          links = row.xpath(self.xpath['SESSION_DETAIL_AGENDA_ROWS_SUBMISSION_LINK'])
          papers = []
          for link in links:
            href = link.get('href')
            if href is None:
              continue
            parsed = parse.search(self.urls['SUBMISSION_DETAIL_PARSE_PATTERN'], href)
            if parsed is not None:
              paper = Paper(numeric_id=int(parsed['paper_id']), identifier=link.text)
              papers.append(paper)
              # Add paper to paper queue
              if hasattr(self, 'paper_queue'):
                self.paper_queue.add(int(parsed['paper_id']))
          if len(papers):
            agendaitem.paper = papers
          """
          Note: we don't scrape agendaitem-related documents for now,
          based on the assumption that they are all found via paper
          detail pages. All we do here is get a list of document IDs
          in found_documents
          """
          # find links
          links = row.xpath('.//a[contains(@href,"getfile.")]')
          for link in links:
            if not link.xpath('.//img'):
              file_link = self.config.BASE_URL + link.get('href')
              document_id = file_link.split('id=')[1].split('&')[0]
              found_documents.append(document_id)
          # find forms
          forms = row.xpath('.//form')
          for form in forms:
            for hidden_field in form.xpath('input'):
              if hidden_field.get('name') != 'DT':
                continue
              document_id = hidden_field.get('value')
              found_documents.append(document_id)
        # Alternative für smc_tophz wegen Version 4.3.5 bi (Layout 3)
        elif ('smc_tophz' in row_classes) or (row.get('valign') == 'top' and row.get('debug') == '3'):
          # additional (optional row for agendaitem)
          label = fields[1].text
          value = fields[2].text
          if label is not None and value is not None:
            label = label.strip()
            value = value.strip()
            if label in ['Ergebnis:', 'Beschluss:', 'Beratungsergebnis:']:
              if value in self.config.RESULT_STRINGS:
                agendaitem.result = self.config.RESULT_STRINGS[value]
              else:
                logging.warn("String '%s' not found in configured RESULT_STRINGS", value)
                if self.options.verbose:
                  print "WARNING: String '%s' not found in RESULT_STRINGS\n" % value
              agendaitem.result = value
            elif label == 'Bemerkung:':
              agendaitem.result_details = value
            # What's this?
            #elif label == 'Abstimmung:':
            #  agendaitems[agendaitem_id]['voting'] = value
            else:
              logging.critical("Agendaitem info label '%s' is unknown", label)
              raise ValueError('Agendaitem info label "%s" is unknown' % label)
        elif 'smcrowh' in row_classes:
          # Subheading (public / nonpublic part)
          if fields[0].text is not None and "Nicht öffentlich" in fields[0].text.encode('utf-8'):
            public = False
      
      #print json.dumps(agendaitems, indent=2)
      meeting.agendaitem = agendaitems

    # meeting-related documents
    containers = dom.xpath(self.xpath['SESSION_DETAIL_ATTACHMENTS'])
    for container in containers:
      classes = container.get('class')
      if classes is None:
        continue
      classes = classes.split(' ')
      if self.xpath['SESSION_DETAIL_ATTACHMENTS_CONTAINER_CLASSNAME'] not in classes:
        continue
      documents = []
      rows = container.xpath('.//tr')
      for row in rows:
        if not row.xpath('.//form'):
          links = row.xpath('.//a')
          for link in links:
            # ignore additional pdf icon links
            if not link.xpath('.//img'):
              title = ' '.join(link.xpath('./text()')).strip()
              file_link = self.config.BASE_URL + link.get('href')
              document_id = file_link.split('id=')[1].split('&')[0]
              if document_id in found_documents:
                continue
              document = Document(
                identifier=document_id,
                numeric_id=document_id,
                title=title,
                original_url=file_link)
              document = self.get_document_file(document=document, link=file_link)
              if 'Einladung' in title:
                document_type = 'invitation'
              elif 'Niederschrift' in title:
                document_type = 'results_protocol'
              else:
                document_type = 'misc'
              documents.append({'relation': document_type, 'document': document})
              found_documents.append(document_id)
        else:
          forms = row.xpath('.//form')
          for form in forms:
            #print "Form: ", form
            title = " ".join(row.xpath('./td/text()')).strip()
            for hidden_field in form.xpath('input'):
              if hidden_field.get('name') != 'DT':
                continue
              document_id = hidden_field.get('value')
              # make sure to add only those which aren't agendaitem-related
              if document_id not in found_documents:
                document = Document(
                  identifier=document_id,
                  numeric_id=document_id,
                  title=title
                )
                # Traversing the whole mechanize response to submit this form
                for mform in mechanize_forms:
                  #print "Form found: '%s'" % mform
                  for control in mform.controls:
                    if control.name == 'DT' and control.value == document_id:
                      #print "Found matching form: ", control.name, control.value
                      document = self.get_document_file(document, mform)
                if 'Einladung' in title:
                  document_type = 'invitation'
                elif 'Niederschrift' in title:
                  document_type = 'results_protocol'
                else:
                  document_type = 'misc'
                documents.append({'relation': document_type, 'document': document})
                found_documents.append(document_id)
      if len(documents):
        meeting.document = documents
    oid = self.db.save_meeting(meeting)
    if self.options.verbose:
      logging.info("Meeting %d stored with _id %s", meeting_id, oid)


  def get_paper(self, paper_url=None, paper_id=None):
    """
    Load paper details for the paper given by detail page URL
    or numeric ID
    """
    # Read either paper_id or paper_url from the opposite
    if paper_id is not None:
      paper_url = self.urls['SUBMISSION_DETAIL_PRINT_PATTERN'] % paper_id
    elif paper_url is not None:
      parsed = parse.search(self.urls['SUBMISSION_DETAIL_PARSE_PATTERN'], paper_url)
      paper_id = parsed['paper_id']
  
    logging.info("Getting paper %d from %s", paper_id, paper_url)
    if self.options.verbose:
      print ("Getting paper %d from %s" % (paper_id, paper_url))
    
    paper = Paper(numeric_id=paper_id)
    try_until = 1
    try_counter = 0
    try_found = False
    
    while (try_counter < try_until):
      try_counter += 1
      try_found = False
      time.sleep(self.config.WAIT_TIME)
      try:
        response = self.user_agent.open(paper_url)
      except urllib2.HTTPError, e:
        if e.code == 404:
          sys.stderr.write("URL not found (HTTP 404) error caught: %s\n" % paper_url)
          sys.stderr.write("Please check BASE_URL in your configuration.\n")
          sys.exit(1)
        elif e.code == 502:
          try_until = 4
          try_found = True
          if try_until == try_counter:
            logging.error("Permanent error in %s after 4 retrys.", paper_url)
            return
          else:
            logging.info("Original RIS Server Bug, restart scraping paper %s", paper_url)
      mechanize_forms = mechanize.ParseResponse(response, backwards_compat=False)
      response.seek(0)
      html = response.read()
      html = html.replace('&nbsp;', ' ')
      parser = etree.HTMLParser()
      dom = etree.parse(StringIO(html), parser)
      # Hole die Seite noch einmal wenn unbekannter zufällig auftretender Fehler ohne Fehlermeldung ausgegeben wird (gefunden in Duisburg, vermutlich kaputte Server Config)
      try:
        page_title = dom.xpath('//h1')[0].text
        if 'Fehler' in page_title:
          try_until = 4
          try_found = True
          if try_until == try_counter:
            logging.error("Permanent error in %s after 3 retrys, proceed.", paper_url)
          else:
            logging.info("Original RIS Server Bug, restart scraping paper %s", paper_url)
      except:
        pass
      if (try_found == False):
        # check for page errors
        try:
          if 'Fehlermeldung' in page_title:
            logging.info("Page %s cannot be accessed due to server error", paper_url)
            if self.options.verbose:
              print "Page %s cannot be accessed due to server error" % paper_url
            return
          if 'Berechtigungsfehler' in page_title:
            logging.info("Page %s cannot be accessed due to permissions", paper_url)
            if self.options.verbose:
              print "Page %s cannot be accessed due to permissions" % paper_url
            return
        except:
          pass
    
        paper.original_url = paper_url
        paper_related = []
        # Paper title
        try:
          stitle = dom.xpath(self.xpath['SUBMISSION_DETAIL_TITLE'])
          paper.title = stitle[0].text
        except:
          logging.critical('Cannot find paper title element using XPath SUBMISSION_DETAIL_TITLE')
          raise TemplateError('Cannot find paper title element using XPath SUBMISSION_DETAIL_TITLE')
      
        # Submission identifier, date, type etc
        tds = dom.xpath(self.xpath['SUBMISSION_DETAIL_IDENTIFIER_TD'])
        if len(tds) == 0:
          logging.critical('Cannot find table fields using XPath SUBMISSION_DETAIL_IDENTIFIER_TD')
          logging.critical('HTML Dump:' + html)
          raise TemplateError('Cannot find table fields using XPath SUBMISSION_DETAIL_IDENTIFIER_TD')
        else:
          current_category = None
          for n in range(0, len(tds)):
            try:
              tdcontent = tds[n].text.strip()
            except:
              continue
            if tdcontent == 'Name:':
              paper.identifier = tds[n + 1].text.strip()
            elif tdcontent == 'Art:':
              paper.type = tds[n + 1].text.strip()
            elif tdcontent == 'Datum:':
              paper.date = tds[n + 1].text.strip()
            elif tdcontent == 'Name:':
              paper.identifier = tds[n + 1].text.strip()
            elif tdcontent == 'Betreff:':
              paper.subject = '; '.join(tds[n + 1].xpath('./text()'))
            elif tdcontent == 'Aktenzeichen:':
              paper.reference_number = tds[n + 1].text.strip()
            elif tdcontent == 'Referenzvorlage:':
              link = tds[n + 1].xpath('a')[0]
              href = link.get('href')
              parsed = parse.search(self.urls['SUBMISSION_DETAIL_PARSE_PATTERN'], href)
              superordinated_paper = Paper(numeric_id=parsed['paper_id'], identifier=link.text.strip())
              paper_related.append({ 'relation': 'superordinated',
                              'paper':  superordinated_paper})
              # add superordinate paper to queue
              if hasattr(self, 'paper_queue'):
                self.paper_queue.add(parsed['paper_id'])
            # subordinate papers are added to the queue
            elif tdcontent == 'Untergeordnete Vorlage(n):':
              current_category = 'subordinates'
              for link in tds[n + 1].xpath('a'):
                href = link.get('href')
                parsed = parse.search(self.urls['SUBMISSION_DETAIL_PARSE_PATTERN'], href)
                subordinated_paper = Paper(numeric_id=parsed['paper_id'], identifier=link.text.strip())
                paper_related.append({ 'relation': 'subordinated',
                              'paper':  subordinated_paper})
                if hasattr(self, 'paper_queue') and parsed is not None:
                  # add subordinate paper to queue
                  self.paper_queue.add(parsed['paper_id'])
            else:
              if current_category == 'subordinates' and len(tds) > n+1:
                for link in tds[n + 1].xpath('a'):
                  href = link.get('href')
                  parsed = parse.search(self.urls['SUBMISSION_DETAIL_PARSE_PATTERN'], href)
                  subordinated_paper = Paper(numeric_id=parsed['paper_id'], identifier=link.text.strip())
                  paper_related.append({ 'relation': 'subordinated',
                                'paper':  subordinated_paper})
                  if hasattr(self, 'paper_queue') and parsed is not None:
                    self.paper_queue.add(parsed['paper_id'])
          if len(paper_related):
            paper.paper = paper_related
          if not hasattr(paper, 'identifier'):
            logging.critical('Cannot find paper identifier using SESSION_DETAIL_IDENTIFIER_TD_XPATH')
            raise TemplateError('Cannot find paper identifier using SESSION_DETAIL_IDENTIFIER_TD_XPATH')
      
        # "Beratungsfolge"(list of sessions for this paper)
        # This is currently not parsed for scraping, but only for
        # gathering session-document ids for later exclusion
        found_documents = []
        rows = dom.xpath(self.xpath['SUBMISSION_DETAIL_AGENDA_ROWS'])
        for row in rows:
          # find forms
          formfields = row.xpath('.//input[@type="hidden"][@name="DT"]')
          for formfield in formfields:
            document_id = formfield.get('value')
            if document_id is not None:
              found_documents.append(document_id)
          # find links
          links = row.xpath('.//a[contains(@href,"getfile.")]')
          for link in links:
            if not link.xpath('.//img'):
              file_link = self.config.BASE_URL + link.get('href')
              document_id = file_link.split('id=')[1].split('&')[0]
              found_documents.append(document_id)
        # paper-related documents
        documents = []
        paper.document = []
        containers = dom.xpath(self.xpath['SUBMISSION_DETAIL_ATTACHMENTS'])
        for container in containers:
          try:
            classes = container.get('class').split(' ')
          except:
            continue
          if self.xpath['SUBMISSION_DETAIL_ATTACHMENTS_CONTAINER_CLASSNAME'] not in classes:
            continue
          rows = container.xpath('.//tr')
          for row in rows:
            # seems that we have direct links
            if not row.xpath('.//form'):
              links = row.xpath('.//a')
              for link in links:
                # ignore additional pdf icon links
                if not link.xpath('.//img'):
                  title = ' '.join(link.xpath('./text()')).strip()
                  file_link = self.config.BASE_URL + link.get('href')
                  document_id = file_link.split('id=')[1].split('&')[0]
                  if document_id in found_documents:
                    continue
                  document = Document(
                    identifier=document_id,
                    numeric_id=document_id,
                    title=title,
                    original_url=file_link)
                  document = self.get_document_file(document=document, link=file_link)
                  if 'Einladung' in title:
                    document_type = 'invitation'
                  elif 'Niederschrift' in title:
                    document_type = 'results_protocol'
                  else:
                    document_type = 'misc'
                  paper.document.append({'relation': document_type, 'document': document})
                  found_documents.append(document_id)
            # no direct link, so we have to handle forms
            else:
              forms = row.xpath('.//form')
              for form in forms:
                title = " ".join(row.xpath('./td/text()')).strip()
                for hidden_field in form.xpath('input[@name="DT"]'):
                  document_id = hidden_field.get('value')
                  if document_id in found_documents:
                    continue
                  document = Document(
                    identifier=document_id,
                    numeric_id=document_id,
                    title=title)
                  # Traversing the whole mechanize response to submit this form
                  for mform in mechanize_forms:
                    for control in mform.controls:
                      if control.name == 'DT' and control.value == document_id:
                        document = self.get_document_file(document=document, form=mform)
                        if 'Einladung' in title:
                          document_type = 'invitation'
                        elif 'Niederschrift' in title:
                          document_type = 'results_protocol'
                        else:
                          document_type = 'misc'
                        paper.document.append({'relation': document_type, 'document': document})
                        found_documents.append(document_id)
        if len(documents):
          paper.document = documents
        # forcing overwrite=True here
        oid = self.db.save_paper(paper)

  def get_document_file(self, document, form=None, link=None):
    """
    Loads the document file from the server and stores it into
    the document object given as a parameter. The form
    parameter is the mechanize Form to be submitted for downloading
    the document.
  
    The document parameter has to be an object of type
    model.document.Document.
    """
    logging.info("Getting document '%s'", document.identifier)
    if self.options.verbose:
      print "Getting document %s" % document.identifier
    if form:
      mechanize_request = form.click()
    elif link:
      mechanize_request = mechanize.Request(link)
    else:
      logging.warn("No form or link provided")
      if self.options.verbose:
        sys.stderr.write("No form or link provided")
    retry_counter = 0
    while retry_counter < 4:
      retry = False
      try:
        mform_response = mechanize.urlopen(mechanize_request)
        retry_counter = 4
        mform_url = mform_response.geturl()
        if not self.list_in_string(self.urls['ATTACHMENT_DOWNLOAD_TARGET'], mform_url) and form:
          logging.warn("Unexpected form target URL '%s'", mform_url)
          if self.options.verbose:
            sys.stderr.write("Unexpected form target URL '%s'\n" % mform_url)
          return document
        document.content = mform_response.read()
        if ord(document.content[0]) == 32 and ord(document.content[1]) == 10:
          document.content = document.content[2:]
        document.mimetype = magic.from_buffer(document.content, mime=True)
        document.filename = self.make_document_filename(document.identifier, document.mimetype)
      except mechanize.HTTPError as e:
        if e.code == 502:
          retry_counter = retry_counter + 1
          retry = True
          log.info("HTTP Error 502 while getting %s, try again", url)
          if self.options.verbose:
            print "HTTP Error 502 while getting %s, try again" % url
          time.sleep(self.config.WAIT_TIME * 5)
        else:
          logging.critical("HTTP Error %s while getting %s", e.code, url)
          sys.stderr.write("CRITICAL ERROR:HTTP Error %s while getting %s" % (e.code, url))
          return
    return document
  
  def make_document_path(self, identifier):
    """
    Creates a reconstructable foder hierarchy for documents
    """
    sha1 = hashlib.sha1(identifier).hexdigest()
    firstfolder = sha1[0:1]   # erstes Zeichen von der Checksumme
    secondfolder = sha1[1:2]  # zweites Zeichen von der Checksumme
    ret = (self.config.ATTACHMENT_FOLDER + os.sep + str(firstfolder) + os.sep +
      str(secondfolder))
    return ret
  
  def make_document_filename(self, identifier, mimetype):
    ext = 'dat'
    if mimetype in self.config.FILE_EXTENSIONS:
      ext = self.config.FILE_EXTENSIONS[mimetype]
    if ext == 'dat':
      logging.warn("No entry in config.FILE_EXTENSIONS for '%s'", mimetype)
      sys.stderr.write("WARNING: No entry in config.FILE_EXTENSIONS for '%s'\n" % mimetype)
    # Verhindere Dateinamen > 255 Zeichen
    identifier = identifier[:192]
    return identifier + '.' + ext

  def save_document_file(self, content, identifier, mimetype):
    """
    Creates a reconstructable folder hierarchy for documents
    """
    folder = self.make_document_path(identifier)
    if not os.path.exists(folder):
      os.makedirs(folder)
    path = folder + os.sep + self.make_document_filename(self, identifier, mimetype)
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


  def get_url(self, url):
    retry_counter = 0
    while retry_counter < 4:
      retry = False
      try:
        response = self.user_agent.open(url)
        return response
      except urllib2.HTTPError,e:
        if e.code == 502:
          retry_counter = retry_counter + 1
          retry = True
          log.info("HTTP Error 502 while getting %s, try again", url)
          if self.options.verbose:
            print "HTTP Error 502 while getting %s, try again" % url
          time.sleep(self.config.WAIT_TIME * 5)
        else:
          logging.critical("HTTP Error %s while getting %s", e.code, url)
          sys.stderr.write("CRITICAL ERROR:HTTP Error %s while getting %s" % (e.code, url))
    if retry_counter == 4 and retry == True:
      logging.critical("HTTP Error %s while getting %s", url)
      sys.stderr.write("CRITICAL ERROR:HTTP Error %s while getting %s" % url)
      return False

class TemplateError(Exception):
  def __init__(self, message):
    Exception.__init__(self, message)
